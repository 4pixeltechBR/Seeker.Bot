"""
Seeker.Bot — Tool Registry & Execution
src/core/execution/registry.py

Define e executa as ferramentas acionadas via tags pelo LLM no Active Loop.
"""

import os
import re
import asyncio
import logging

log = logging.getLogger("seeker.execution")

# ── INTEGRAÇÃO TIRITH SECURITY + CHECKPOINT MANAGER ──────────────────
checkpoint_active = False
tirith_active = False
_checkpoint_mgr = None
_last_execution_time = 0.0

try:
    from seeker_agent.tools.checkpoint_manager import CheckpointManager
    from seeker_agent.tools.tirith_security import check_command_security

    checkpoint_enabled = os.getenv("CHECKPOINT_ENABLED", "true").lower() in ("true", "1", "yes")
    tirith_enabled = os.getenv("TIRITH_ENABLED", "true").lower() in ("true", "1", "yes")

    if checkpoint_enabled:
        max_snapshots = int(os.getenv("CHECKPOINT_MAX_SNAPSHOTS", "20"))
        max_total_size = int(os.getenv("CHECKPOINT_MAX_SIZE_MB", "500"))
        _checkpoint_mgr = CheckpointManager(
            enabled=True,
            max_snapshots=max_snapshots,
            max_total_size_mb=max_total_size
        )
        checkpoint_active = True
        log.info("Checkpoint Manager integrado com sucesso.")

    if tirith_enabled:
        tirith_active = True
        log.info("Tirith Security integrado com sucesso.")

except Exception as e:
    log.warning(f"Falha ao carregar ferramentas do Seeker Agent (fail-open): {e}")


def _trigger_checkpoint(reason: str = "auto"):
    """Tira um checkpoint do workspace atual antes de qualquer alteração destrutiva."""
    global _last_execution_time
    if not (checkpoint_active and _checkpoint_mgr):
        return

    try:
        now = asyncio.get_event_loop().time()
    except RuntimeError:
        import time
        now = time.time()

    # Heurística de debounce de turno: se passaram mais de 15 segundos,
    # reseta o turno do checkpoint manager para tirar um novo snapshot.
    if now - _last_execution_time > 15.0:
        try:
            _checkpoint_mgr.new_turn()
            log.debug("Novo turno de checkpoint detectado e redefinido.")
        except Exception as te:
            log.warning(f"Erro ao redefinir turno do checkpoint: {te}")

    _last_execution_time = now

    try:
        working_dir = os.getcwd()
        success = _checkpoint_mgr.ensure_checkpoint(working_dir, reason)
        if success:
            log.info(f"Checkpoint criado com sucesso: {reason}")
    except Exception as ce:
        log.warning(f"Erro não fatal ao criar checkpoint do workspace: {ce}")


# ─────────────────────────────────────────────────────────────────────
# DOCUMENTAÇÃO DINÂMICA DAS FERRAMENTAS PARA O LLM
# ─────────────────────────────────────────────────────────────────────

def get_toolsets_prompt(active_toolsets: list[str] | None) -> str:
    if not active_toolsets:
        return ""
        
    parts = [
        "━━━ FERRAMENTAS OPERACIONAIS DISPONÍVEIS ━━━\n"
        "Você pode executar ações no sistema hospedeiro emitindo tags estruturadas em sua resposta.\n"
        "O pipeline capturará a tag, executará a ação e reinjetará o resultado no seu contexto.\n"
    ]
    
    idx = 1
    if "web" in active_toolsets:
        parts.append(
            f"{idx}. BUSCA WEB:\n"
            "   Use quando precisar de informações factuais recentes pós-2025.\n"
            "   Formato: `[SEARCH_REQUIRED: \"sua query de busca aqui\"]`\n"
        )
        idx += 1
        
    if "files" in active_toolsets:
        parts.append(
            f"{idx}. LEITURA DE ARQUIVO:\n"
            "   Lê o conteúdo de um arquivo de texto no disco.\n"
            "   Formato: `[READ_FILE: \"caminho/do/arquivo\"]`\n\n"
            f"{idx+1}. ESCRITA DE ARQUIVO:\n"
            "   Cria ou sobrescreve um arquivo de texto completo.\n"
            "   Formato:\n"
            "   [WRITE_FILE: \"caminho/do/arquivo\"]\n"
            "   conteúdo completo do arquivo aqui\n"
            "   [/WRITE_FILE]\n\n"
            f"{idx+2}. ALTERAÇÃO CIRÚRGICA DE ARQUIVO (PATCH):\n"
            "   Modifica apenas blocos específicos de código sem reescrever o arquivo inteiro.\n"
            "   Formato:\n"
            "   [PATCH_FILE: \"caminho/do/arquivo\"]\n"
            "   [TARGET]\n"
            "   linhas de código antigas e exatas para substituir\n"
            "   [/TARGET]\n"
            "   [REPLACEMENT]\n"
            "   novas linhas de código modificadas\n"
            "   [/REPLACEMENT]\n"
            "   [/PATCH_FILE]\n"
        )
        idx += 3
        
    if "terminal" in active_toolsets:
        parts.append(
            f"{idx}. EXECUÇÃO DE COMANDO TERMINAL:\n"
            "   Executa um comando no shell do sistema operacional hospedeiro (Windows Powershell).\n"
            "   Formato: `[TERMINAL_EXECUTE: \"seu comando aqui\"]`\n"
        )
        idx += 1
        
    try:
        from src.core.execution.adapters.manager import get_ported_tools_prompt
        ported = get_ported_tools_prompt()
        if ported:
            parts.append(ported)
    except Exception as e:
        log.warning(f"Erro ao obter prompt das ferramentas portadas: {e}")

    parts.append(
        "REGRAS DE USO:\n"
        "- Emita apenas UMA tag de ferramenta por vez em sua resposta.\n"
        "- Após emitir a tag, pare a geração imediatamente. O pipeline cuidará de fornecer a resposta da ferramenta no turno seguinte."
    )
    
    return "\n".join(parts)

