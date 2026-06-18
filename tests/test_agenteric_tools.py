import os
import pytest
import tempfile
from src.core.execution.registry import (
    get_toolsets_prompt,
    execute_read_file,
    execute_write_file,
    execute_patch_file,
    execute_terminal_command,
)

def test_get_toolsets_prompt():
    # Sem ferramentas ativas
    assert get_toolsets_prompt([]) == ""
    assert get_toolsets_prompt(None) == ""

    # Ferramenta individual
    prompt_web = get_toolsets_prompt(["web"])
    assert "BUSCA WEB" in prompt_web
    assert "READ_FILE" not in prompt_web

    # Múltiplas ferramentas
    prompt_all = get_toolsets_prompt(["web", "files", "terminal"])
    assert "BUSCA WEB" in prompt_all
    assert "LEITURA DE ARQUIVO" in prompt_all
    assert "EXECUÇÃO DE COMANDO TERMINAL" in prompt_all

@pytest.mark.anyio
async def test_filesystem_tools():
    with tempfile.TemporaryDirectory() as temp_dir:
        test_file = os.path.join(temp_dir, "test.txt")
        
        # Teste de Escrita
        write_res = await execute_write_file(test_file, "Linha 1\nLinha 2\nLinha 3")
        assert "Arquivo gravado com sucesso" in write_res
        assert os.path.exists(test_file)

        # Teste de Leitura
        content = await execute_read_file(test_file)
        assert content == "Linha 1\nLinha 2\nLinha 3"

        # Teste de Patch
        patch_response = (
            '[PATCH_FILE: "dummy"]\n'
            "[TARGET]\n"
            "Linha 2\n"
            "[/TARGET]\n"
            "[REPLACEMENT]\n"
            "Linha 2 Modificada\n"
            "[/REPLACEMENT]\n"
            "[/PATCH_FILE]"
        )
        patch_res = await execute_patch_file(patch_response, test_file)
        assert "Patch aplicado" in patch_res

        # Verifica alteração
        new_content = await execute_read_file(test_file)
        assert "Linha 2 Modificada" in new_content
        assert "Linha 1" in new_content
        assert "Linha 3" in new_content

@pytest.mark.anyio
async def test_terminal_command():
    # Comando simples que deve funcionar em Windows Powershell
    res = await execute_terminal_command("echo 'Seeker Rule'")
    assert "Seeker Rule" in res
