import asyncio
import logging
from playwright.async_api import async_playwright
import random

log = logging.getLogger("seeker.vision.browser")


class StealthBrowser:
    """
    Camadas L1 e L2: Chromium headless blindado para scraping stealth.
    
    v2:
    - Retry com backoff em navegação (prefeituras são lentas)
    - Context manager para cleanup garantido
    - Timeout configurável
    - Cookie/popup dismissal básico
    """

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    ]

    DEFAULT_TIMEOUT_MS = 45000      # 45s — sites de prefeitura são lentos
    DEFAULT_MAX_RETRIES = 2
    THROTTLE_RANGE = (2.0, 5.0)     # Rate limiting entre requests

    def __init__(self, headless: bool = True, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.playwright = None
        self.browser = None
        self.page = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def start(self):
        self.playwright = await async_playwright().start()
        ua = random.choice(self.USER_AGENTS)
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        self.page = await self.browser.new_page(
            user_agent=ua,
            viewport={"width": 1920, "height": 1080},
        )
        # Obfuscação básica do webdriver flag
        await self.page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        log.info(f"[browser] Chromium iniciado (headless={self.headless}, UA={ua[:40]}...)")

    async def close(self):
        for resource, name in [
            (self.page, "page"),
            (self.browser, "browser"),
            (self.playwright, "playwright"),
        ]:
            if resource:
                try:
                    if name == "playwright":
                        await resource.stop()
                    else:
                        await resource.close()
                except Exception as e:
                    log.warning(f"[browser] Erro fechando {name}: {e}")
        self.page = None
        self.browser = None
        self.playwright = None

    async def navigate_and_screenshot(
        self,
        url: str,
        max_retries: int = DEFAULT_MAX_RETRIES,
        full_page: bool = False,
    ) -> bytes:
        """
        Navega para a URL e retorna screenshot em bytes.
        Retry com backoff para sites lentos (prefeituras, portais gov).
        """
        if not self.browser:
            await self.start()

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                # Throttle entre tentativas (rate limiting)
                delay = random.uniform(*self.THROTTLE_RANGE)
                if attempt > 0:
                    delay += attempt * 5  # Backoff adicional em retry
                await asyncio.sleep(delay)

                log.info(
                    f"[browser] Navegando (L1 Stealth, tentativa {attempt + 1}) → {url}"
                )
                await self.page.goto(
                    url,
                    wait_until="networkidle",
                    timeout=self.timeout_ms,
                )

                # Tenta fechar popups/cookie banners comuns
                await self._dismiss_overlays()

                screenshot_bytes = await self.page.screenshot(full_page=full_page)
                return screenshot_bytes

            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    wait = (attempt + 1) * 5
                    log.warning(
                        f"[browser] Falha tentativa {attempt + 1}/{max_retries + 1} "
                        f"em {url}: {e}. Retry em {wait}s..."
                    )
                    await asyncio.sleep(wait)

        log.error(f"[browser] Todas as tentativas falharam para {url}: {last_error}")
        raise last_error

    async def click_coordinate(self, x: int, y: int):
        """Click interno no navegador headless (sem tocar no mouse do SO)."""
        if self.page:
            await self.page.mouse.click(x, y)
            await self.page.wait_for_load_state("networkidle")

    async def extract_html(self) -> str:
        if self.page:
            return await self.page.content()
        return ""

    async def get_current_url(self) -> str:
        if self.page:
            return self.page.url
        return ""

    async def _dismiss_overlays(self):
        """Tenta fechar popups e cookie banners comuns em sites brasileiros."""
        dismiss_selectors = [
            # Cookie consent
            'button:has-text("Aceitar")',
            'button:has-text("Concordo")',
            'button:has-text("OK")',
            'button:has-text("Fechar")',
            '[class*="cookie"] button',
            '[id*="cookie"] button',
            # LGPD banners
            '[class*="lgpd"] button',
            '[id*="lgpd"] button',
        ]
        for selector in dismiss_selectors:
            try:
                el = self.page.locator(selector).first
                if await el.is_visible(timeout=500):
                    await el.click()
                    log.info(f"[browser] Fechou overlay: {selector}")
                    break
            except Exception:
                continue
