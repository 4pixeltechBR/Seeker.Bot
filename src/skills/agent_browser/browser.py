import logging
import asyncio
import os

log = logging.getLogger("seeker.agent_browser")

class AgentBrowser:
    """Skill de automação de browser utilizando Playwright para o Seeker.Bot."""

    def __init__(self, pipeline):
        self.pipeline = pipeline
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._initialized = False

    async def _init_browser(self):
        """Inicialização preguiçosa do Playwright e browser Chromium headless."""
        if self._initialized:
            return

        try:
            from playwright.async_api import async_playwright
            log.info("[browser] Inicializando Playwright assíncrono...")
            self._playwright = await async_playwright().start()
            
            # Inicializa Chromium headless por padrão
            headless = os.getenv("BROWSER_HEADLESS", "true").lower() in ("true", "1", "yes")
            self._browser = await self._playwright.chromium.launch(
                headless=headless,
                args=["--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage"]
            )
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            self._page = await self._context.new_page()
            self._initialized = True
            log.info("[browser] Browser iniciado com sucesso.")
        except ImportError:
            log.error(
                "[browser] Playwright não está instalado. "
                "Execute: pip install playwright && playwright install"
            )
            raise RuntimeError("Playwright não instalado no ambiente do Python.")
        except Exception as e:
            log.error(f"[browser] Erro ao inicializar o browser: {e}", exc_info=True)
            await self.close()
            raise

    async def close(self):
        """Fecha todas as conexões e recursos do browser."""
        log.info("[browser] Fechando recursos do browser...")
        try:
            if self._page:
                await self._page.close()
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            log.debug(f"[browser] Erro durante o fechamento do browser: {e}")
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None
            self._initialized = False

    async def navigate(self, url: str) -> str:
        """Navega para uma URL e retorna a árvore de acessibilidade da página."""
        await self._init_browser()
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url

        log.info(f"[browser] Navegando para: {url}")
        try:
            await self._page.goto(url, wait_until="load", timeout=30000)
            # Dá um tempo extra para JS dinâmico renderizar
            await asyncio.sleep(1)
            return await self.get_accessibility_tree()
        except Exception as e:
            log.error(f"[browser] Erro ao navegar para {url}: {e}")
            return f"Erro de navegação: {e}"

    async def click(self, selector_or_text: str) -> str:
        """Clica em um elemento e retorna a árvore de acessibilidade atualizada."""
        await self._init_browser()
        log.info(f"[browser] Tentando clicar em: '{selector_or_text}'")
        try:
            # Tenta resolver o seletor diretamente. Se falhar, tenta achar por texto de botão ou link
            try:
                # Espera curta para ver se o seletor existe
                await self._page.wait_for_selector(selector_or_text, timeout=3000)
                await self._page.click(selector_or_text)
            except Exception:
                # Fallback: clica buscando por texto visível de botão/link
                clicked = False
                for role in ["button", "link", "checkbox", "radio"]:
                    try:
                        locator = self._page.get_by_role(role, name=selector_or_text, exact=False)
                        if await locator.count() > 0:
                            await locator.first.click()
                            clicked = True
                            break
                    except Exception:
                        pass
                
                if not clicked:
                    # Tenta clicar no primeiro elemento contendo o texto
                    await self._page.click(f"text={selector_or_text}", timeout=5000)

            await asyncio.sleep(1) # Espera transição/renderização
            return await self.get_accessibility_tree()
        except Exception as e:
            log.error(f"[browser] Erro ao clicar em '{selector_or_text}': {e}")
            return f"Erro ao clicar: {e}"

    async def fill(self, selector_or_text: str, value: str) -> str:
        """Preenche um campo de entrada e retorna a árvore de acessibilidade atualizada."""
        await self._init_browser()
        log.info(f"[browser] Preenchendo campo '{selector_or_text}' com '{value}'")
        try:
            try:
                await self._page.wait_for_selector(selector_or_text, timeout=3000)
                await self._page.fill(selector_or_text, value)
            except Exception:
                # Fallback por placeholder ou label
                filled = False
                for search_func in [self._page.get_by_placeholder, self._page.get_by_label]:
                    try:
                        locator = search_func(selector_or_text, exact=False)
                        if await locator.count() > 0:
                            await locator.first.fill(value)
                            filled = True
                            break
                    except Exception:
                        pass
                if not filled:
                    # Tenta preencher usando o seletor por texto
                    await self._page.fill(f"text={selector_or_text}", value, timeout=5000)

            await asyncio.sleep(0.5)
            return await self.get_accessibility_tree()
        except Exception as e:
            log.error(f"[browser] Erro ao preencher campo '{selector_or_text}': {e}")
            return f"Erro ao preencher campo: {e}"

    async def get_accessibility_tree(self) -> str:
        """Extrai elementos interativos do DOM e formata como árvore de acessibilidade em Markdown."""
        await self._init_browser()
        try:
            title = await self._page.title()
            url = self._page.url
            
            # JS script para extrair elementos interativos estruturados de forma leve
            js_script = """
            () => {
                const elements = [];
                const walk = (node) => {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        const style = window.getComputedStyle(node);
                        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
                            return;
                        }
                        
                        const tagName = node.tagName.toLowerCase();
                        const role = node.getAttribute('role');
                        const isInteractive = tagName === 'button' || tagName === 'a' || tagName === 'input' || 
                                              tagName === 'select' || tagName === 'textarea' || role === 'button' ||
                                              role === 'link' || node.onclick || node.hasAttribute('contenteditable');
                        
                        if (isInteractive) {
                            let text = (node.innerText || node.getAttribute('placeholder') || node.getAttribute('aria-label') || '').trim();
                            text = text.replace(/\\s+/g, ' ').substring(0, 80);
                            
                            let identifier = node.id ? '#' + node.id : '';
                            if (!identifier && node.className) {
                                identifier = '.' + Array.from(node.classList).join('.');
                            }
                            
                            const elementInfo = {
                                type: tagName,
                                text: text,
                                role: role || tagName,
                                id: node.id || '',
                                name: node.name || '',
                                href: node.getAttribute('href') || '',
                                value: node.value || '',
                                identifier: tagName + (node.id ? '#' + node.id : (node.name ? `[name="${node.name}"]` : ''))
                            };
                            elements.push(elementInfo);
                        }
                    }
                    for (let i = 0; i < node.childNodes.length; i++) {
                        walk(node.childNodes[i]);
                    }
                };
                walk(document.body);
                return elements;
            }
            """
            elements = await self._page.evaluate(js_script)
            
            # Converte os elementos para uma representação Markdown compacta
            lines = [f"### Página: {title} ({url})", "Elementos Interativos Disponíveis:"]
            
            if not elements:
                lines.append("*(Nenhum elemento interativo detectado nesta página)*")
            else:
                for idx, el in enumerate(elements, 1):
                    type_str = el['type'].upper()
                    text_str = f" \"{el['text']}\"" if el['text'] else ""
                    id_name_str = ""
                    if el['id']:
                        id_name_str += f" id=\"{el['id']}\""
                    if el['name']:
                        id_name_str += f" name=\"{el['name']}\""
                    if el['value']:
                        id_name_str += f" value=\"{el['value']}\""
                    if el['href'] and not el['href'].startswith("javascript:"):
                        id_name_str += f" href=\"{el['href']}\""
                        
                    lines.append(f"@{idx}. [{type_str}]{id_name_str}{text_str} -> Seletor para Ação: `{el['identifier'] or el['text']}`")
            
            # Cópia do texto da página resumido (apenas os primeiros 1500 caracteres de texto puro)
            body_text = await self._page.inner_text("body")
            body_text_cleaned = " ".join(body_text.split())[:1500]
            lines.append("\nConteúdo Textual (Resumido):")
            lines.append(f"{body_text_cleaned}...")
            
            return "\n".join(lines)
            
        except Exception as e:
            log.error(f"[browser] Erro ao extrair árvore de acessibilidade: {e}")
            return f"Erro ao extrair dados da página: {e}"
