import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.skills.x_search.x_search import XSearcher

@pytest.mark.anyio
async def test_x_search_success():
    pipeline_mock = MagicMock()
    pipeline_mock.api_keys = {"xai": "test-key-xai"}
    
    searcher = XSearcher(pipeline_mock)
    
    # Mock da resposta HTTP
    response_mock = MagicMock()
    response_mock.status_code = 200
    response_mock.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "A discussão sobre IA no X indica otimismo com novos modelos de reasoning."
                }
            }
        ],
        "system_fingerprint": "fp_xai_grok"
    }
    
    with patch("requests.post") as mock_post:
        mock_post.return_value = response_mock
        
        res = await searcher.search("IA reasoning")
        
        assert "otimismo" in res
        assert "grok-2-1212" in res
        mock_post.assert_called_once()

@pytest.mark.anyio
async def test_x_search_no_key():
    pipeline_mock = MagicMock()
    pipeline_mock.api_keys = {}
    
    searcher = XSearcher(pipeline_mock)
    
    with patch.dict("os.environ", {}, clear=True):
        res = await searcher.search("IA reasoning")
        assert "não está configurada" in res
