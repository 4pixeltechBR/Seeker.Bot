import asyncio
import logging
import pyautogui
from pynput import keyboard

log = logging.getLogger("seeker.vision.keyboard")

class KeyboardEngine:
    """
    Engine para Digitação Autônoma (Desktop Takeover L3).
    Usa pynput para Kill Switch: Se o botão ESC for pressionado durante a digitação autônoma, aborta.
    A digitação é "assíncrona" (uma tecla por vez com sleep) para não travar o event loop e permitir intervenção do ESC imediata.
    """
    
    def __init__(self):
        self.aborted = False
        self.listener = keyboard.Listener(on_press=self._on_physical_press)

    def _on_physical_press(self, key):
        # A detecção de digitação física concorrente é complexa porque o pynput também catch o que o bot digita.
        # Portanto, usamos a tecla ESC como Kill Switch expresso para a digitação.
        if key == keyboard.Key.esc:
            self.aborted = True

    async def start_listener(self):
        if not self.listener.is_alive():
            self.listener.start()

    async def stop_listener(self):
        if self.listener.is_alive():
            self.listener.stop()

    async def type_text(self, text: str, delay_between_chars: float = 0.03):
        """Digita texto de forma natural e interrompível."""
        from src.skills.vision.mouse_engine import UserInterventionException
        
        self.aborted = False
        log.info(f"[Keyboard] Digitando: '{text[:15]}...' | Kill Switch (ESC) ON")
        
        for char in text:
            if self.aborted:
                self.aborted = False
                log.warning("[Keyboard] 🚨 KILL SWITCH: Usuário apertou ESC! Abortando digitação da string.")
                raise UserInterventionException("O usuário assumiu o controle físico interrompendo a digitação.")
                
            # Evita travamento da gui
            pyautogui.write(char)
            # Yield event loop
            await asyncio.sleep(delay_between_chars)

    async def press_hotkey(self, *keys):
        """Executa um atalho de teclado."""
        from src.skills.vision.mouse_engine import UserInterventionException
        
        if self.aborted:
            raise UserInterventionException("Operação abortada preventivamente pelo usuário.")
            
        log.info(f"[Keyboard] Hotkey: {' + '.join(keys)}")
        pyautogui.hotkey(*keys)
        await asyncio.sleep(0.5)  # Dá tempo do SO reagir ao atalho

