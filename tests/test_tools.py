from pathlib import Path

import pytest

from seeker.tools import Files, Shell, ToolError


def test_leitura_fica_na_pasta(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "nota.txt").write_text("olá", encoding="utf-8")
    (root / ".env").write_text("segredo", encoding="utf-8")
    outside = tmp_path / "fora.txt"
    outside.write_text("não", encoding="utf-8")
    files = Files((root,), 1000)
    assert files.read_file("nota.txt") == "olá"
    assert "nota.txt" in files.list_dir("")
    with pytest.raises(ToolError, match="permitidas"):
        files.read_file(str(outside))
    with pytest.raises(ToolError, match="fora"):
        files.read_file(str(root / ".env"))
    with pytest.raises(ToolError, match="permitidas"):
        files.read_file("../fora.txt")


def test_procura_pelo_nome_fora_da_pasta_de_trabalho(tmp_path: Path):
    home = tmp_path / "usuario"
    disco = tmp_path / "disco"
    (home / "docs").mkdir(parents=True)
    (disco / "node_modules").mkdir(parents=True)
    (home / "docs" / "Contrato Ana.txt").write_text("oi", encoding="utf-8")
    (disco / "node_modules" / "Contrato Ana.txt").write_text("nao", encoding="utf-8")
    (home / ".env").write_text("segredo", encoding="utf-8")
    files = Files((home, disco), 1000)
    found = files.find_files("ana")
    assert "Contrato Ana.txt" in found
    assert "node_modules" not in found
    assert ".env" not in found
    assert files.read_file(str(home / "docs" / "Contrato Ana.txt")) == "oi"


def test_powershell_devolve_a_saida(tmp_path: Path):
    shell = Shell(tmp_path, timeout=15, cap=1000)
    try:
        text = shell.run("Write-Output ping")
        assert "ping" in text
        assert "Código de saída: 0" in text
        other = tmp_path / "sala"
        other.mkdir()
        shell.run(f"Set-Location -LiteralPath '{other}'")
        where = shell.run("Write-Output (Get-Location).Path")
        assert "sala" in where.casefold()
        assert shell.session.text().count("PS ") >= 2
    finally:
        shell.stop()
