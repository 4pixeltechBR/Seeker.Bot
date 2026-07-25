import os
import tempfile
import pytest
import shutil
import concurrent.futures
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.skills.instascraper.insta_scraper import InstaScraper

@pytest.fixture
def temp_instascraper():
    with tempfile.TemporaryDirectory() as temp_dir:
        base_path = Path(temp_dir) / "Downloads" / "Instagram"
        inbox_path = Path(temp_dir) / "Inbox"
        
        # Create directories
        base_path.mkdir(parents=True, exist_ok=True)
        inbox_path.mkdir(parents=True, exist_ok=True)
        
        # Patch the load_cookies method to avoid loading real cookies during init
        with patch("src.skills.instascraper.insta_scraper.InstaScraper._load_cookies"):
            scraper = InstaScraper(base_path=str(base_path), inbox_path=str(inbox_path))
            scraper.cookies_dict = {"sessionid": "test_session", "csrftoken": "test_csrf"}
            scraper.csrf_token = "test_csrf"
            yield scraper

def test_extreme_inputs(temp_instascraper):
    """Testa se download_single_post trata adequadamente entradas extremas sem lançar exceções não tratadas."""
    scraper = temp_instascraper
    
    # Lista de inputs adversariais
    adversarial_inputs = [
        "",                     # Vazio
        "   ",                  # Apenas espaços
        "CON",                  # Reservado Windows
        "PRN",                  # Reservado Windows
        "AUX",                  # Reservado Windows
        "NUL",                  # Reservado Windows
        "COM1",                 # Reservado Windows
        "LPT1",                 # Reservado Windows
        "*?|<>:\"",             # Caracteres inválidos em nomes de arquivos no Windows
        "../../traversal",      # Path traversal (Linux style)
        "..\\..\\traversal",    # Path traversal (Windows style)
        "some_folder\\..\\..\\pollution", # Traversal direcionado
        "A" * 5000              # Tamanho massivo
    ]
    
    # Mock das requisições para evitar chamadas de rede e focar na robustez do fluxo
    with patch("src.skills.instascraper.insta_scraper.curl_requests.post") as mock_post, \
         patch("src.skills.instascraper.insta_scraper.curl_requests.get") as mock_get, \
         patch("instaloader.Post.from_shortcode") as mock_instaloader_post:
         
        # Faz com que todas as tentativas de requisição/resolução falhem
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 404
        mock_post.return_value = mock_post_resp
        mock_instaloader_post.side_effect = Exception("Fallback fail")
        
        for adv_input in adversarial_inputs:
            try:
                res = scraper.download_single_post(adv_input)
                # Deve retornar None já que as requisições falham, mas o importante é não levantar exceções não tratadas
                assert res is None
            except Exception as e:
                pytest.fail(f"Falhou com exceção não tratada para o input '{adv_input}': {e}")
                
            # Verifica se não houve poluição de diretório fora de single_posts
            # Nenhuma pasta ou arquivo novo deve ter sido criado na raiz do base_path ou fora dele
            root_contents = list(scraper.base_path.iterdir())
            # Apenas 'single_posts' deve existir dentro do base_path, e ele deve estar vazio
            for item in root_contents:
                if item.name != "single_posts":
                    pytest.fail(f"Poluição detectada! Item criado indevidamente: {item}")
                else:
                    single_posts_contents = list(item.iterdir())
                    assert not single_posts_contents, f"Poluição detectada em single_posts: {single_posts_contents}"

def test_concurrent_downloads_same_reel(temp_instascraper):
    """Verifica se downloads simultâneos do mesmo post não causam conflitos de escrita/renomeação e limpam tudo."""
    scraper = temp_instascraper
    shortcode = "ConcurrentTestReel"
    post_url = f"https://www.instagram.com/reel/{shortcode}/"
    
    # Mock GraphQL query response
    mock_graphql_data = {
        "data": {
            "xdt_shortcode_media": {
                "__typename": "XDTGraphVideo",
                "shortcode": shortcode,
                "is_video": True,
                "video_url": "https://cdn.instagram.com/mock_video.mp4"
            }
        }
    }
    
    # Mock the GraphQL post and video stream get
    with patch("src.skills.instascraper.insta_scraper.curl_requests.post") as mock_post, \
         patch("src.skills.instascraper.insta_scraper.curl_requests.get") as mock_get:
        
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = mock_graphql_data
        mock_post.return_value = mock_post_resp
        
        # Vídeo fake retornando pedaços de bytes
        mock_video_resp = MagicMock()
        mock_video_resp.status_code = 200
        mock_video_resp.iter_content.return_value = [b"video_bytes_chunk"]
        mock_get.return_value = mock_video_resp
        
        # Dispara 10 downloads concorrentes do mesmo reel
        num_threads = 10
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(scraper.download_single_post, post_url) for _ in range(num_threads)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
            
        # Verifica se todos os caminhos retornados são válidos, existem, são arquivos e são distintos
        assert len(results) == num_threads
        assert all(res is not None for res in results)
        assert all(res.exists() for res in results)
        assert all(res.is_file() for res in results)
        
        # Garante que os caminhos são únicos (evitando conflito de sobrescrita)
        assert len(set(results)) == num_threads
        
        # Limpa os arquivos gerados
        for res in results:
            res.unlink()
            
        # Garante que a pasta single_posts ficou limpa
        single_posts_dir = scraper.base_path / "single_posts"
        assert not list(single_posts_dir.iterdir()), "Dangling files found in single_posts after clean up!"

