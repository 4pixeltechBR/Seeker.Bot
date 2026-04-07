"""
Seeker.Bot — Desktop Controller
src/skills/vision/desktop_controller.py

Controlador centralizado do Desktop Takeover.
Orquestra o ciclo completo: Screenshot → VLM → Mouse → Confirmação.

Hierarquia de segurança:
  L1 (Leitura)  → tier=1, action_type="read"  → timeout = abort
  L3 (Escrita)  → tier=1, action_type="write" → SEMPRE exige aprovação humana explícita

O Kill Switch do MouseEngine aborta qualquer operação se o humano agarrar o mouse.
"""

import asyncio
import logging

from src.skills.vision.afk_protocol import AFKProtocol, PermissionResult
from src.skills.vision.screenshot import capture_desktop
from src.skills.vision.vlm_client import VLMClient
from src.skills.vision.mouse_engine import MouseEngine, UserInterventionException
from src.skills.vision.keyboard_engine import KeyboardEngine
from src.skills.vision.audit import VisionAudit

log = logging.getLogger("seeker.vision.controller")


class DesktopController:
    """
    Centraliza todas as operações de Desktop Takeover.

    Modos:
      - read_screen()   → L1: captura + analisa (somente leitura)
      - execute_action() → L3: captura + foca + clica + digita + confirma

    Ambos retornam (context_string, image_bytes | None) para injeção no pipeline.
    """

    def __init__(self, afk_protocol: AFKProtocol):
        self.afk = afk_protocol
        self.vlm = VLMClient()
        self.mouse = MouseEngine()
        self.keyboard = KeyboardEngine()
        self.audit = VisionAudit()
        self._mouse_listener_started = False
        self._keyboard_listener_started = False

    # (L1 fica inalterado, vou manter da linha 31 até 78 do block abaixo)
    
    async def read_screen(self, reason: str = "Capturar screenshot para análise visual.") -> tuple[str, bytes | None]:
        # ... Mantém lógica atual
        if not self.afk:
            return "\n\n[AFKProtocol ausente — visão não autorizada]", None

        try:
            # 1. Permissão L1 Read
            res = await self.afk.request_permission(
                reason=reason, tier=1, action_type="read"
            )
            if res not in (PermissionResult.APPROVED, PermissionResult.AFK):
                return f"\n\n[Captura negada: {res.name}]", None

            # 2. Captura
            screenshot_bytes = await capture_desktop()
            log.info("[controller] Screenshot capturado com sucesso")

            # 3. Audit — salva o frame antes de qualquer processamento
            await self.audit.init_session("read_screen")
            await self.audit.log_frame("capture", screenshot_bytes)

            # 4. VLM — análise (com fallback gracioso)
            if not await self.vlm.health_check():
                log.warning("[controller] VLM indisponível — enviando foto sem análise")
                return (
                    "\n\n[SISTEMA: A tela foi CAPTURADA com SUCESSO e anexada à sua resposta. "
                    "O módulo VLM não estava disponível para ler o conteúdo. "
                    "Diga ao usuário que o print foi tirado e enviado com sucesso, "
                    "mas que não foi possível analisar o texto na tela.]"
                ), screenshot_bytes

            log.info("[controller] VLM: analisando frame...")
            analysis = await self.vlm.describe_page(screenshot_bytes)

            context = f"\n\n━━━ SCREENSHOT ANALISADO ━━━\n{analysis}"
            return context, screenshot_bytes

        except Exception as e:
            log.error(f"[controller] Falha na leitura: {e}", exc_info=True)
            # Preserva bytes capturados mesmo em erro
            captured = screenshot_bytes if 'screenshot_bytes' in locals() else None
            return (
                f"\n\n[SISTEMA: A tela foi CAPTURADA e anexada à resposta. "
                f"Ocorreu um erro no módulo VLM ({e}), mas a foto foi enviada.]"
            ), captured

    # ──────────────────────────────────────────────────────
    # L3: AÇÃO — Captura + Foca + Clica + Digita
    # ──────────────────────────────────────────────────────

    async def execute_action(
        self,
        action_description: str,
        element_description: str | None = None,
        text_to_type: str | None = None,
        hotkey: list[str] | None = None,
    ) -> tuple[str, bytes | None]:
        """
        Executa uma ação combinada no desktop.
        
        P4 Optimization: Confirmation screenshot + VLM analysis é feito apenas
        para ações que envolvem digitação ou hotkeys. Cliques simples retornam
        screenshot bruto sem análise VLM — economia de 3-8s.
        """
        if not self.afk:
            return "\n\n[AFKProtocol ausente — ação não autorizada]", None

        screenshot_bytes = None
        target_x, target_y, confidence = None, None, None

        try:
            # 1. Permissão L3 Write — SEMPRE exige aprovação explícita
            res = await self.afk.request_permission(
                reason=f"Desktop Takeover L3: {action_description}\n"
                       f"Elemento alvo: {element_description or 'Nenhum'}\n"
                       f"Texto: {text_to_type or 'Nenhum'}\n"
                       f"Atalho: {'+'.join(hotkey) if hotkey else 'Nenhum'}",
                tier=1,
                action_type="write",
            )
            if res != PermissionResult.APPROVED:
                return f"\n\n[Ação L3 negada: {res.name}. Controle requer aprovação explícita.]", None

            log.info(f"[controller] L3 APROVADO — Ação: {action_description}")

            screenshot_bytes = await capture_desktop()
            await self.audit.init_session("desktop_action")
            await self.audit.log_frame("before_action", screenshot_bytes)

            if not await self.vlm.health_check():
                return "\n\n[SISTEMA: VLM indisponível. Ollama precisa estar ativo.]", screenshot_bytes

            # 2. Inicia os Kill Switches
            if not self._mouse_listener_started:
                 await self.mouse.start_listener()
                 self._mouse_listener_started = True
            if not self._keyboard_listener_started:
                 await self.keyboard.start_listener()
                 self._keyboard_listener_started = True

            # 3. Localizar elemento e Clicar
            if element_description and element_description.lower() not in ["nenhum", "tela", "vazio"]:
                log.info(f"[controller] VLM: localizando '{element_description}'...")
                bbox = await self.vlm.locate_element(screenshot_bytes, element_description)
                if not bbox or bbox.get("confidence", 0) < 0.3:
                    analysis = await self.vlm.describe_page(screenshot_bytes)
                    return f"\n\n[SISTEMA: Falha localizando '{element_description}'.\n{analysis}]", screenshot_bytes
                
                target_x, target_y = int(bbox["x"]), int(bbox["y"])
                confidence = bbox.get("confidence", 0.5)
                await self.mouse.move_to(target_x, target_y, duration=0.8)
                await self.mouse.click()
                await asyncio.sleep(0.5)

            # 4. Digitar Texto
            if text_to_type:
                await self.keyboard.type_text(text_to_type)
                await asyncio.sleep(0.5)

            # 5. Apertar Atalho
            if hotkey:
                await self.keyboard.press_hotkey(*hotkey)
                await asyncio.sleep(0.5)

            # 6. Confirmação — P4: VLM analysis só para ações complexas
            needs_visual_confirm = bool(text_to_type or hotkey)

            await asyncio.sleep(0.5 if not needs_visual_confirm else 1.0)
            confirm_bytes = await capture_desktop()
            await self.audit.log_frame("after_action", confirm_bytes)

            if needs_visual_confirm:
                # Ação complexa (digitação/hotkey) — analisa resultado via VLM
                after_analysis = await self.vlm.describe_page(confirm_bytes)
                context = (
                    f"\n\n━━━ AÇÃO EXECUTADA COM SUCESSO ━━━\n"
                    f"Ação L3: {action_description}\n"
                    f"━━━ TELA APÓS AÇÃO ━━━\n{after_analysis}"
                )
            else:
                # Clique simples — skip VLM analysis, retorna screenshot bruto
                log.info("[controller] P4: Clique simples — skip VLM confirm analysis")
                context = (
                    f"\n\n━━━ AÇÃO EXECUTADA COM SUCESSO ━━━\n"
                    f"Ação L3: {action_description}\n"
                    f"Elemento: {element_description or 'N/A'}\n"
                    f"[Screenshot de confirmação anexado]"
                )

            return context, confirm_bytes

        except UserInterventionException as e:
            log.warning(f"[controller] 🚨 KILL SWITCH ATIVADO: {e}")
            captured = screenshot_bytes if 'screenshot_bytes' in locals() else None
            return f"\n\n[SISTEMA: KILL SWITCH! Ação ABORTADA pelo usuário. Nenhum outro comando de digitação foi computado.]", captured
        except Exception as e:
            log.error(f"[controller] Falha na ação L3: {e}", exc_info=True)
            captured = screenshot_bytes if 'screenshot_bytes' in locals() else None
            return f"\n\n[SISTEMA: Erro no Desktop Takeover: {e}.]", captured

    # ──────────────────────────────────────────────────────
    # CLEANUP
    # ──────────────────────────────────────────────────────

    async def shutdown(self):
        """Desliga listener de mouse/teclado e descarrega VLM."""
        if self._mouse_listener_started:
            await self.mouse.stop_listener()
        if self._keyboard_listener_started:
            await self.keyboard.stop_listener()
        try:
            await self.vlm.unload_model()
        except Exception:
            pass

