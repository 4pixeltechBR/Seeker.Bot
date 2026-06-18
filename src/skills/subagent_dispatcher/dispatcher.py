import asyncio
import logging
from src.providers.base import LLMRequest, invoke_with_fallback
from config.models import CognitiveRole

log = logging.getLogger("seeker.subagent_dispatcher")

class SubagentDispatcher:
    """Orquestrador de subagentes assíncronos e paralelos no Seeker.Bot."""

    def __init__(self, pipeline):
        self.pipeline = pipeline

    async def run_subagent(self, goal: str, parent_session_id: str) -> str:
        """Executa um subagente focado em um objetivo específico com Active Loop básico."""
        log.info(f"[subagent] Iniciando subagente para objetivo: '{goal}'")
        
        messages = []
        system_prompt = (
            "Você é um subagente focado executando uma tarefa delegada.\n"
            f"SEU OBJETIVO: {goal}\n\n"
            "Diretrizes:\n"
            "1. Resolva a tarefa de forma direta, clara e concisa.\n"
            "2. Se precisar de dados externos ou arquivos, use as seguintes tags na sua resposta:\n"
            "   - [SEARCH_REQUIRED: termo_da_busca] para buscar na web\n"
            "   - [READ_FILE: caminho_do_arquivo] para ler um arquivo local\n"
            "3. Quando tiver a resposta final, faça um resumo claro, estruturado e conciso sobre o que foi feito e descoberto.\n"
            "4. Não emita mais tags quando concluir a tarefa."
        )
        
        user_prompt = f"Por favor, execute o seguinte objetivo: {goal}"
        messages.append({"role": "user", "content": user_prompt})
        
        max_turns = 3
        turn = 0
        response_text = ""
        
        while turn < max_turns:
            req = LLMRequest(
                messages=messages,
                system=system_prompt,
                temperature=0.15,
                max_tokens=2048,
            )
            
            try:
                # Subagentes usam o tier rápido (CognitiveRole.FAST) por economia e velocidade
                res = await invoke_with_fallback(
                    role=CognitiveRole.FAST,
                    request=req,
                    router=self.pipeline.model_router,
                    api_keys=self.pipeline.api_keys,
                )
            except Exception as e:
                log.error(f"[subagent] Falha ao invocar LLM para subagente: {e}", exc_info=True)
                return f"Erro na execução do subagente: {e}"
                
            response_text = res.text.strip()
            messages.append({"role": "assistant", "content": response_text})
            
            has_tool_call = False
            tool_output = ""
            
            # Active Loop simplificado para subagentes
            if "[SEARCH_REQUIRED:" in response_text:
                start_idx = response_text.find("[SEARCH_REQUIRED:") + len("[SEARCH_REQUIRED:")
                end_idx = response_text.find("]", start_idx)
                if end_idx != -1:
                    query = response_text[start_idx:end_idx].strip().strip('"').strip("'")
                    log.info(f"[subagent] Subagente solicitou busca web: '{query}'")
                    has_tool_call = True
                    try:
                        search_results = await self.pipeline.searcher.search(query, max_results=2)
                        tool_output = f"\n\n[RETORNO DA BUSCA WEB]\n{search_results.to_context(max_results=2)}"
                    except Exception as e:
                        tool_output = f"\n\n[ERRO NA BUSCA WEB]\n{e}"
            
            elif "[READ_FILE:" in response_text:
                start_idx = response_text.find("[READ_FILE:") + len("[READ_FILE:")
                end_idx = response_text.find("]", start_idx)
                if end_idx != -1:
                    path = response_text[start_idx:end_idx].strip().strip('"').strip("'")
                    log.info(f"[subagent] Subagente solicitou leitura de arquivo: '{path}'")
                    has_tool_call = True
                    try:
                        from src.core.execution.registry import execute_read_file
                        content = await execute_read_file(path)
                        tool_output = f"\n\n[CONTEÚDO DO ARQUIVO {path}]\n{content}"
                    except Exception as e:
                        tool_output = f"\n\n[ERRO AO LER ARQUIVO {path}]\n{e}"
            
            if has_tool_call:
                messages.append({
                    "role": "user",
                    "content": f"Resultado da ferramenta:{tool_output}\n\nAnalise o resultado acima e prossiga para concluir ou refinar seu objetivo."
                })
                turn += 1
                continue
            else:
                break
                
        return response_text

    async def dispatch_parallel_goals(self, goals: list[str], session_id: str = "telegram") -> list[str]:
        """Despacha múltiplos objetivos de subagentes concorrentemente e retorna os resumos."""
        if not goals:
            return []
        
        log.info(f"[subagent_dispatcher] Despachando {len(goals)} subagentes em paralelo...")
        tasks = [self.run_subagent(goal, session_id) for goal in goals]
        results = await asyncio.gather(*tasks)
        return list(results)
