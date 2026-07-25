import os
import tempfile
import pytest
import http.cookiejar
from pathlib import Path
from unittest.mock import patch, MagicMock
from curl_cffi import requests as curl_requests
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
        with patch("src.skills.instascraper.insta_scraper.InstaScraper._load_cookies") as mock_load:
            scraper = InstaScraper(base_path=str(base_path), inbox_path=str(inbox_path))
            scraper.cookies_dict = {"sessionid": "test_session", "csrftoken": "test_csrf"}
            scraper.csrf_token = "test_csrf"
            yield scraper

# --- 1. Empty Cookie Files ---

def test_empty_cookie_file(temp_instascraper):
    """Verifica comportamento quando o arquivo de cookies está totalmente vazio."""
    scraper = temp_instascraper
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tmp:
        tmp_name = tmp.name
    
    try:
        # Define o arquivo de cookies como o arquivo vazio recém-criado
        scraper.cookie_file = tmp_name
        scraper.cookies_dict = {}
        scraper.loader.context._session.cookies.clear()
        
        # _load_cookies não deve levantar exceção mesmo com arquivo vazio/inválido
        scraper._load_cookies()
        
        # cookies_dict deve permanecer vazio
        assert scraper.cookies_dict == {}
        assert len(scraper.loader.context._session.cookies) == 0
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)

# --- 2. Completely Invalid URLs and Profiles ---

def test_directory_pollution_on_invalid_profiles(temp_instascraper):
    """Verifica se diretórios são criados indevidamente para perfis inválidos."""
    scraper = temp_instascraper
    
    # Caso com "www.instagram.com" (deve falhar na validação e NÃO criar diretório)
    res_www = scraper.raspar_perfil("www.instagram.com")
    assert "Erro" in res_www
    # Verifica se criou o diretório
    www_dir = scraper.base_path / "www.instagram.com"
    assert not www_dir.exists(), "Diretório de 'www.instagram.com' foi criado indevidamente (poluição de diretório)!"

def test_spaces_in_profile_names(temp_instascraper):
    """Verifica se nomes de perfil com espaços são tratados corretamente."""
    scraper = temp_instascraper
    
    res_space = scraper.raspar_perfil("hello world")
    assert "Erro" in res_space
    
    space_dir = scraper.base_path / "hello world"
    assert not space_dir.exists(), "Diretório com espaço 'hello world' foi criado indevidamente!"

def test_invalid_filename_characters_in_profiles(temp_instascraper):
    """Verifica se nomes com caracteres inválidos do Windows são rejeitados e não criam pastas."""
    scraper = temp_instascraper
    
    invalid_profiles = ["user:name", "user*name", "user?name", "user<name", "user>name", "user|name"]
    for ip in invalid_profiles:
        res = scraper.raspar_perfil(ip)
        assert "Erro" in res
        
        # Garante que não criou diretório com esse nome (ou nomes que o Windows pudesse aceitar parcialmente)
        clean_ip = ip.replace(":", "").replace("*", "").replace("?", "").replace("<", "").replace(">", "").replace("|", "")
        if clean_ip:
            assert not (scraper.base_path / clean_ip).exists(), f"Diretório para '{ip}' foi criado!"

def test_download_single_post_invalid_shortcode_path_traversal(temp_instascraper):
    """Verifica se shortcodes com barras/contrabarras causam falhas ou comportamento inesperado."""
    scraper = temp_instascraper
    
    # Shortcode com contrabarra
    shortcode_backslash = "abc\\def"
    
    with patch("src.skills.instascraper.insta_scraper.curl_requests.post") as mock_post:
        # Força falha no GraphQL
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 404
        mock_post.return_value = mock_post_resp
        
        # Não deve levantar exceção não tratada ao tentar abrir o arquivo para download
        # (se tentar usar o shortcode cru com contrabarra no Windows, pode tentar criar na pasta single_posts/abc/def.mp4 e falhar com FileNotFoundError)
        try:
            res = scraper.download_single_post(shortcode_backslash)
            # Deve retornar None já que falhou
            assert res is None
        except FileNotFoundError as fnf:
            pytest.fail(f"Levantou FileNotFoundError devido a caminho inválido com contrabarra: {fnf}")
        except OSError as ose:
            pytest.fail(f"Levantou OSError devido a caminho inválido com contrabarra: {ose}")

# --- 3. Extreme Timeouts or Bad Network Responses ---

def test_graphql_timeout_handling(temp_instascraper):
    """Testa se timeouts no GraphQL caem corretamente no fallback do Instaloader."""
    scraper = temp_instascraper
    shortcode = "TimeoutPost123"
    
    # Mock do GraphQL lançando uma exceção de timeout do curl_cffi
    with patch("src.skills.instascraper.insta_scraper.curl_requests.post", side_effect=curl_requests.errors.RequestsError("Timeout mock")) as mock_post, \
         patch("instaloader.Post.from_shortcode") as mock_instaloader_post:
        
        # Configura o mock do Instaloader para falhar também de forma segura
        mock_instaloader_post.side_effect = Exception("Instaloader network failure")
        
        res = scraper.download_single_post(shortcode)
        assert res is None
        mock_post.assert_called_once()
        mock_instaloader_post.assert_called_once()