def test_unbound_local_error_finally_leak(temp_instascraper):
    """Testa se exceções lançadas antes da definição de video_path no bot do Telegram causam UnboundLocalError silencioso."""
    # Vamos simular o Telegram Router chamando o handler e testar se ele captura tudo.
    # O handler _handle_download em telegram/commands/instascraper.py usa um bloco try..finally.
    # Se _do_download levantar uma exceção, video_path fica indefinido.
    # O bloco finally tenta acessar video_path, o que gera UnboundLocalError se não estiver inicializado.
    # Queremos verificar que no código original isso é capturado pela exceção genérica interna ou se gera problemas.
    
    # Importa o módulo do telegram
    from src.channels.telegram.commands import instascraper
    
    # Mock do objeto Message do aiogram
    mock_message = MagicMock()
    mock_message.answer = MagicMock()
    # Criamos um mock assíncrono para answer que retorna uma mensagem de status mockada
    from unittest.mock import AsyncMock
    mock_status = MagicMock()
    mock_status.edit_text = AsyncMock()
    mock_status.delete = AsyncMock()
    
    async def async_answer(*args, **kwargs):
        return mock_status
    mock_message.answer.side_effect = async_answer
    
    # Forçamos _do_download a levantar uma exceção
    with patch("src.skills.instascraper.insta_scraper.InstaScraper.download_single_post", side_effect=Exception("Critical download failure")):
         
         # Executamos o handler do download
         # Como _handle_download é assíncrono, rodamos com pytest-asyncio ou asyncio.run
         import asyncio
         try:
             asyncio.run(instascraper._handle_download(mock_message, "https://instagram.com/reel/DZiUVEPPz0K/"))
         except Exception as e:
             pytest.fail(f"O handler _handle_download levantou uma exceção não tratada: {e}")
             
         # Se não levantou exceção externa, verifica se o status foi editado informando a falha
         mock_status.edit_text.assert_called()
         called_text = mock_status.edit_text.call_args[0][0]
         assert "Falha ao baixar" in called_text or "Não foi possível" in called_text

def test_adversarial_validation_bypass_path_traversal(temp_instascraper):
    """
    Demonstrates that a crafted input passing the instagram url check
    results in a filename resolving outside the single_posts directory.
    """
    scraper = temp_instascraper
    malicious_input = "..\\..\\..\\#instagram.com/reel/"
    
    mock_graphql_data = {
        "data": {
            "xdt_shortcode_media": {
                "__typename": "XDTGraphVideo",
                "shortcode": "#instagram.com",
                "is_video": True,
                "video_url": "https://cdn.instagram.com/mock_video.mp4"
            }
        }
    }
    
    with patch("src.skills.instascraper.insta_scraper.curl_requests.post") as mock_post, \
         patch("src.skills.instascraper.insta_scraper.curl_requests.get") as mock_get:
        
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = mock_graphql_data
        mock_post.return_value = mock_post_resp
        
        mock_video_resp = MagicMock()
        mock_video_resp.status_code = 200
        mock_video_resp.iter_content.return_value = [b"payload"]
        mock_get.return_value = mock_video_resp
        
        res_path = scraper.download_single_post(malicious_input)
        
        try:
            # Asserts that the validation blocks path traversal (returns None)
            assert res_path is None, "Vulnerability NOT fixed: malicious input was not blocked."
        finally:
            if res_path and res_path.exists():
                res_path.unlink()
                # Also remove the created 'etc' directory if it exists
                etc_dir = res_path.parent
                if etc_dir.name == "etc" and etc_dir.exists():
                    import shutil
                    shutil.rmtree(etc_dir, ignore_errors=True)
