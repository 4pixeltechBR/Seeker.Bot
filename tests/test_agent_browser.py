import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.skills.agent_browser.browser import AgentBrowser

@pytest.mark.anyio
async def test_agent_browser_navigate():
    pipeline_mock = MagicMock()
    browser_skill = AgentBrowser(pipeline_mock)
    
    # Mock do Playwright e Page
    page_mock = AsyncMock()
    page_mock.url = "https://example.com"
    page_mock.title.return_value = "Example Domain"
    
    # Mock do js_script de extração
    elements_mock = [
        {"type": "button", "text": "Clique Aqui", "id": "btn1", "name": "submit", "value": "", "href": "", "identifier": "button#btn1"},
        {"type": "a", "text": "Mais Informações", "id": "", "name": "", "value": "", "href": "/info", "identifier": "Mais Informações"}
    ]
    page_mock.evaluate.return_value = elements_mock
    page_mock.inner_text.return_value = "Este é o corpo do site exemplo..."
    
    browser_skill._page = page_mock
    browser_skill._initialized = True
    
    # Executa navegação
    res = await browser_skill.navigate("https://example.com")
    
    assert "Example Domain" in res
    assert "Clique Aqui" in res
    assert "Mais Informações" in res
    assert "body" in page_mock.inner_text.call_args[0][0]
    page_mock.goto.assert_called_once_with("https://example.com", wait_until="load", timeout=30000)

@pytest.mark.anyio
async def test_agent_browser_click():
    pipeline_mock = MagicMock()
    browser_skill = AgentBrowser(pipeline_mock)
    
    page_mock = AsyncMock()
    page_mock.title.return_value = "Clicado"
    page_mock.url = "https://example.com/clicked"
    page_mock.evaluate.return_value = []
    page_mock.inner_text.return_value = "Site após clique..."
    
    browser_skill._page = page_mock
    browser_skill._initialized = True
    
    # Executa clique
    res = await browser_skill.click("#btn-submit")
    
    assert "Clicado" in res
    page_mock.wait_for_selector.assert_called_once_with("#btn-submit", timeout=3000)
    page_mock.click.assert_called_once_with("#btn-submit")

@pytest.mark.anyio
async def test_agent_browser_fill():
    pipeline_mock = MagicMock()
    browser_skill = AgentBrowser(pipeline_mock)
    
    page_mock = AsyncMock()
    page_mock.title.return_value = "Preenchido"
    page_mock.url = "https://example.com/filled"
    page_mock.evaluate.return_value = []
    page_mock.inner_text.return_value = "Site após preenchimento..."
    
    browser_skill._page = page_mock
    browser_skill._initialized = True
    
    # Executa preenchimento
    res = await browser_skill.fill("#input-email", "test@example.com")
    
    assert "Preenchido" in res
    page_mock.wait_for_selector.assert_called_once_with("#input-email", timeout=3000)
    page_mock.fill.assert_called_once_with("#input-email", "test@example.com")
