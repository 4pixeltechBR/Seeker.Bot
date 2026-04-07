"""
Seeker.Bot — Deliberate Phase
src/core/phases/deliberate.py

Síntese com memória: 1-2 LLM calls, web search opcional.
Para: perguntas técnicas, explicações, tarefas que precisam de contexto.
"""

import asyncio
import logging
import re

from config.models import ModelRouter, CognitiveRole
from src.core.phases.base import PhaseContext, PhaseResult
from src.core.cognition.prompts import build_deliberate_prompt
from src.core.search.web import WebSearcher
from src.core.utils import parse_llm_json
from src.providers.base import LLMRequest, invoke_with_fallback

log = logging.getLogger("seeker.phases.deliberate")

# Regex para detectar se o input pede ação de escrita (click/mouse)
_WRITE_ACTION_RE = re.compile(
    r"cliqu[ea]|clicar|clique\s+(em|no|na|n[oa]s)|"
    r"arrast[ea]|arrastar|"
    r"press\s|pressione|apertar?\s|"
    r"abr[ae]\s|fechar?\s|minimiz|maximiz|"
    r"digit[ea]|escrev[ae]|type\s",
    re.IGNORECASE,
)


class DeliberatePhase:
    """Síntese com memória, 1-2 LLM calls, web opcional."""

    def __init__(
        self,
        router: ModelRouter,
        api_keys: dict[str, str],
        searcher: WebSearcher,
    ):
        self.router = router
        self.api_keys = api_keys
        self.searcher = searcher

    async def execute(self, ctx: PhaseContext) -> PhaseResult:
        total_cost = 0.0
        llm_calls = 0

        module_ctx = ""
        image_bytes = None
        if ctx.decision.forced_module:
            module_ctx = f"\nMódulo cognitivo: {ctx.decision.forced_module}"

        # ── Automação L3: Criação de Skill Autônoma ────────
        lower_in = ctx.user_input.lower()
        if "crie uma skill" in lower_in or "codifique" in lower_in or "crie código" in lower_in or "crie um código" in lower_in:
            from src.skills.skill_creator.coder import SkillCreatorEngine
            log.info("[deliberate] Intenção de CODIFICAÇÃO detectada. Redirecionando para SkillCreatorEngine.")
            res = await SkillCreatorEngine.process_coding_request(
                prompt=ctx.user_input,
                afk_protocol=ctx.afk_protocol,
                model_router=self.router,
                api_keys=self.api_keys,
            )
            return PhaseResult(response=res, cost_usd=0.0, llm_calls=1, image_bytes=None)

        # ── OS Control: Abrir aplicativos nativos ──────────
        if lower_in.startswith("abra ") or lower_in.startswith("abrir "):
            from src.skills.os_control.launcher import AppLauncher
            target = ctx.user_input.split(None, 1)[1] if " " in ctx.user_input else ""
            res = AppLauncher.launch(target)
            return PhaseResult(response=f"Comando executado: {res}", cost_usd=0.0, llm_calls=0, image_bytes=None)

        # ── Ferramentas internas (IMAP, Visão, etc) ──────────
        tool_context = ""
        if ctx.decision.forced_module == "email":
            log.info("[deliberate] Acessando emails via IMAP")
            tool_context = await self._fetch_emails()
        elif ctx.decision.forced_module == "vision":
            log.info("[deliberate] Ativando módulo de visão")
            is_write_action = bool(_WRITE_ACTION_RE.search(ctx.user_input))

            try:
                vision_result, vision_image = await self._handle_vision(ctx)
            except Exception as e:
                log.error(f"[deliberate] Exceção fatal no módulo de visão: {e}", exc_info=True)
                # Retorna erro direto — NUNCA deixa cair no LLM genérico
                # (que alucinaria "não tenho mãos para clicar")
                return PhaseResult(
                    response=(
                        f"⚠️ <b>Erro no módulo de visão</b>\n\n"
                        f"A operação falhou: <code>{e}</code>\n\n"
                        f"Possíveis causas:\n"
                        f"• Ollama não está rodando ou modelo VLM não carregou\n"
                        f"• Timeout na inferência (GPU ocupada)\n"
                        f"• Falha na captura de tela\n\n"
                        f"<i>Tente novamente ou verifique o status do Ollama.</i>"
                    ),
                    cost_usd=0.0,
                    llm_calls=0,
                    image_bytes=None,
                )

            if is_write_action:
                # Ações de escrita (clique, digitação, etc) retornam DIRETO
                # sem passar pelo LLM — o desktop controller já executou a ação
                return PhaseResult(
                    response=vision_result.replace("\n\n", "", 1).strip(),
                    cost_usd=0.0,
                    llm_calls=0,
                    image_bytes=vision_image,
                )
            else:
                # Leituras (screenshot) injetam o resultado como contexto para o LLM interpretar
                tool_context = vision_result
                image_bytes = vision_image

        # ── Web Search se necessário (factual queries) ────────
        web_section = ""
        if ctx.decision.needs_web:
            log.info("[deliberate] Web search ativado (query factual)")
            try:
                search_queries = await asyncio.wait_for(
                    self._generate_search_queries(ctx.user_input), timeout=15.0
                )
                search_results = await asyncio.wait_for(
                    self.searcher.search_multiple(
                        search_queries, max_results_per_query=3
                    ), timeout=25.0
                )
                web_parts = [sr.to_context(max_results=3) for sr in search_results if sr.results]
                if web_parts:
                    web_section = "\n\n━━━ DADOS DA WEB ━━━\n" + "\n\n".join(web_parts)
                llm_calls += 1  # query generation
            except asyncio.TimeoutError:
                log.warning("[deliberate] Web search falhou por timeout")
            except Exception as e:
                log.warning(f"[deliberate] Web search falhou: {e}")

        system = build_deliberate_prompt(
            module_context=module_ctx,
            memory_context=ctx.memory_prompt,
            session_context=ctx.session_context,
            web_context=web_section + tool_context,
        )

        # Sem web → modelo FAST (rápido, tier cloud)
        # Com web → cloud SYNTHESIS (precisa de qualidade pra interpretar resultados)
        role = CognitiveRole.FAST if not ctx.decision.needs_web else CognitiveRole.SYNTHESIS

        try:
            response = await asyncio.wait_for(
                invoke_with_fallback(
                    role=role,
                    request=LLMRequest(
                        messages=[{"role": "user", "content": ctx.user_input}],
                        system=system,
                        max_tokens=4000,
                        temperature=0.15,
                    ),
                    router=self.router,
                    api_keys=self.api_keys,
                ),
                timeout=180.0
            )
            total_cost += response.cost_usd
            llm_calls += 1
        except asyncio.TimeoutError:
            log.error("[deliberate] Síntese principal sofreu timeout fatal longo (>180s)")
            return PhaseResult(
                response="[Seeker] Pipeline abortado por timeout na malha de fallbacks (Fase de síntese).",
                cost_usd=total_cost,
                llm_calls=llm_calls,
                image_bytes=image_bytes,
            )
        except Exception as e:
            log.error(f"[deliberate] Síntese principal falhou fatalmente: {e}")
            raise

        return PhaseResult(
            response=response.text,
            cost_usd=total_cost,
            llm_calls=llm_calls,
            image_bytes=image_bytes,
        )

    # ─────────────────────────────────────────────────────────
    # VISION — Router interno: Leitura vs Ação
    # ─────────────────────────────────────────────────────────

    async def _handle_vision(self, ctx: PhaseContext) -> tuple[str, bytes | None]:
        """
        Decide se é leitura (screenshot) ou ação (clique/mouse) e despacha
        para o DesktopController apropriado.

        P2 Optimization: Para ações L3, extract_params (LLM) e health_check (HTTP)
        rodam em paralelo — economiza 1-3s no caminho crítico.
        """
        from src.skills.vision.desktop_controller import DesktopController

        if not ctx.afk_protocol:
            return "\n\n[AFKProtocol ausente — visão não autorizada]", None

        controller = DesktopController(ctx.afk_protocol)

        # Fluxo normal da Visão L1/L3
        is_write = bool(_WRITE_ACTION_RE.search(ctx.user_input))

        if is_write:
            log.info("[deliberate] Visão: modo AÇÃO (Desktop Takeover L3)")
            # P2: Paraleliza extract_params (LLM) com health_check (HTTP)
            params_task = asyncio.create_task(
                self._extract_l3_params(ctx.user_input)
            )
            warmup_task = asyncio.create_task(
                controller.vlm.health_check()
            )

            params = await params_task
            vlm_ok = await warmup_task

            if not vlm_ok:
                log.warning("[deliberate] VLM indisponível após pré-aquecimento")
                # Não aborta — execute_action fará seu próprio health_check
                # (que agora retornará do cache, graças ao P3)

            return await controller.execute_action(
                action_description=ctx.user_input,
                element_description=params.get("element"),
                text_to_type=params.get("text_to_type"),
                hotkey=params.get("hotkey"),
            )
        else:
            log.info("[deliberate] Visão: modo LEITURA (Screenshot L1)")
            return await controller.read_screen()

    async def _extract_l3_params(self, user_input: str) -> dict:
        """
        Usa LLM FAST para extrair os detalhes da ação (clique, digitação, atalho).
        Ex: "Clique na busca e escreva teste" → {"element": "busca", "text_to_type": "teste"}
        """
        try:
            response = await invoke_with_fallback(
                role=CognitiveRole.FAST,
                request=LLMRequest(
                    messages=[{
                        "role": "user",
                        "content": (
                            f"Instrução: Analise o comando do usuário e extraia 3 parâmetros de automação:\n"
                            f"1. 'element': O elemento a ser clicado/focado (ex: botão de salvar, campo vazia). Retorne 'null' se aplicar a atalho global.\n"
                            f"2. 'text_to_type': Texto EXATO para ser digitado, se houver.\n"
                            f"3. 'hotkey': Array de teclas para atalho, ex ['ctrl', 'c'], se houver.\n\n"
                            f"Comando: \"{user_input}\"\n\n"
                            f"Retorne APENAS um JSON válido contendo essas 3 chaves."
                        ),
                    }],
                    max_tokens=200,
                    temperature=0.0,
                    response_format="json"
                ),
                router=self.router,
                api_keys=self.api_keys,
            )
            data = parse_llm_json(response.text)
            return {
                "element": data.get("element"),
                "text_to_type": data.get("text_to_type"),
                "hotkey": data.get("hotkey")
            }
        except Exception as e:
            log.warning(f"[deliberate] Falha ao extrair parâmetros L3: {e}")
            # Fallback: extrai alvo óbvio via regex em vez de usar frase inteira
            m = re.search(
                r'(?:cliqu[ea]\s+(?:em|no|na|nos|nas)\s+|bot[aã]o\s+)'
                r'(.+?)(?:\s+(?:e\s|para\s|na\s|no\s|da\s|do\s|que\s)|$|\.)',
                user_input, re.IGNORECASE,
            )
            element = m.group(1).strip() if m else user_input[:60]
            return {"element": element, "text_to_type": None, "hotkey": None}

    # ─────────────────────────────────────────────────────────
    # SEARCH QUERIES
    # ─────────────────────────────────────────────────────────

    async def _generate_search_queries(self, user_input: str) -> list[str]:
        """Gera 2-3 queries de busca otimizadas (em inglês) via modelo FAST."""
        try:
            response = await invoke_with_fallback(
                role=CognitiveRole.FAST,
                request=LLMRequest(
                    messages=[{
                        "role": "user",
                        "content": (
                            f"Gere 2-3 queries de busca web curtas e específicas (em inglês, "
                            f"pra melhores resultados) para investigar esta pergunta:\n\n"
                            f"{user_input}\n\n"
                            f'Retorne APENAS JSON: {{"queries": ["query1", "query2"]}}'
                        ),
                    }],
                    max_tokens=200,
                    temperature=0.0,
                    response_format="json",
                ),
                router=self.router,
                api_keys=self.api_keys,
            )
            data = parse_llm_json(response.text)
            queries = data.get("queries", [])
            if queries and isinstance(queries, list):
                return [q for q in queries if isinstance(q, str) and len(q) > 3][:3]
        except Exception as e:
            log.warning(f"[deliberate] Falha ao gerar queries: {e}")

        return [user_input[:100]]

    # ─────────────────────────────────────────────────────────
    # EMAIL
    # ─────────────────────────────────────────────────────────

    async def _fetch_emails(self, max_emails: int = 10) -> str:
        """Busca emails via IMAP pra injetar no contexto."""
        try:
            from src.channels.email.imap_reader import IMAPReader
            reader = IMAPReader.from_env()
            if not reader:
                return "\n\n[IMAP não configurado — sem acesso a emails]"
            
            emails = await reader.fetch_unread_emails(max_emails=max_emails)
            if not emails:
                return "\n\n━━━ EMAILS ━━━\nCaixa de entrada vazia (0 não lidos)."
            
            lines = [f"\n\n━━━ EMAILS ({len(emails)} não lidos) ━━━"]
            for em in emails:
                lines.append(
                    f"\nDe: {em['sender']}\n"
                    f"Assunto: {em['subject']}\n"
                    f"Conteúdo: {em['body'][:500]}\n"
                    f"{'─' * 30}"
                )
            return "\n".join(lines)
        except Exception as e:
            log.warning(f"[deliberate] IMAP falhou: {e}")
            return f"\n\n[Falha ao acessar emails: {e}]"

