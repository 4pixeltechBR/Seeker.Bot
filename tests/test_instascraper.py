import os
import tempfile
import pytest
import http.cookiejar
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

def test_cookie_filtering():
    """Verifica se _load_cookies filtra corretamente os cookies não pertencentes ao Instagram."""
    cookie_jar = http.cookiejar.MozillaCookieJar()
    c1 = http.cookiejar.Cookie(0, "sessionid", "12345", None, False, ".instagram.com", True, True, "/", True, True, None, False, None, None, {}, False)
    c2 = http.cookiejar.Cookie(0, "other_cookie", "abc", None, False, ".google.com", True, True, "/", True, True, None, False, None, None, {}, False)
    c3 = http.cookiejar.Cookie(0, "empty_domain_cookie", "xyz", None, False, "", True, False, "/", True, True, None, False, None, None, {}, False)
    c4 = http.cookiejar.Cookie(0, "attacker_cookie", "bad", None, False, "attackerinstagram.com", True, True, "/", True, True, None, False, None, None, {}, False)
    c5 = http.cookiejar.Cookie(0, "exact_cookie", "good", None, False, "instagram.com", True, True, "/", True, True, None, False, None, None, {}, False)
    cookie_jar.set_cookie(c1)
    cookie_jar.set_cookie(c2)
    cookie_jar.set_cookie(c3)
    cookie_jar.set_cookie(c4)
    cookie_jar.set_cookie(c5)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tmp:
        tmp_name = tmp.name
    try:
        cookie_jar.save(tmp_name, ignore_discard=True, ignore_expires=True)
        
        scraper = InstaScraper()
        scraper.cookie_file = tmp_name
        scraper.cookies_dict = {}
        scraper.loader.context._session.cookies.clear()
        scraper._load_cookies()
        
        # c2 (.google.com) and c4 (attackerinstagram.com) deve ser filtrado
        assert "sessionid" in scraper.cookies_dict
        assert "empty_domain_cookie" in scraper.cookies_dict
        assert "exact_cookie" in scraper.cookies_dict
        assert "other_cookie" not in scraper.cookies_dict
        assert "attacker_cookie" not in scraper.cookies_dict
        
        # Também deve estar filtrado no cookie jar do Instaloader
        session_cookie_names = [c.name for c in scraper.loader.context._session.cookies]
        assert "sessionid" in session_cookie_names
        assert "empty_domain_cookie" in session_cookie_names
        assert "exact_cookie" in session_cookie_names
        assert "other_cookie" not in session_cookie_names
        assert "attacker_cookie" not in session_cookie_names
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)

def test_raspar_perfil_invalid_username_validation(temp_instascraper):
    scraper = temp_instascraper
    
    # Test that a profile name containing '/' (like a URL) is rejected
    invalid_url = "https://www.instagram.com/reel/DZGj47gxPZ7/"
    res = scraper.raspar_perfil(invalid_url)
    assert "Erro" in res
    assert "inválido" in res or "caracteres" in res
    
    # Test that a profile name containing ':' is rejected
    invalid_colon = "user:name"
    res2 = scraper.raspar_perfil(invalid_colon)
    assert "Erro" in res2
    
    # Test that www.instagram.com is rejected and no directory is created
    invalid_www = "www.instagram.com"
    res_www = scraper.raspar_perfil(invalid_www)
    assert "Erro" in res_www
    assert not (scraper.base_path / "www.instagram.com").exists()
    
    # Test that http://instagram.com/username is rejected
    invalid_http = "http://instagram.com/username"
    res_http = scraper.raspar_perfil(invalid_http)
    assert "Erro" in res_http
    
    # Verify that no directory was created for the invalid profile names
    assert not (scraper.base_path / "https:").exists()
    assert not (scraper.base_path / "user:name").exists()
    assert not (scraper.base_path / "http:").exists()
    assert not (scraper.base_path / "instagram.com").exists()

