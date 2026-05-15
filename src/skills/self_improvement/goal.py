import os
import re
import logging

from src.core.pipeline import SeekerPipeline
from src.providers.base import LLMRequest, invoke_with_fallback
from src.core.goals.protocol import (
    GoalBudget,
    GoalResult,
    GoalStatus,
    NotificationChannel,
)
from config.models import CognitiveRole
from src.skills.self_improvement.code_validator import get_validator
from src.skills.self_improvement.error_database import (
    ErrorDatabase,
    get_pending_store,
    sanitize_traceback,
)

log = logging.getLogger("seeker.self_improvement")


class SelfImprovementGoal:
    """
    Motor de auto-cura de código (S.A.R.A).

    Fluxo com CodeValidator + ErrorDatabase + PendingPatchStore (T-12):
    1. Lê logs novos, extrai tracebacks.
    2. Dedup 6h via ErrorDatabase.is_recent_duplicate.
    3. LLM propõe full_code corrigido.
    4. CodeValidator valida (ast.parse → compile → pyright).
    5. Patch validado vai para PendingPatchStore (não escreve no arquivo).
    6. Notificação com botões sara_approve:{id} / sara_reject:{id}.
    7. Callback em commands/system.py aplica ou descarta após clique humano.
    """

    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline
        self._status = GoalStatus.IDLE
        self._budget = GoalBudget(max_per_cycle_usd=0.20, max_daily_usd=1.0)
        self.last_log_byte_parsed = 0

        # Resolve caminho absoluto do log do Seeker
        root_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..")
        )
        self.log_file = os.path.join(root_dir, "logs", "seeker.log")

        # SARA primitives (T-12 wire-up)
        sara_db_path = os.path.join(root_dir, "data", "sara_errors.db")
        os.makedirs(os.path.dirname(sara_db_path), exist_ok=True)
        self.validator = get_validator(use_pyright=True)
        self.error_db = ErrorDatabase(db_path=sara_db_path)
        self.pending_store = get_pending_store(db_path=sara_db_path)

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

        if not os.path.exists(self.log_file):
            self._status = GoalStatus.IDLE
            return GoalResult(
                success=True,
                summary="Arquivo de log não encontrado para análise.",
                cost_usd=0.0,
            )

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
            return GoalResult(
                success=False, summary=f"Falha ao ler log: {e}", cost_usd=0.0
            )

        if not new_logs:
            self._status = GoalStatus.IDLE
            return GoalResult(success=True, summary="Sem novos logs.", cost_usd=0.0)

        # Procura tracebacks
        exception_blocks = self._extract_exceptions(new_logs)

        if not exception_blocks:
            self._status = GoalStatus.IDLE
            return GoalResult(
                success=True,
                summary="Sem erros críticos nos logs recentes.",
                cost_usd=0.0,
            )

        log.info(
            f"[self_improvement] Detectados {len(exception_blocks)} erros recentes. Analisando o mais grave..."
        )
        target_error = exception_blocks[-1]  # Pega o último (mais recente)

        # Sanitize traceback antes de qualquer LLM call (remove paths absolutos + secrets)
        clean_error = sanitize_traceback(target_error, max_len=2000)

        # T-12: Dedup 6h — evita gastar LLM call em traceback repetido
        if await self.error_db.is_recent_duplicate(clean_error, hours=6.0):
            self._status = GoalStatus.IDLE
            return GoalResult(
                success=True,
                summary="Traceback já analisado nas últimas 6h (dedup).",
                cost_usd=0.0,
            )

        # Envia pro LLM para análise e overwrite closed-loop (S.A.R.A)
        # 1. Extrair possiveis arquivos do traceback
        file_paths = re.findall(r'File "(.*?)", line \d+', target_error)
        relevant_files = []
        for fp in set(file_paths):
            if "Seeker.Bot" in fp and os.path.exists(fp):
                relevant_files.append(fp)

        # Pega o arquivo principal do erro (geralmente o último no traceback que é do nosso código)
        target_file = relevant_files[-1] if relevant_files else None

        if not target_file:
            self._status = GoalStatus.IDLE
            return GoalResult(
                success=True,
                summary="Traceback não aponta para arquivo local do Seeker.",
                cost_usd=0.0,
            )

        # T-12: Registra o erro no banco (vai ser linkado ao patch abaixo)
        error_type = "Unknown"
        last_line = target_error.strip().splitlines()[-1] if target_error.strip() else ""
        if ":" in last_line:
            error_type = last_line.split(":", 1)[0].strip()[:64]
        error_id = await self.error_db.record_error(
            traceback=clean_error,
            file_path=target_file,
            error_type=error_type,
        )

        # 2. Ler o código fonte afetado
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                source_code = f.read()
        except (FileNotFoundError, IOError, UnicodeDecodeError) as e:
            log.error(
                f"[self_improvement] Falha ao ler {target_file}: {e}", exc_info=True
            )
            return GoalResult(
                success=True,
                summary="Falha ao ler arquivo afetado para o SARA.",
                cost_usd=0.0,
            )

        prompt = (
            "Você é o S.A.R.A (Systematic Automatic Retrospective Analysis), o motor de auto-cura Nível 5 do Seeker.Bot.\n"
            "Analise o traceback abaixo e o código fonte original, corrija o bug ESTRITAMENTE, "
            "e retorne um JSON formatado exatamente assim:\n"
            "{\n"
            '  "rationale": "Explicação 1 linha",\n'
            '  "full_code": "O CÓDIGO FONTE COMPLETO corrigido (nunca trunque). Não use markdown ticks no valor."\n'
            "}\n"
            "CRÍTICO: NÃO invente caminhos de importação. Se faltar uma função e você não souber o módulo exato no projeto, NÃO adivinhe (isso causará ImportError). Escreva um fallback local.\n\n"
            f"=== TARGET FILE ===\n{target_file}\n"
            f"=== ERROR TRACEBACK ===\n{target_error[:2000]}\n=======================\n\n"
            f"=== ORIGINAL SOURCE CODE ===\n{source_code}\n===========================\n"
        )

        from config.models import ModelRouter, DEEPSEEK_CHAT
        from src.core.utils import parse_llm_json

        try:
            # Cria um router one-off apenas com DeepSeek para tarefas analíticas pesadas
            deepseek_router = ModelRouter(routes={CognitiveRole.DEEP: [DEEPSEEK_CHAT]})

            response = await invoke_with_fallback(
                CognitiveRole.DEEP,
                LLMRequest(
                    messages=[{"role": "user", "content": prompt}],
                    system="Você retorna APENAS JSON válido sem marcações markdown extra.",
                    max_tokens=6144,
                    temperature=0.0,
                ),
                deepseek_router,
                self.pipeline.api_keys,
            )
            cycle_cost += response.cost_usd

            try:
                # O parse_llm_json limpa os blocos markdown ```json
                repaired_data = parse_llm_json(response.text)
                new_code = repaired_data.get("full_code")
                rationale = repaired_data.get(
                    "rationale", "Correção automática aplicada."
                )

                if not new_code or len(new_code) < 10:
                    raise ValueError("Código vazio retornado.")

                # T-12: Validar antes de qualquer write
                vres = self.validator.validate(new_code, filename=target_file)
                if not vres.passed:
                    await self.error_db.record_patch(
                        error_id=error_id,
                        validation_passed=False,
                        stage_failed=vres.stage_failed,
                        applied=False,
                        cost_usd=response.cost_usd,
                        rationale=rationale,
                    )
                    self.pipeline.integrity.record_sara_attempt(success=False)
                    self._status = GoalStatus.IDLE
                    err_preview = (vres.errors[0] if vres.errors else "?")[:150]
                    log.warning(
                        f"[sara] Patch REJEITADO em stage={vres.stage_failed}: {err_preview}"
                    )
                    return GoalResult(
                        success=True,  # ciclo executou; só não aplicou
                        summary=(
                            f"Patch rejeitado pelo CodeValidator "
                            f"(stage={vres.stage_failed}): {err_preview}"
                        ),
                        cost_usd=cycle_cost,
                    )

                # T-12: Validou. Em vez de escrever direto, parqueia como pending
                # e devolve botões. O arquivo original NÃO é tocado até aprovação.
                pending_id = await self.pending_store.create_pending(
                    file_path=target_file,
                    proposed_code=new_code,
                    rationale=rationale,
                )
                await self.error_db.record_patch(
                    error_id=error_id,
                    validation_passed=True,
                    stage_failed=None,
                    applied=False,  # ainda não aplicado — aguarda aprovação
                    cost_usd=response.cost_usd,
                    rationale=rationale,
                )

                msg = (
                    f"🛡️ <b>S.A.R.A — Patch Proposto</b>\n\n"
                    f"🐛 <b>Traceback Interceptado:</b>\n<code>{target_error.splitlines()[-1]}</code>\n\n"
                    f"🔧 <b>Arquivo:</b> {os.path.basename(target_file)}\n"
                    f"🧠 <b>Raciocínio:</b> {rationale}\n"
                    f"✅ <b>Validação:</b> ast + compile + pyright passaram.\n\n"
                    f"<i>Patch validado aguardando sua aprovação (id={pending_id}, expira em 24h).</i>"
                )
                log.info(
                    f"[sara] Patch validado, aguardando aprovação: "
                    f"pending_id={pending_id} file={target_file}"
                )

                self._status = GoalStatus.IDLE
                return GoalResult(
                    success=True,
                    summary=f"Patch pendente para {os.path.basename(target_file)} (id={pending_id})",
                    notification=msg,
                    cost_usd=cycle_cost,
                    data={
                        "sara_edits": 1,
                        "pending_id": pending_id,
                        "buttons": [
                            [
                                {"text": "✅ Aprovar e aplicar",
                                 "callback_data": f"sara_approve:{pending_id}"},
                                {"text": "❌ Rejeitar",
                                 "callback_data": f"sara_reject:{pending_id}"},
                            ]
                        ],
                    },
                )

            except Exception as parse_e:
                self.pipeline.integrity.record_sara_attempt(success=False)
                log.error(f"[sara] Falha no parser SARA: {parse_e}", exc_info=True)
                self._status = GoalStatus.ERROR
                return GoalResult(
                    success=False,
                    summary=f"Falha de parser SARA: {parse_e}",
                    cost_usd=cycle_cost,
                )

        except Exception:
            self._status = GoalStatus.ERROR
            return GoalResult(
                success=False,
                summary="Falha Cognitiva no Self Improvement",
                cost_usd=cycle_cost,
            )

    def _extract_exceptions(self, text: str) -> list[str]:
        """Extrai blocos de Traceback de logs em raw string."""
        blocks = []
        lines = text.split("\n")
        in_traceback = False
        current_block = []

        for line in lines:
            if (
                "Traceback (most recent call last):" in line
                or "Exception:" in line
                or "[ERROR]" in line
            ):
                in_traceback = True
                if current_block:
                    blocks.append("\n".join(current_block))
                    current_block = []

            if in_traceback:
                current_block.append(line)
                if (
                    not line.startswith(" ")
                    and "Traceback" not in line
                    and "Error" in line
                ):
                    blocks.append("\n".join(current_block))
                    current_block = []
                    in_traceback = False

        if current_block:
            blocks.append("\n".join(current_block))
        return blocks

    def serialize_state(self) -> dict:
        return {"last_log_byte_parsed": self.last_log_byte_parsed}

    def load_state(self, state: dict) -> None:
        self.last_log_byte_parsed = state.get("last_log_byte_parsed", 0)


def create_goal(pipeline) -> SelfImprovementGoal:
    return SelfImprovementGoal(pipeline)
