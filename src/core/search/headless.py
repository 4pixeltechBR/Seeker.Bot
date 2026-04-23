"""
Seeker.Bot — Headless Scraper
src/core/search/headless.py

Extrai contatos (WhatsApp, email, site) a partir de perfis do Instagram e páginas
Linktree usando Playwright em modo headless — invisível na tela, rápido e resiliente.

Fluxo:
  1. Visita instagram.com/@handle
  2. Lê meta description (bio) — mais estável que DOM dinâmico
  3. Varre links da página por padrões: wa.me, linktr.ee, mailto
  4. Se encontrar Linktree → navega e extrai todos os botões/links
  5. Fallback: regex sobre bio_raw para email e WhatsApp direto

Proteções:
  - User-Agent real (Chrome 124) para evitar bloqueio
  - wait_for_timeout: aguarda JS render antes de ler DOM
  - try/except global: nunca levanta exceção para o chamador
  - Retorna dict parcial mesmo em caso de falha
"""

import re
import logging
from typing import Optional

log = logging.getLogger("seeker.search.headless")


class HeadlessScraper:
    """Scraper headless via Playwright para extração de contatos."""

    INSTAGRAM_TIMEOUT = 12_000   # ms
    LINKTREE_TIMEOUT  = 10_000   # ms
    JS_RENDER_WAIT    = 2_500    # ms — aguarda hydration do React/Next
    LINKTREE_WAIT     = 2_000    # ms

    # User-Agent real para evitar detecção como bot
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    async def extract_contacts_from_instagram(self, handle: str) -> dict:
        """
        Visita instagram.com/@handle e extrai contatos disponíveis na bio/links.

        Args:
            handle: @handle ou 'handle' (com ou sem @)

        Returns:
            dict com chaves: whatsapp, email, site, linktree_url, bio_raw, _erro (opcional)
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            log.error("[headless] Playwright não instalado. Execute: pip install playwright && playwright install chromium")
            return {"_erro": "playwright_not_installed"}

        handle = handle.lstrip("@").strip()
        if not handle:
            return {"_erro": "handle_vazio"}

        url = f"https://www.instagram.com/{handle}/"
        result: dict = {
            "whatsapp": None,
            "email": None,
            "site": None,
            "linktree_url": None,
            "bio_raw": None,
        }

        log.info(f"[headless] Scraping Instagram: @{handle}")

        try:
            import os
            from src.core.search.web import WebSearcher
            
            tavily_key = os.getenv("TAVILY_API_KEY", "")
            brave_key = os.getenv("BRAVE_API_KEY", "")
            searcher = WebSearcher(tavily_key=tavily_key, brave_key=brave_key)
            
            query = f'site:instagram.com "@{handle}"'
            resp = await searcher.search(query, max_results=3)
            
            bio_raw = ""
            for item in resp.results:
                # O Instagram usa o título como "Name (@handle) • Instagram photos and videos"
                # E o snippet como a bio. Vamos concatenar os snippets relevantes.
                if handle.lower() in item.url.lower():
                    bio_raw += item.snippet + " "
                    
            result["bio_raw"] = bio_raw.strip()
            
            # --- Fallback regex sobre bio_raw (snippet OSINT) ---
            bio = result["bio_raw"]
            
            # Tenta achar linktree na bio_raw do snippet
            linktree_match = re.search(r'(linktr\.ee/[a-zA-Z0-9_\-]+)', bio)
            if linktree_match:
                result["linktree_url"] = f"https://{linktree_match.group(1)}"
            
            if not result["email"] and bio:
                found = re.findall(r"[\w.+\-]+@[\w\-]+\.[a-z]{2,}", bio)
                if found:
                    result["email"] = found[0]

            if not result["whatsapp"] and bio:
                # Padrão: wa.me/5511... ou (11) 9xxxx-xxxx ou +55 11 9xxxx
                found = re.findall(r"(?:wa\.me/|whatsapp\.com/send\?phone=)(\d+)", bio)
                if found:
                    result["whatsapp"] = f"https://wa.me/{found[0]}"
                else:
                    # Número BR direto na bio (ex: 64 9 9999-0000)
                    nums = re.findall(r"\+?55\s*\d{2}\s*9\s*\d{4}[\s\-]?\d{4}", bio)
                    if nums:
                        clean = re.sub(r"\D", "", nums[0])
                        if not clean.startswith("55"):
                            clean = "55" + clean
                        result["whatsapp"] = f"https://wa.me/{clean}"
                        
            # Se encontrou linktree, o extract_contacts_from_url fará o Playwright
            if result["linktree_url"]:
                log.info(f"[headless] @{handle} -> Linktree encontrado ({result['linktree_url']}). Extraindo botões...")
                linktree_data = await self.extract_contacts_from_url(result["linktree_url"])
                for key, val in linktree_data.items():
                    if val and not result.get(key):
                        result[key] = val

        except Exception as e:
            log.error(f"[headless] Falha OSINT para @{handle}: {e}")
            result["_erro"] = f"osint_error: {e}"

        log.info(
            f"[headless] @{handle} → whatsapp={bool(result['whatsapp'])} "
            f"email={bool(result['email'])} linktree={bool(result['linktree_url'])}"
        )
        return result

    async def _scrape_linktree(self, page, url: str) -> dict:
        """
        Navega para URL do Linktree e extrai contatos dos botões.
        Usa a mesma instância de página para evitar overhead de novo browser.
        """
        contacts: dict = {"whatsapp": None, "email": None, "site": None}

        try:
            await page.goto(
                url,
                timeout=self.LINKTREE_TIMEOUT,
                wait_until="domcontentloaded",
            )
            await page.wait_for_timeout(self.LINKTREE_WAIT)
            contacts = await self._extract_links_from_current_page(page)
            log.debug(f"[headless] Linktree {url} -> {contacts}")

        except Exception as e:
            log.warning(f"[headless] Falha no Linktree {url}: {e}")

        return contacts

    async def _extract_links_from_current_page(self, page) -> dict:
        """Varre links da página atual e classifica por tipo de contato."""
        contacts: dict = {"whatsapp": None, "email": None, "site": None}
        try:
            links = await page.query_selector_all("a[href]")
            for link in links:
                href = (await link.get_attribute("href") or "").strip()
                text = ((await link.text_content()) or "").lower().strip()

                if not href:
                    continue

                if "wa.me" in href or "whatsapp" in href:
                    contacts["whatsapp"] = href
                elif href.startswith("mailto:"):
                    contacts["email"] = href.replace("mailto:", "").split("?")[0]
                elif href.startswith("http") and any(
                    k in text for k in ["site", "contato", "email", "fale", "orcamento", "orçamento"]
                ):
                    if not contacts["site"]:
                        contacts["site"] = href
        except Exception as e:
            log.warning(f"[headless] Erro ao extrair links: {e}")
        return contacts

    async def extract_contacts_from_url(self, url: str) -> dict:
        """
        Extrai contatos de qualquer URL (Linktree, site de evento, etc).
        Útil quando o evento já tem URL direta sem precisar do Instagram.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return {"_erro": "playwright_not_installed"}

        result: dict = {"whatsapp": None, "email": None, "site": url, "bio_raw": None}

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                ctx = await browser.new_context(user_agent=self.USER_AGENT, locale="pt-BR")
                page = await ctx.new_page()
                try:
                    await page.goto(url, timeout=self.LINKTREE_TIMEOUT, wait_until="domcontentloaded")
                    await page.wait_for_timeout(self.LINKTREE_WAIT)
                    # Extrai diretamente na página atual (sem re-navegar)
                    contacts = await self._extract_links_from_current_page(page)
                    result.update({k: v for k, v in contacts.items() if v})
                    # Tenta bio via meta
                    og = await page.query_selector('meta[property="og:description"]')
                    result["bio_raw"] = await og.get_attribute("content") if og else ""
                except Exception as e:
                    result["_erro"] = str(e)
                finally:
                    await browser.close()
        except Exception as e:
            result["_erro"] = f"playwright_error: {e}"

        return result

    async def batch_extract(
        self,
        handles: list[str],
        score_threshold: float = 6.0,
        scores: Optional[dict] = None,
    ) -> dict[str, dict]:
        """
        Extrai contatos de múltiplos handles em sequência (Instagram rate-limit safe).

        Args:
            handles: lista de @handles
            score_threshold: só processa handles com score >= threshold
            scores: dict {handle: score} para filtrar por prioridade

        Returns:
            dict {handle: result_dict}
        """
        results: dict[str, dict] = {}
        for handle in handles:
            handle_clean = handle.lstrip("@")
            score = (scores or {}).get(handle_clean, 10.0)
            if score < score_threshold:
                log.debug(f"[headless] Pulando @{handle_clean} (score {score} < {score_threshold})")
                continue
            results[handle_clean] = await self.extract_contacts_from_instagram(handle_clean)
        return results