# ─────────────────────────────────────────────────────────────────────
# EXECUTORES REAIS
# ─────────────────────────────────────────────────────────────────────

async def execute_read_file(path: str) -> str:
    """Lê conteúdo de um arquivo de forma assíncrona."""
    abs_path = os.path.abspath(path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"Arquivo não encontrado: {abs_path}")
    
    if os.path.isdir(abs_path):
        raise IsADirectoryError(f"O caminho é um diretório, não um arquivo: {abs_path}")

    # Evita ler arquivos binários gigantescos
    size = os.path.getsize(abs_path)
    if size > 1024 * 1024 * 5:  # 5MB limit
        raise ValueError("Arquivo excede o limite máximo de leitura de 5MB.")

    def read_sync():
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    return await asyncio.to_thread(read_sync)


async def execute_write_file(path: str, content: str) -> str:
    """Escreve conteúdo em um arquivo de forma assíncrona."""
    abs_path = os.path.abspath(path)
    
    # Criar checkpoint antes de gravar
    _trigger_checkpoint(reason=f"write_file: {os.path.basename(abs_path)}")
    
    # Garante diretórios pais
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)


    def write_sync():
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)

    await asyncio.to_thread(write_sync)
    return f"Arquivo gravado com sucesso: {abs_path} ({len(content)} caracteres)."


async def execute_patch_file(response_text: str, path: str) -> str:
    """Aplica uma substituição (patch) cirúrgica em um arquivo."""
    abs_path = os.path.abspath(path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"Arquivo para patch não existe: {abs_path}")

    # Criar checkpoint antes de aplicar o patch
    _trigger_checkpoint(reason=f"patch_file: {os.path.basename(abs_path)}")


    # Extrai TARGET e REPLACEMENT
    target_match = re.search(r"\[TARGET\](.*?)\[/TARGET\]", response_text, re.DOTALL)
    replacement_match = re.search(r"\[REPLACEMENT\](.*?)\[/REPLACEMENT\]", response_text, re.DOTALL)

    if not target_match or not replacement_match:
        raise ValueError("Estrutura [TARGET] ou [REPLACEMENT] ausente na tag de patch.")

    target_content = target_match.group(1)
    replacement_content = replacement_match.group(1)

    def patch_sync():
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            file_data = f.read()

        if target_content not in file_data:
            # Tenta limpar espaços/linhas em branco extras nas pontas para tolerância a falhas
            stripped_target = target_content.strip()
            if stripped_target in file_data:
                # Substitui a versão stripped
                new_data = file_data.replace(stripped_target, replacement_content.strip(), 1)
            else:
                raise ValueError("O conteúdo [TARGET] especificado não foi encontrado no arquivo de origem.")
        else:
            new_data = file_data.replace(target_content, replacement_content, 1)

        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(new_data)

    await asyncio.to_thread(patch_sync)
    return f"Patch aplicado cirurgicamente no arquivo: {abs_path}"


async def execute_terminal_command(command: str) -> str:
    """Executa comando shell no host de forma assíncrona capturando streams."""
    log.info(f"Executando comando terminal: {command}")
    
    # 1. Executar verificação de segurança do Tirith
    if tirith_active:
        try:
            verdict = check_command_security(command)
            action = verdict.get("action", "allow")
            summary = verdict.get("summary", "")
            if action == "block":
                log.warning(f"Comando bloqueado pelo Tirith Security: '{command}'. Motivo: {summary}")
                return f"[ERRO: O comando foi bloqueado pelas políticas de segurança do Tirith Security. Motivo: {summary or 'Comando de alto risco detectado'}]"
            elif action == "warn":
                log.warning(f"Aviso de segurança emitido pelo Tirith para o comando '{command}': {summary}")
        except Exception as e:
            log.warning(f"Falha ao executar auditoria do Tirith (fail-open): {e}")

    # 2. Criar checkpoint antes de executar comando no terminal
    _trigger_checkpoint(reason=f"terminal_command: {command[:50]}")
    
    # Define limite de tempo de 45 segundos para comandos

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=45.0)
        
        out_decoded = stdout.decode("utf-8", errors="replace").strip()
        err_decoded = stderr.decode("utf-8", errors="replace").strip()
        
        result_parts = []
        if out_decoded:
            result_parts.append(out_decoded)
        if err_decoded:
            result_parts.append(f"STDERR:\n{err_decoded}")
            
        return "\n".join(result_parts) if result_parts else "[Comando concluído com sucesso, saída vazia]"
    except asyncio.TimeoutError:
        return "[ERRO: O comando atingiu o timeout limite de execução de 45 segundos]"
    except Exception as e:
        return f"[ERRO ao executar comando: {e}]"
