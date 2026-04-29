import os
import re
import logging
import asyncio
import shutil
import time

from src.core.pipeline import SeekerPipeline
from src.providers.base import LLMRequest, invoke_with_fallback
from src.core.goals.protocol import (
    AutonomousGoal, GoalBudget, GoalResult, GoalStatus, NotificationChannel
)
from config.models import CognitiveRole
from src.skills.self_improvement.code_validator import get_validator
from src.skills.self_improvement.error_database import ErrorDatabase, PendingPatchStore, sanitize_traceback
from src.skills.self_improvement.patch_engine import apply_changes, generate_diff_preview, PatchError
from src.core.reasoning.ooda_loop import OODALoop, ObservationData, OrientationModel, Decision, ActionResult, LoopResult
from src.core.utils import parse_llm_json

log = logging.getLogger("seeker.self_improvement")

class SelfImprovementGoal:
    """
    Motor de auto-cura de código autônomo (S.A.R.A).
    Integrado com o OODA Loop formal para inferir o nível de risco (Autonomy Tier).
    Erros em core/infraestrutura exigem aprovação (Tier 1),
    Erros isolados em skills são curados de forma 100% autônoma (Tier 3).
    """

    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline
        self._status = GoalStatus.IDLE
        self._budget = GoalBudget(max_per_cycle_usd=0.20, max_daily_usd=1.0)
        self.last_log_byte_parsed = 0
        
        self.ooda = OODALoop()
        self._current_context = {}

        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        self.log_file = os.path.join(root_dir, "logs", "seeker.log")

        self.error_db = ErrorDatabase()
        self.pending_store = PendingPatchStore(db_path=self.error_db.db_path)

    @property
    def name(self) -> str: return "self_improvement_loop"

    @property
    def interval_seconds(self) -> int: return 21600

    @property
    def budget(self) -> GoalBudget: return self._budget

    @property
    def channels(self) -> list[NotificationChannel]: return [NotificationChannel.TELEGRAM]

    def get_status(self) -> GoalStatus: return self._status

    async def run_cycle(self) -> GoalResult:
        self._status = GoalStatus.RUNNING
        await self.error_db.init()

        if not os.path.exists(self.log_file):
            self._status = GoalStatus.IDLE
            return GoalResult(success=True, summary="Arquivo de log não encontrado.", cost_usd=0.0)

        file_size = os.path.getsize(self.log_file)
        if file_size < self.last_log_byte_parsed:
            self.last_log_byte_parsed = 0

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

        exception_blocks = self._extract_exceptions(new_logs)
        if not exception_blocks:
            self._status = GoalStatus.IDLE
            return GoalResult(success=True, summary="Sem erros críticos.", cost_usd=0.0)

        target_error = exception_blocks[-1]
        log.info(f"[sara] OODA Loop iniciado para o erro mais recente.")

        # Injeta contexto para ser carregado pelo ciclo OODA
        self._current_context = {"raw_traceback": target_error, "cycle_cost": 0.0, "notification": None, "buttons": None}

        # Executa o OODA Loop formal
        iteration = await self.ooda.execute(
            user_input="sara_trigger",
            observe_fn=self._sara_observe,
            orient_fn=self._sara_orient,
            decide_fn=self._sara_decide,
            act_fn=self._sara_act
        )

        self._status = GoalStatus.IDLE
        cost = self._current_context.get("cycle_cost", 0.0)
        
        # Converte o LoopResult no GoalResult
        if iteration.result == LoopResult.SUCCESS:
            return GoalResult(
                success=True,
                summary="S.A.R.A Cycle OK",
                cost_usd=cost,
                notification=self._current_context.get("notification"),
                data={"buttons": self._current_context.get("buttons")} if self._current_context.get("buttons") else None
            )
        else:
            return GoalResult(
                success=False,
                summary=f"S.A.R.A Cycle Aborted/Failed: {iteration.action_result.error if iteration.action_result else 'Unknown'}",
                cost_usd=cost,
                notification=self._current_context.get("notification")
            )

    # ─── OODA LOOP PHASES ────────────────────────────────────────────────────────

    async def _sara_observe(self, user_input: str, context: dict) -> ObservationData:
        ctx = self._current_context
        target_error = ctx["raw_traceback"]
        
        # Dedup Check
        ctx["is_duplicate"] = await self.error_db.is_recent_duplicate(target_error, hours=6.0)
        
        target_error_safe = sanitize_traceback(target_error, max_len=2000)
        ctx["target_error_safe"] = target_error_safe
        
        file_paths = re.findall(r'File "(.*?)", line \d+', target_error)
        relevant_files = [fp for fp in set(file_paths) if "Seeker.Bot" in fp and os.path.exists(fp)]
        target_file = relevant_files[-1] if relevant_files else None
        
        ctx["target_file"] = target_file
        
        target_line = None
        if target_file:
            for match in re.finditer(r'File "' + re.escape(target_file) + r'", line (\d+)', target_error):
                target_line = int(match.group(1))
                
        ctx["target_line"] = target_line
        ctx["error_type"] = target_error.strip().splitlines()[-1].split(":")[0].strip() if target_error.strip() else "Unknown"
        
        if target_file:
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    all_lines = f.readlines()
                ctx["source_code"] = "".join(all_lines)
                
                MAX_LINES = 150
                if len(all_lines) > MAX_LINES and target_line:
                    start = max(0, target_line - 60)
                    end = min(len(all_lines), target_line + 60)
                    source_section = "".join(all_lines[start:end])
                    section_note = f"[Exibindo linhas {start+1}-{end} de {len(all_lines)} totais. Linha do erro: {target_line}]"
                    ctx["source_for_llm"] = f"{section_note}\n{source_section}"
                else:
                    ctx["source_for_llm"] = ctx["source_code"]
            except Exception as e:
                log.error(f"[sara] Fail read file: {e}")
                ctx["source_code"] = ""
                ctx["source_for_llm"] = ""
        else:
            ctx["source_code"] = ""
            ctx["source_for_llm"] = ""

        return ObservationData(user_input=target_error)

    async def _sara_orient(self, obs: ObservationData) -> OrientationModel:
        ctx = self._current_context
        constraints = []
        
        if ctx.get("is_duplicate"):
            constraints.append("Duplicate error")
            
        target_file = ctx.get("target_file", "")
        
        # Risk Assessment (Autonomy Tier Determination)
        tier = 1
        reasoning = ""
        
        if not target_file:
            tier = 1
            reasoning = "Nenhum arquivo local identificado no traceback."
        elif "src\\core" in target_file or "src/core" in target_file or "bot.py" in target_file or "message.py" in target_file:
            tier = 1 # MANUAL
            reasoning = "Módulo Core ou Roteador (Risco Crítico). Exige aprovação manual."
        elif "src\\skills" in target_file or "src/skills" in target_file:
            if "self_improvement" in target_file:
                tier = 1
                reasoning = "O SARA não deve modificar a si mesmo sem supervisão."
            else:
                tier = 3 # AUTONOMOUS
                reasoning = "Skill isolada. Impacto de blast-radius baixo. Seguro para auto-cura."
        else:
            tier = 2 # REVERSIBLE
            reasoning = "Módulo de domínio geral."

        ctx["autonomy_tier"] = tier
        return OrientationModel(
            confidence=0.9 if not ctx.get("is_duplicate") else 0.0,
            constraints=constraints,
            reasoning=reasoning
        )

    async def _sara_decide(self, orient: OrientationModel) -> Decision:
        ctx = self._current_context
        
        if "Duplicate error" in orient.constraints:
            return Decision(action_type="abort", rationale="Erro duplicado nas últimas 6h.", verification_required=False)
            
        if not ctx.get("target_file") or not ctx.get("source_for_llm"):
            return Decision(action_type="abort", rationale="Arquivo não legível ou inexistente.", verification_required=False)
            
        # Error record mapping
        ctx["error_id"] = await self.error_db.record_error(ctx["raw_traceback"], ctx["target_file"], ctx["error_type"])

        prompt = (
            "Você é o S.A.R.A (Systematic Automatic Retrospective Analysis).\n"
            "Analise o traceback e o código fonte. Retorne APENAS este JSON:\n"
            "{\n"
            '  "rationale": "Explicação do bug em 1 linha",\n'
            '  "changes": [\n'
            '    {"search": "bloco exato", "replace": "bloco corrigido"}\n'
            '  ]\n'
            "}\n"
            "REGRAS:\n1. 'search' copia EXATA.\n2. Inclua apenas linhas que mudam.\n"
            f"=== TARGET FILE ===\n{os.path.basename(ctx['target_file'])}\n"
            f"=== TRACEBACK ===\n{ctx['target_error_safe']}\n================\n"
            f"=== SOURCE ===\n{ctx['source_for_llm']}\n================\n"
        )
        
        try:
            response = await invoke_with_fallback(
                CognitiveRole.FAST,
                LLMRequest(
                    messages=[{"role": "user", "content": prompt}],
                    system="Retorne JSON puro.", max_tokens=8192, temperature=0.0
                ),
                self.pipeline.model_router,
                self.pipeline.api_keys,
            )
            ctx["cycle_cost"] += response.cost_usd
            
            repaired_data = parse_llm_json(response.text)
            rationale = repaired_data.get("rationale", "Auto-correção.")
            changes = repaired_data.get("changes")
            full_code_fallback = repaired_data.get("full_code")

            source_code = ctx["source_code"]
            if changes:
                new_code = apply_changes(source_code, changes)
            elif full_code_fallback and len(full_code_fallback) > 10:
                new_code = full_code_fallback
            else:
                raise ValueError("JSON sem changes ou full_code.")

            # Validation Phase
            filename = os.path.basename(ctx["target_file"])
            validator = get_validator(use_pyright=True)
            validation = validator.validate(new_code, filename=filename)

            ctx["patch_data"] = {
                "new_code": new_code,
                "rationale": rationale,
                "validation": validation,
                "changes_count": len(changes) if changes else 1,
                "diff_preview": generate_diff_preview(source_code, new_code, filename)
            }

            if not validation.passed:
                return Decision(action_type="reject_patch", rationale=f"Falha de validação: {validation.stage_failed}", verification_required=False)
            
            return Decision(action_type="apply_patch", autonomy_tier=ctx["autonomy_tier"], rationale=orient.reasoning, verification_required=False)
            
        except Exception as e:
            log.error(f"[sara] Exception no Decide: {e}")
            return Decision(action_type="abort", rationale=f"Falha LLM: {str(e)}", verification_required=False)

    async def _sara_act(self, decision: Decision) -> ActionResult:
        ctx = self._current_context
        
        if decision.action_type == "abort":
            return ActionResult(success=True, error=decision.rationale)
            
        pd = ctx.get("patch_data", {})
        error_id = ctx.get("error_id")
        filename = os.path.basename(ctx["target_file"])
        
        if decision.action_type == "reject_patch":
            await self.error_db.record_patch(
                error_id=error_id, validation_passed=False, stage_failed=pd["validation"].stage_failed,
                applied=False, cost_usd=ctx["cycle_cost"], rationale=pd["rationale"]
            )
            rejection_msg = (
                f"🛡️ <b>S.A.R.A — PATCH REJEITADO</b>\n\n"
                f"🐛 <b>Bug:</b> <code>{ctx['error_type']}</code>\n"
                f"❌ <b>Falha ({pd['validation'].stage_failed})</b>\n"
                f"<i>Revisão manual necessária.</i>"
            )
            ctx["notification"] = rejection_msg
            return ActionResult(success=False, error="Validação Falhou")
            
        if decision.action_type == "apply_patch":
            tier = decision.autonomy_tier
            
            if tier == 3:
                # AUTÔNOMO: Aplica o patch direto no arquivo
                try:
                    with open(ctx["target_file"], "w", encoding="utf-8") as f:
                        f.write(pd["new_code"])
                        
                    await self.error_db.record_patch(
                        error_id=error_id, validation_passed=True, stage_failed=None,
                        applied=True, cost_usd=ctx["cycle_cost"], rationale=pd["rationale"]
                    )
                    
                    msg = (
                        f"🤖 <b>S.A.R.A — AUTO-CURA AUTÔNOMA (Tier 3)</b>\n\n"
                        f"🐛 <b>Corrigido:</b> <code>{ctx['error_type']}</code>\n"
                        f"📄 <b>Arquivo:</b> {filename}\n"
                        f"⚙️ <b>Motivo:</b> Impacto isolado, corrigido e aplicado via OODA Loop."
                    )
                    ctx["notification"] = msg
                    return ActionResult(success=True)
                except Exception as e:
                    return ActionResult(success=False, error=f"I/O error: {str(e)}")
                    
            else:
                # MANUAL/REVERSIBLE: Pendente para Telegram
                pending_id = await self.pending_store.create_pending(
                    file_path=ctx["target_file"], proposed_code=pd["new_code"], rationale=pd["rationale"]
                )
                await self.error_db.record_patch(
                    error_id=error_id, validation_passed=True, stage_failed=None,
                    applied=False, cost_usd=ctx["cycle_cost"], rationale=pd["rationale"]
                )
                
                preview_text = pd["diff_preview"] if pd["diff_preview"].strip() else "\n".join(pd["new_code"].splitlines()[:6])
                approval_msg = (
                    f"🛡️ <b>S.A.R.A — OODA LOOP (Aguardando Aprovação)</b>\n\n"
                    f"🐛 Bug: <code>{ctx['error_type']}</code>\n"
                    f"📄 Arquivo: {filename}\n"
                    f"🚥 Autonomy Tier: {tier} ({decision.rationale})\n"
                    f"🧠 Raciocínio: {pd['rationale']}\n\n"
                    f"Diff Preview:\n<code>{preview_text[:500]}</code>"
                )
                ctx["notification"] = approval_msg
                ctx["buttons"] = [[
                    {"text": "✅ Aprovar", "callback_data": f"sara_approve:{pending_id}"},
                    {"text": "❌ Rejeitar", "callback_data": f"sara_reject:{pending_id}"},
                ]]
                return ActionResult(success=True)

        return ActionResult(success=False, error="Unknown decision type")

    def _extract_exceptions(self, text: str) -> list[str]:
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
        if current_block: blocks.append("\n".join(current_block))
        return blocks

    async def get_sara_stats(self) -> str:
        await self.error_db.init()
        return await self.error_db.format_stats_for_telegram()

    def serialize_state(self) -> dict: return {"last_log_byte_parsed": self.last_log_byte_parsed}
    def load_state(self, state: dict) -> None: self.last_log_byte_parsed = state.get("last_log_byte_parsed", 0)

def create_goal(pipeline) -> SelfImprovementGoal:
    return SelfImprovementGoal(pipeline)