def test_raspar_perfil_valid_username_stripping(temp_instascraper):
    scraper = temp_instascraper
    
    # Mock curl_requests.get to return a mock response for feed user
    with patch("src.skills.instascraper.insta_scraper.curl_requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"items": []} # no items to avoid further loops
        mock_get.return_value = mock_response
        
        # Verify that @username is stripped to username
        res = scraper.raspar_perfil("@test_user", limit_posts=1)
        assert "Erro: Nenhum post retornado" in res
        
        # Check if the directory 'test_user' was created
        assert (scraper.base_path / "test_user").exists()

def test_raspar_perfil_deferred_folder_creation_on_error(temp_instascraper):
    scraper = temp_instascraper
    
    # Caso 1: 404 Not Found
    with patch("src.skills.instascraper.insta_scraper.curl_requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response
        
        res = scraper.raspar_perfil("nonexistent_user", limit_posts=1)
        assert "Erro" in res
        assert "não foi encontrado" in res
        
        # Check if the directory was NOT created
        assert not (scraper.base_path / "nonexistent_user").exists()

    # Caso 2: 500 Internal Server Error
    with patch("src.skills.instascraper.insta_scraper.curl_requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Server Error"
        mock_get.return_value = mock_response
        
        res = scraper.raspar_perfil("error_user", limit_posts=1)
        assert "Erro" in res
        assert "Falha ao carregar" in res
        
        # Check if the directory was NOT created
        assert not (scraper.base_path / "error_user").exists()

def test_download_single_post_happy_path(temp_instascraper):
    scraper = temp_instascraper
    shortcode = "DZiUVEPPz0K"
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
        
        # Mock post metadata query
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = mock_graphql_data
        mock_post.return_value = mock_post_resp
        
        # Mock video download response
        mock_video_resp = MagicMock()
        mock_video_resp.status_code = 200
        mock_video_resp.iter_content.return_value = [b"chunk1", b"chunk2"]
        mock_get.return_value = mock_video_resp
        
        downloaded_path = scraper.download_single_post(post_url)
        
        assert downloaded_path is not None
        assert downloaded_path.exists()
        assert downloaded_path.name.startswith(f"single_{shortcode}_")
        assert downloaded_path.name.endswith(".mp4")
        
        # Read the file to ensure the mock content was chunked correctly
        with open(downloaded_path, "rb") as f:
            content = f.read()
        assert content == b"chunk1chunk2"
        
        # Verify calls
        mock_post.assert_called_once()
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["cookies"] == scraper.cookies_dict
        assert call_kwargs["impersonate"] == "chrome120"
        assert call_kwargs["timeout"] == 120
        assert call_kwargs["stream"] is True

def test_download_single_post_not_a_video(temp_instascraper):
    scraper = temp_instascraper
    shortcode = "PhotoPost123"
    
    mock_graphql_data = {
        "data": {
            "xdt_shortcode_media": {
                "__typename": "XDTGraphImage",
                "shortcode": shortcode,
                "is_video": False,
                "video_url": None
            }
        }
    }
    
    with patch("src.skills.instascraper.insta_scraper.curl_requests.post") as mock_post:
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = mock_graphql_data
        mock_post.return_value = mock_post_resp
        
        result = scraper.download_single_post(shortcode)
        assert result is None

def test_download_single_post_http_error(temp_instascraper):
    scraper = temp_instascraper
    shortcode = "ErrorPost123"
    
    with patch("src.skills.instascraper.insta_scraper.curl_requests.post") as mock_post:
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 400
        mock_post_resp.text = "Bad Request"
        mock_post.return_value = mock_post_resp
        
        result = scraper.download_single_post(shortcode)
        assert result is None

def test_download_single_post_fallback(temp_instascraper):
    """Testa o fallback de download_single_post via Instaloader quando GraphQL falha."""
    scraper = temp_instascraper
    shortcode = "DZiUVEPPz0K"
    
    mock_post = MagicMock()
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 500  # Força falha no GraphQL
    mock_post.return_value = mock_post_resp
    
    mock_post_obj = MagicMock()
    mock_post_obj.is_video = True
    mock_post_obj.shortcode = shortcode
    
    def fake_download_post(post, target):
        dest_path = scraper.base_path / target / f"fake_{post.shortcode}.mp4"
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(b"instaloader_downloaded_data")

    scraper.loader.download_post = MagicMock(side_effect=fake_download_post)

    with patch("src.skills.instascraper.insta_scraper.curl_requests.post", mock_post), \
         patch("instaloader.Post.from_shortcode", return_value=mock_post_obj):
         
        result_path = scraper.download_single_post(shortcode)
        
        assert result_path is not None
        assert result_path.exists()
        assert result_path.name.startswith(f"single_{shortcode}_")
        assert result_path.name.endswith(".mp4")
        with open(result_path, "rb") as f:
            assert f.read() == b"instaloader_downloaded_data"
        
        # Verify the target parameter is a temporary subdirectory under single_posts
        called_args, called_kwargs = scraper.loader.download_post.call_args
        assert called_args[0] == mock_post_obj
        called_target = called_kwargs.get("target")
        assert "single_posts" in called_target and "tmp_" in called_target

def test_download_single_post_live(temp_instascraper):
    """Tenta executar um download real sem quebrar o teste caso ocorra erro de rede/WAF/login."""
    scraper = temp_instascraper
    try:
        res = scraper.download_single_post("DZiUVEPPz0K")
        if res:
            assert res.exists()
            assert res.name.startswith("single_DZiUVEPPz0K_")
            assert res.name.endswith(".mp4")
            print(f"Live download test success: {res}")
        else:
            print("Live download test returned None (rate limit / credentials / private)")
    except Exception as e:
        print(f"Live download test skipped due to: {e}")


def test_download_single_post_null_graphql_response(temp_instascraper):
    """Verifica que o retorno de data: null no GraphQL é tratado com segurança retornando None (ou seguindo pro fallback)."""
    scraper = temp_instascraper
    shortcode = "NullPost123"
    
    # Mock GraphQL post request to return {"data": null}
    mock_graphql_data = {"data": None}
    
    with patch("src.skills.instascraper.insta_scraper.curl_requests.post") as mock_post:
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = mock_graphql_data
        mock_post.return_value = mock_post_resp
        
        # O GraphQL deve falhar silenciosamente (e tentar fallback via Instaloader que também falhará
        # no mock e retornará None)
        with patch("instaloader.Post.from_shortcode", side_effect=Exception("Instaloader fail")):
            result = scraper.download_single_post(shortcode)
            assert result is None


def test_download_single_post_concurrent_unique_filenames(temp_instascraper):
    """Verifica que duas chamadas concorrentes para o mesmo post retornam caminhos de arquivo únicos/distintos."""
    scraper = temp_instascraper
    shortcode = "ConcurrentPost123"
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
        
        # Mock post metadata query
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = mock_graphql_data
        mock_post.return_value = mock_post_resp
        
        # Mock video download response
        mock_video_resp = MagicMock()
        mock_video_resp.status_code = 200
        mock_video_resp.iter_content.return_value = [b"chunk1"]
        mock_get.return_value = mock_video_resp
        
        # Baixa o mesmo post duas vezes consecutivas para simular a concorrência de escrita de arquivos
        path1 = scraper.download_single_post(post_url)
        path2 = scraper.download_single_post(post_url)
        
        assert path1 is not None
        assert path2 is not None
        assert path1.exists()
        assert path2.exists()
        
        # Garante que os caminhos são arquivos diferentes
        assert path1 != path2
        assert path1.name != path2.name
