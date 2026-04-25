import os
import re
import logging
import asyncio

from src.core.pipeline import SeekerPipeline
from src.providers.base import LLMRequest, invoke_with_fallback
from src.core.goals.protocol import (
    AutonomousGoal, GoalBudget, GoalResult, GoalStatus, NotificationChannel
)
from config.models import CognitiveRole
from src.skills.self_improvement.code_validator import get_validator
from src.skills.self_improvement.error_database import ErrorDatabase, PendingPatchStore, sanitize_traceback

log = logging.getLogger("seeker.self_improvement")

class SelfImprovementGoal:
    """
    Motor de auto-cura de código. Lê os logs em busca de Tracebacks e Exceções,
    propõe correções usando LLMs avançados, e escreve o relatório de correção
    no diretório ativo (para ser aplicado ou para auto-aplicar se permitido).
    """

    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline
        self._status = GoalStatus.IDLE
        self._budget = GoalBudget(max_per_cycle_usd=0.20, max_daily_usd=1.0)
        self.last_log_byte_parsed = 0

        # Resolve caminho absoluto do log do Seeker
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        self.log_file = os.path.join(root_dir, "logs", "seeker.log")

        # ErrorDatabase — telemetria e dedup de erros
        self.error_db = ErrorDatabase()
        # PendingPatchStore — patches aguardando aprovação via Telegram
        self.pending_store = PendingPatchStore(db_path=self.error_db.db_path)

    @property
    def name(self) -> str:
        return "self_improvement_loop"

    @property
    def interval_seconds(self) -> int:
        return 21600  # A cada 6 horas ou pós-crash

    @property
    def budget(self) -> GoalBudget:
        return self._budget

    @property
    def channels(self) -> list[NotificationChannel]:
        return [NotificationChannel.TELEGRAM]

    def get_status(self) -> GoalStatus:
        return self._status

    async def run_cycle(self) -> GoalResult:
        self._status = GoalStatus.RUNNING
        cycle_cost = 0.0

        # Inicializa ErrorDB na primeira execução
        await self.error_db.init()

        if not os.path.exists(self.log_file):
            self._status = GoalStatus.IDLE
            return GoalResult(success=True, summary="Arquivo de log não encontrado para análise.", cost_usd=0.0)

        # Trunca se o log for menor que a marcação (houve rotação)
        file_size = os.path.getsize(self.log_file)
        if file_size < self.last_log_byte_parsed:
            self.last_log_byte_parsed = 0

        # Coleta novas linhas
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                f.seek(self.last_log_byte_parsed)
                new_logs = f.read()
                self.last_log_byte_parsed = f.tell()
        except Exception as e:
            log.error(f"[self_improvement] Erro de I/O: {e}", exc_info=True)
            self._status = GoalStatus.ERROR
            return GoalResult(success=False, summary=f"Falha ao ler log: {e}", cost_usd=0.0)

        if not new_logs:
            self._status = GoalStatus.IDLE
            return GoalResult(success=True, summary="Sem novos logs.", cost_usd=0.0)

        # Procura tracebacks
        exception_blocks = self._extract_exceptions(new_logs)

        if not exception_blocks:
            self._status = GoalStatus.IDLE
            return GoalResult(success=True, summary="Sem erros críticos nos logs recentes.", cost_usd=0.0)

        log.info(f"[self_improvement] Detectados {len(exception_blocks)} erros recentes. Analisando o mais grave...")
        target_error = exception_blocks[-1]  # Pega o último (mais recente)

        # Dedup: não gastar LLM call no mesmo erro repetido nas últimas 6h
        if await self.error_db.is_recent_duplicate(target_error, hours=6.0):
            self._status = GoalStatus.IDLE
            return GoalResult(
                success=True,
                summary="Erro recente já analisado (dedup 6h) — pulando.",
                cost_usd=0.0,
            )

        # Sanitiza traceback antes de enviar ao LLM (remove paths absolutos, secrets)
        target_error_safe = sanitize_traceback(target_error, max_len=2000)

        # Extrai arquivos do traceback (usa versão raw para paths reais no disco)
        import re
        file_paths = re.findall(r'File "(.*?)", line \d+', target_error)
        relevant_files = []
        for fp in set(file_paths):
            if "Seeker.Bot" in fp and os.path.exists(fp):
                relevant_files.append(fp)
        
        # Pega o arquivo principal do erro (geralmente o último no traceback que é do nosso código)
        target_file = relevant_files[-1] if relevant_files else None
        
        if not target_file:
            self._status = GoalStatus.IDLE
            return GoalResult(success=True, summary="Traceback não aponta para arquivo local do Seeker.", cost_usd=0.0)

        # 2. Ler o código fonte afetado
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                source_code = f.read()
        except (FileNotFoundError, IOError, UnicodeDecodeError) as e:
            log.error(f"[self_improvement] Falha ao ler {target_file}: {e}", exc_info=True)
            return GoalResult(success=True, summary="Falha ao ler arquivo afetado para o SARA.", cost_usd=0.0)

        # Registra erro no ErrorDB (usa path real para o arquivo, traceback sanitizado para LLM)
        error_type = target_error.strip().splitlines()[-1].split(":")[0].strip() if target_error.strip() else "Unknown"
        error_id = await self.error_db.record_error(target_error, target_file, error_type)

        prompt = (
            "Você é o S.A.R.A (Systematic Automatic Retrospective Analysis), o motor de auto-cura Nível 5 do Seeker.Bot.\n"
            "Analise o traceback abaixo e o código fonte original, corrija o bug ESTRITAMENTE, "
            "e retorne um JSON formatado exatamente assim:\n"
            "{\n"
            '  "rationale": "Explicação 1 linha",\n'
            '  "full_code": "O CÓDIGO FONTE COMPLETO corrigido (nunca trunque). Não use markdown ticks no valor."\n'
            "}\n\n"
            f"=== TARGET FILE ===\n{os.path.basename(target_file)}\n"
            f"=== ERROR TRACEBACK ===\n{target_error_safe}\n=======================\n\n"
            f"=== ORIGINAL SOURCE CODE ===\n{source_code}\n===========================\n"
        )

        from config.models import ModelRouter, DEEPSEEK_CHAT, CognitiveRole
        from src.core.utils import parse_llm_json
        import shutil
        
        try:
            # Cria um router one-off apenas com DeepSeek para tarefas analíticas pesadas
            deepseek_router = ModelRouter(routes={CognitiveRole.DEEP: [DEEPSEEK_CHAT]})
            
            response = await invoke_with_fallback(
                CognitiveRole.DEEP,
                LLMRequest(
                    messages=[{"role": "user", "content": prompt}],
                    system="Você retorna APENAS JSON válido sem marcações markdown extra.",
                    max_tokens=6144,
                    temperature=0.0
                ),
                deepseek_router,
                self.pipeline.api_keys,
            )
            cycle_cost += response.cost_usd
            
            try:
                # O parse_llm_json limpa os blocos markdown ```json
                repaired_data = parse_llm_json(response.text)
                new_code = repaired_data.get("full_code")
                rationale = repaired_data.get("rationale", "Correção automática aplicada.")
                
                if not new_code or len(new_code) < 10:
                    raise ValueError("Código vazio retornado.")

                # 3. Validar antes de escrever (CodeValidator — Day 2)
                filename = os.path.basename(target_file)
                validator = get_validator(use_pyright=True)
                validation = validator.validate(new_code, filename=filename)

                if not validation.passed:
                    # Patch inválido — preservar arquivo original
                    error_preview = "\n".join(validation.errors[:3])
                    log.warning(
                        f"[sara] Patch REJEITADO ({validation.stage_failed}) para {filename}: "
                        f"{validation.errors[0][:120] if validation.errors else 'sem detalhes'}"
                    )
                    # Registra patch rejeitado no ErrorDB
                    await self.error_db.record_patch(
                        error_id=error_id,
                        validation_passed=False,
                        stage_failed=validation.stage_failed,
                        applied=False,
                        cost_usd=cycle_cost,
                        rationale=rationale,
                    )
                    rejection_msg = (
                        f"🛡️ <b>S.A.R.A — PATCH REJEITADO</b>\n\n"
                        f"🐛 <b>Bug original:</b> <code>{target_error.splitlines()[-1][:120]}</code>\n"
                        f"📄 <b>Arquivo:</b> {filename}\n"
                        f"❌ <b>Validação falhou ({validation.stage_failed}):</b>\n"
                        f"<code>{error_preview[:400]}</code>\n\n"
                        f"<i>O arquivo original foi preservado. Revisão manual necessária.</i>"
                    )
                    self._status = GoalStatus.IDLE
                    return GoalResult(
                        success=False,
                        summary=f"Patch inválido ({validation.stage_failed}) — {filename} preservado",
                        notification=rejection_msg,
                        cost_usd=cycle_cost,
                        data={"sara_edits": 0, "validation_failed": True, "stage": validation.stage_failed}
                    )

                # 4. Patch válido — Solicitar aprovação via Telegram (ApprovalEngine)
                pending_id = await self.pending_store.create_pending(
                    file_path=target_file,
                    proposed_code=new_code,
                    rationale=rationale,
                )

                # Registra patch validado (não aplicado ainda — aguarda aprovação)
                await self.error_db.record_patch(
                    error_id=error_id,
                    validation_passed=True,
                    stage_failed=None,
                    applied=False,  # Será True após aprovação
                    cost_usd=cycle_cost,
                    rationale=rationale,
                )

                # Preview do diff: primeiras 5 linhas do código novo
                code_preview = "\n".join(new_code.splitlines()[:6])

                approval_msg = (
                    f"🛡️ <b>S.A.R.A — PATCH VALIDADO (aguardando aprovacao)</b>\n\n"
                    f"🐛 <b>Bug:</b> <code>{target_error.splitlines()[-1][:100]}</code>\n"
                    f"📄 <b>Arquivo:</b> {filename}\n"
                    f"✅ <b>Validacao:</b> ast + compile + pyright OK\n"
                    f"🧠 <b>Raciocinio:</b> {rationale}\n\n"
                    f"<b>Preview do patch:</b>\n<pre>{code_preview[:400]}...</pre>\n\n"
                    f"<i>Aprovacao necessaria antes de aplicar.</i>"
                )

                log.info(f"[sara] Patch {pending_id} criado para {filename} — aguardando aprovacao")

                self._status = GoalStatus.IDLE
                return GoalResult(
                    success=True,
                    summary=f"Patch validado para {filename} — aguardando aprovacao",
                    notification=approval_msg,
                    cost_usd=cycle_cost,
                    data={
                        "sara_edits": 0,  # Ainda não aplicado
                        "buttons": [[
                            {"text": "Aprovar", "callback_data": f"sara_approve:{pending_id}"},
                            {"text": "Rejeitar", "callback_data": f"sara_reject:{pending_id}"},
                        ]],
                    },
                )

            except Exception as parse_e:
                log.error(f"[sara] Falha no parser SARA: {parse_e}", exc_info=True)
                self._status = GoalStatus.ERROR
                return GoalResult(success=False, summary=f"Falha de parser SARA: {parse_e}", cost_usd=cycle_cost)

        except Exception as e:
            self._status = GoalStatus.ERROR
            return GoalResult(success=False, summary="Falha Cognitiva no Self Improvement", cost_usd=cycle_cost)

    def _extract_exceptions(self, text: str) -> list[str]:
        """Extrai blocos de Traceback de logs em raw string."""
        blocks = []
        lines = text.split('\n')
        in_traceback = False
        current_block = []
        
        for line in lines:
            if "Traceback (most recent call last):" in line or "Exception:" in line or "[ERROR]" in line:
                in_traceback = True
                if current_block:
                    blocks.append("\n".join(current_block))
                    current_block = []
            
            if in_traceback:
                current_block.append(line)
                if not line.startswith(" ") and "Traceback" not in line and "Error" in line:
                    blocks.append("\n".join(current_block))
                    current_block = []
                    in_traceback = False

        if current_block:
             blocks.append("\n".join(current_block))
        return blocks

    async def get_sara_stats(self) -> str:
        """Retorna telemetria do S.A.R.A formatada para Telegram (/sara ou health)."""
        await self.error_db.init()
        return await self.error_db.format_stats_for_telegram()

    def serialize_state(self) -> dict:
        return {"last_log_byte_parsed": self.last_log_byte_parsed}

    def load_state(self, state: dict) -> None:
        self.last_log_byte_parsed = state.get("last_log_byte_parsed", 0)

def create_goal(pipeline) -> SelfImprovementGoal:
    return SelfImprovementGoal(pipeline)
