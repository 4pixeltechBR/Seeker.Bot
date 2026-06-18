import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch
from src.skills.fuzzy_match.fuzzy_match import FuzzyMatcher
from src.skills.osv_check.osv_check import OSVScanner
from src.skills.microsoft_graph.ms_graph import MSGraphClient

def test_fuzzy_matcher_levenshtein():
    pipeline_mock = MagicMock()
    matcher = FuzzyMatcher(pipeline_mock)
    
    # Casos de teste básicos de distância de Levenshtein
    assert matcher.levenshtein_distance("kitten", "sitting") == 3
    assert matcher.levenshtein_distance("flaw", "lawn") == 2
    assert matcher.levenshtein_distance("", "") == 0
    assert matcher.levenshtein_distance("abc", "") == 3
    assert matcher.levenshtein_distance("", "abc") == 3
    assert matcher.levenshtein_distance("same", "same") == 0

def test_fuzzy_matcher_closest_path():
    pipeline_mock = MagicMock()
    matcher = FuzzyMatcher(pipeline_mock)
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Cria arquivos no diretório temporário
        file1 = os.path.normpath(os.path.join(temp_dir, "config_prod.yaml"))
        file2 = os.path.normpath(os.path.join(temp_dir, "pipeline_core.py"))
        
        with open(file1, "w") as f:
            f.write("prod")
        with open(file2, "w") as f:
            f.write("core")
            
        # 1. Caminho correto (deve retornar igual)
        assert matcher.find_closest_path(file1, temp_dir) == file1
        
        # 2. Caminho digitado incorretamente (ex: config_prud.yaml)
        wrong_path1 = os.path.normpath(os.path.join(temp_dir, "config_prud.yaml"))
        assert matcher.find_closest_path(wrong_path1, temp_dir) == file1
        
        # 3. Caminho com erro maior que a tolerância de 4 caracteres
        wrong_path_too_far = os.path.normpath(os.path.join(temp_dir, "very_different_filename.txt"))
        assert matcher.find_closest_path(wrong_path_too_far, temp_dir) == wrong_path_too_far

@pytest.mark.anyio
async def test_osv_scanner_success():
    pipeline_mock = MagicMock()
    scanner = OSVScanner(pipeline_mock)
    
    # 1. Mock do requirements.txt
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as temp_req:
        temp_req.write("requests==2.31.0\nurllib3==1.26.15\n# comentario\ninvalido\n")
        temp_req_path = temp_req.name
        
    try:
        scanner.requirements_path = temp_req_path
        
        packages = scanner._parse_requirements()
        assert len(packages) == 2
        assert packages[0]["name"] == "requests"
        assert packages[0]["version"] == "2.31.0"
        
        # 2. Mock da API OSV sem vulnerabilidades
        response_mock = MagicMock()
        response_mock.status_code = 200
        response_mock.json.return_value = {} # Sem campo 'vulns'
        
        with patch("requests.post") as mock_post:
            mock_post.return_value = response_mock
            
            res = await scanner.scan_vulnerabilities()
            assert "Nenhuma vulnerabilidade" in res
            assert mock_post.call_count == 2
            
    finally:
        if os.path.exists(temp_req_path):
            os.remove(temp_req_path)

@pytest.mark.anyio
async def test_osv_scanner_with_vulnerabilities():
    pipeline_mock = MagicMock()
    scanner = OSVScanner(pipeline_mock)
    
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as temp_req:
        temp_req.write("insecure-package==1.0.0\n")
        temp_req_path = temp_req.name
        
    try:
        scanner.requirements_path = temp_req_path
        
        # Mock da API OSV com vulnerabilidade
        response_mock = MagicMock()
        response_mock.status_code = 200
        response_mock.json.return_value = {
            "vulns": [
                {
                    "id": "GHSA-xxxx-yyyy",
                    "summary": "Critical vulnerability in insecure-package",
                    "details": "Details about the vulnerability..."
                }
            ]
        }
        
        with patch("requests.post") as mock_post:
            mock_post.return_value = response_mock
            
            res = await scanner.scan_vulnerabilities()
            assert "Vulnerabilidades Encontradas" in res
            assert "GHSA-xxxx-yyyy" in res
            assert "Critical vulnerability" in res
            
    finally:
        if os.path.exists(temp_req_path):
            os.remove(temp_req_path)

@pytest.mark.anyio
async def test_ms_graph_client_send_email_static_token():
    pipeline_mock = MagicMock()
    client = MSGraphClient(pipeline_mock)
    
    response_mock = MagicMock()
    response_mock.status_code = 202 # Accepted
    
    with patch.dict("os.environ", {"MICROSOFT_ACCESS_TOKEN": "mock-access-token"}):
        with patch("requests.post") as mock_post:
            mock_post.return_value = response_mock
            
            res = await client.send_email("test@example.com", "Test Subject", "Test Body")
            assert "sucesso" in res
            mock_post.assert_called_once()
            
            # Valida cabeçalhos e payload enviados
            headers_sent = mock_post.call_args[1]["headers"]
            assert headers_sent["Authorization"] == "Bearer mock-access-token"
            
            json_sent = mock_post.call_args[1]["json"]
            assert json_sent["message"]["subject"] == "Test Subject"
            assert json_sent["message"]["toRecipients"][0]["emailAddress"]["address"] == "test@example.com"

@pytest.mark.anyio
async def test_ms_graph_client_send_email_oauth():
    pipeline_mock = MagicMock()
    client = MSGraphClient(pipeline_mock)
    
    # Configura ambiente para requisição OAuth
    env_mock = {
        "MICROSOFT_CLIENT_ID": "mock-client-id",
        "MICROSOFT_CLIENT_SECRET": "mock-client-secret",
        "MICROSOFT_TENANT_ID": "mock-tenant-id",
        "MICROSOFT_SENDER_EMAIL": "sender@example.com"
    }
    
    token_response = MagicMock()
    token_response.status_code = 200
    token_response.json.return_value = {"access_token": "oauth-generated-token"}
    
    send_response = MagicMock()
    send_response.status_code = 202
    
    with patch.dict("os.environ", env_mock, clear=True):
        with patch("requests.post") as mock_post:
            # Primeira chamada do post é o OAuth Token, a segunda é o Send Email
            mock_post.side_effect = [token_response, send_response]
            
            res = await client.send_email("recipient@example.com", "Oauth Subject", "Oauth Body")
            assert "sucesso" in res
            assert mock_post.call_count == 2
            
            # Verifica se foi para a URL com sender_email
            called_urls = [args[0][0] for args in mock_post.call_args_list]
            assert "https://login.microsoftonline.com/mock-tenant-id/oauth2/v2.0/token" in called_urls[0]
            assert "https://graph.microsoft.com/v1.0/users/sender@example.com/sendMail" in called_urls[1]

@pytest.mark.anyio
async def test_ms_graph_client_send_email_fail():
    pipeline_mock = MagicMock()
    client = MSGraphClient(pipeline_mock)
    
    # Sem chaves de ambiente
    with patch.dict("os.environ", {}, clear=True):
        res = await client.send_email("test@example.com", "Subject", "Body")
        assert "falhou" in res