def test_graphql_invalid_json_response(temp_instascraper):
    """Testa o comportamento se o GraphQL retornar 200 mas com conteúdo que não seja JSON válido (ex: HTML de bloqueio)."""
    scraper = temp_instascraper
    shortcode = "HTMLBlockPost"
    
    with patch("src.skills.instascraper.insta_scraper.curl_requests.post") as mock_post, \
         patch("instaloader.Post.from_shortcode") as mock_instaloader_post:
        
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # json() levanta ValueError quando o corpo não é JSON válido
        mock_resp.json.side_effect = ValueError("Expecting value: line 1 column 1")
        mock_post.return_value = mock_resp
        
        mock_instaloader_post.side_effect = Exception("Instaloader failure")
        
        # Deve capturar o ValueError e fazer fallback silenciosamente
        res = scraper.download_single_post(shortcode)
        assert res is None
        mock_post.assert_called_once()
        mock_instaloader_post.assert_called_once()

def test_graphql_data_is_none_bug(temp_instascraper):
    """Testa se 'data: null' na resposta do GraphQL quebra a execução com TypeError ou se é tratado."""
    scraper = temp_instascraper
    shortcode = "NullDataPost"
    
    # Resposta GraphQL com 'data' como None
    mock_graphql_data = {
        "data": None
    }
    
    with patch("src.skills.instascraper.insta_scraper.curl_requests.post") as mock_post, \
         patch("instaloader.Post.from_shortcode") as mock_instaloader_post:
        
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_graphql_data
        mock_post.return_value = mock_resp
        
        mock_instaloader_post.side_effect = Exception("Instaloader failure")
        
        # Se houver bug de TypeError ('NoneType' object is not iterable), deve ser capturado no try-except geral de download_single_post
        res = scraper.download_single_post(shortcode)
        assert res is None
        mock_post.assert_called_once()
        mock_instaloader_post.assert_called_once()

def test_video_download_stream_failure_leaves_partial_file(temp_instascraper):
    """Verifica se falhas durante o stream de download do vídeo deixam arquivos corrompidos na pasta."""
    scraper = temp_instascraper
    shortcode = "StreamFailPost"
    
    mock_graphql_data = {
        "data": {
            "xdt_shortcode_media": {
                "shortcode": shortcode,
                "is_video": True,
                "video_url": "https://cdn.instagram.com/stream_fail.mp4"
            }
        }
    }
    
    with patch("src.skills.instascraper.insta_scraper.curl_requests.post") as mock_post, \
         patch("src.skills.instascraper.insta_scraper.curl_requests.get") as mock_get, \
         patch("instaloader.Post.from_shortcode") as mock_instaloader_post:
        
        # GraphQL responde com dados válidos
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = mock_graphql_data
        mock_post.return_value = mock_post_resp
        
        # GET do vídeo falha no meio da iteração do stream
        mock_video_resp = MagicMock()
        mock_video_resp.status_code = 200
        
        def generator_with_exception():
            yield b"part1"
            raise curl_requests.errors.RequestsError("Connection aborted mid-stream")
            
        mock_video_resp.iter_content.return_value = generator_with_exception()
        mock_get.return_value = mock_video_resp
        
        mock_instaloader_post.side_effect = Exception("Instaloader failure")
        
        res = scraper.download_single_post(shortcode)
        assert res is None
        
        # Verifica se o arquivo parcial ficou no disco
        partial_files = list(scraper.base_path.glob(f"**/*{shortcode}*"))
        assert not partial_files, "O arquivo corrompido parcial deveria ter sido removido ao ocorrer erro no stream!"

# --- 4. Large Files ---

def test_large_file_streaming(temp_instascraper):
    """Verifica se downloads de arquivos grandes funcionam via stream sem consumir memória excessiva."""
    scraper = temp_instascraper
    shortcode = "LargeVideoPost"
    
    mock_graphql_data = {
        "data": {
            "xdt_shortcode_media": {
                "shortcode": shortcode,
                "is_video": True,
                "video_url": "https://cdn.instagram.com/large.mp4"
            }
        }
    }
    
    with patch("src.skills.instascraper.insta_scraper.curl_requests.post") as mock_post, \
         patch("src.skills.instascraper.insta_scraper.curl_requests.get") as mock_get:
        
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = mock_graphql_data
        mock_post.return_value = mock_post_resp
        
        # Gera muitos blocos de bytes simulando arquivo grande
        large_chunks = [b"a" * 1024 * 1024 for _ in range(10)] # 10MB total
        
        mock_video_resp = MagicMock()
        mock_video_resp.status_code = 200
        mock_video_resp.iter_content.return_value = large_chunks
        mock_get.return_value = mock_video_resp
        
        res_path = scraper.download_single_post(shortcode)
        
        assert res_path is not None
        assert res_path.exists()
        assert res_path.stat().st_size == 10 * 1024 * 1024
        
        # Limpa o arquivo criado
        os.remove(res_path)
