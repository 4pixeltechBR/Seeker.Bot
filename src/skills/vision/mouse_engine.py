import asyncio
import logging
import time
import pyautogui
from pynput import mouse

log = logging.getLogger("seeker.vision.mouse")

class UserInterventionException(Exception):
    pass

class MouseEngine:
    """
    Desktop Takeover Engine (L3).
    Usa o mouse do Sistema Operacional. Possui o Kill Switch inteligente.
    """
    HUMAN_MOVEMENT_THRESHOLD_PX = 15
    HUMAN_MOVEMENT_WINDOW_MS = 200

    def __init__(self):
        # pytautogui default failsafe (0,0)
        pyautogui.FAILSAFE = True
        
        # Track expected position during autonomous movement
        self.expected_x = None
        self.expected_y = None
        self.aborted = False

        # Hook pynput para escuta de hardware (mesmo quando o bot não está se movendo,
        # ou movendo, se o delta for alto, aborta)
        self.listener = mouse.Listener(on_move=self._on_physical_move)
        
    def _on_physical_move(self, x, y):
        # Se o bot está ativamente movendo o mouse, expected_x/y estarão setados
        if self.expected_x is not None and self.expected_y is not None:
            dx = abs(x - self.expected_x)
            dy = abs(y - self.expected_y)
            # Se a posição real distar mais de 15px da posição prevista pela curva = Fricção Humana
            if dx > self.HUMAN_MOVEMENT_THRESHOLD_PX or dy > self.HUMAN_MOVEMENT_THRESHOLD_PX:
                self.aborted = True
                
    async def start_listener(self):
        if not self.listener.is_alive():
            self.listener.start()
            
    async def stop_listener(self):
        if self.listener.is_alive():
            self.listener.stop()

    async def move_to(self, target_x, target_y, duration=1.0):
        """Arrasta o mouse do SO interpolando steps, com Kill Switch em tempo real."""
        self.aborted = False
        start_x, start_y = pyautogui.position()
        
        # 60 frames por segundo
        steps = int(duration * 60)
        sleep_time = duration / steps if steps > 0 else 0
        
        log.info(f"[Mouse] Movendo para ({target_x}, {target_y})... Kill Switch ON.")
        
        for i in range(steps + 1):
            if self.aborted:
                self._reset_state()
                log.warning("[Mouse] 🚨 FALHA CRÍTICA L3: Humano agarrou o mouse! Abortando traçado.")
                raise UserInterventionException("O usuário assumiu o controle físico do mouse.")
                
            t = i / steps if steps > 0 else 1.0
            # Curva de bezier simples (Ease in/out) para movimento humanizado e daltônico a anti-bots
            easing = t * t * (3 - 2 * t) 
            
            cur_x = start_x + (target_x - start_x) * easing
            cur_y = start_y + (target_y - start_y) * easing
            
            self.expected_x = cur_x
            self.expected_y = cur_y
            
            # Use disable_tweens para mover atomicamente
            pyautogui.moveTo(cur_x, cur_y, _pause=False)
            
            await asyncio.sleep(sleep_time)
            
        self._reset_state()
        
    async def click(self):
        if self.aborted:
            raise UserInterventionException("O usuário assumiu o controle físico.")
        pyautogui.click()
        
    def _reset_state(self):
        self.expected_x = None
        self.expected_y = None
