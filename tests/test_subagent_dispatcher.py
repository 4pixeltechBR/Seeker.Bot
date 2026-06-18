import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.skills.subagent_dispatcher.dispatcher import SubagentDispatcher

@pytest.mark.anyio
async def test_run_subagent_simple():
    pipeline_mock = MagicMock()
    pipeline_mock.model_router = MagicMock()
    pipeline_mock.api_keys = {"gemini": "test-key"}
    
    dispatcher = SubagentDispatcher(pipeline_mock)
    
    # Mock do invoke_with_fallback para retornar um resultado mockado sem tags de ferramenta
    res_mock = MagicMock()
    res_mock.text = "A resposta final do subagente foi gerada com sucesso."
    
    with patch("src.skills.subagent_dispatcher.dispatcher.invoke_with_fallback", new_callable=AsyncMock) as mock_invoke:
        mock_invoke.return_value = res_mock
        
        result = await dispatcher.run_subagent("Pesquise sobre X", "parent_sess_1")
        
        assert result == "A resposta final do subagente foi gerada com sucesso."
        mock_invoke.assert_called_once()

@pytest.mark.anyio
async def test_run_subagent_with_search_tool():
    pipeline_mock = MagicMock()
    pipeline_mock.model_router = MagicMock()
    pipeline_mock.api_keys = {"gemini": "test-key"}
    
    searcher_mock = AsyncMock()
    search_res_mock = MagicMock()
    search_res_mock.to_context.return_value = "Resultados da busca web para Y"
    searcher_mock.search.return_value = search_res_mock
    pipeline_mock.searcher = searcher_mock
    
    dispatcher = SubagentDispatcher(pipeline_mock)
    
    # Primeiro turno: subagente pede busca
    res_mock_1 = MagicMock()
    res_mock_1.text = "Eu preciso de mais informações. [SEARCH_REQUIRED: Flamengo]"
    
    # Segundo turno: subagente responde com o final
    res_mock_2 = MagicMock()
    res_mock_2.text = "Flamengo é um clube de futebol do Rio de Janeiro."
    
    with patch("src.skills.subagent_dispatcher.dispatcher.invoke_with_fallback", new_callable=AsyncMock) as mock_invoke:
        mock_invoke.side_effect = [res_mock_1, res_mock_2]
        
        result = await dispatcher.run_subagent("Quem é o Flamengo?", "parent_sess_1")
        
        assert result == "Flamengo é um clube de futebol do Rio de Janeiro."
        assert mock_invoke.call_count == 2
        searcher_mock.search.assert_called_once_with("Flamengo", max_results=2)

@pytest.mark.anyio
async def test_dispatch_parallel_goals():
    pipeline_mock = MagicMock()
    pipeline_mock.model_router = MagicMock()
    pipeline_mock.api_keys = {"gemini": "test-key"}
    
    dispatcher = SubagentDispatcher(pipeline_mock)
    
    res_mock = MagicMock()
    res_mock.text = "Resumo da tarefa delegada."
    
    with patch("src.skills.subagent_dispatcher.dispatcher.invoke_with_fallback", new_callable=AsyncMock) as mock_invoke:
        mock_invoke.return_value = res_mock
        
        goals = ["Pesquisar A", "Pesquisar B"]
        results = await dispatcher.dispatch_parallel_goals(goals, "telegram")
        
        assert len(results) == 2
        assert results[0] == "Resumo da tarefa delegada."
        assert results[1] == "Resumo da tarefa delegada."
        assert mock_invoke.call_count == 2
