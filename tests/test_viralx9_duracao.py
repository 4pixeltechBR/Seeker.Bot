"""Testes do ViralX9 bridge: teto de 45s do roteiro via --duracao + env var."""
import os
from unittest.mock import MagicMock, patch

import pytest


def _mk_cand():
    return {
        "nicho": "microbiologia_ia",
        "tema": "IA diagnostica cancer",
        "justificativa": "🔥 3.0x",
        "tema_original": "AI cancer",
        "idioma_original": "en",
        "video_url": "https://youtube.com/watch?v=xyz",
        "canal": "@Test",
        "regiao": "us",
        "outlier": 3.0,
        "velocity": 100.0,
    }


def test_default_duration_is_45():
    """Sem env var VIRALX9_DURACAO, o default DEVE ser 45s."""

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("VIRALX9_DURACAO", None)
        assert _roteiro_duracao_s() == 45


def test_env_var_overrides_default():
    """VIRALX9_DURACAO=30 retorna 30."""

    with patch.dict(os.environ, {"VIRALX9_DURACAO": "30"}):
        assert _roteiro_duracao_s() == 30


def test_env_var_invalid_falls_back_to_default():
    """Env var não-numérica cai no default 45 (não levanta)."""

    with patch.dict(os.environ, {"VIRALX9_DURACAO": "abc"}):
        assert _roteiro_duracao_s() == 45


def test_env_var_clamped_to_max_60():
    """Teto hard cap: nunca passa de 60s mesmo se env errar."""

    with patch.dict(os.environ, {"VIRALX9_DURACAO": "180"}):
        assert _roteiro_duracao_s() == 60


def test_env_var_clamped_to_min_15():
    """Piso hard cap: nunca abaixo de 15s (roteiro viral minimo)."""

    with patch.dict(os.environ, {"VIRALX9_DURACAO": "5"}):
        assert _roteiro_duracao_s() == 15


def test_create_project_passes_duracao_arg_in_subprocess():
    """create_project injeta --duracao 45 no subprocess do ViralClip."""

    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.stdout = '{"success": true, "projectId": "x", "projectDir": "y", "nicho": "z", "titulo": "t", "duracao": 45, "numCenas": 3}'
    fake_proc.stderr = ""

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("VIRALX9_DURACAO", None)
        with patch("subprocess.run", return_value=fake_proc) as mock_run:
            result = bridge.create_project(_mk_cand())

    assert result["success"] is True
    # Args usados na chamada do subprocess:
    args = mock_run.call_args.args[0]
    assert "--duracao" in args
    assert "45" in args
    # Verifica que --duracao vem ANTES de --source (ordem estável)
    assert args.index("--duracao") < args.index("--source")
    # Verifica que --duracao vale exatamente 45
    idx = args.index("--duracao")
    assert args[idx + 1] == "45"


def test_create_project_includes_roteiro_duracao_in_seeker_meta():
    """O seeker_meta carrega roteiro_duracao_s=45 para o front do ViralClip."""
    import json

    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.stdout = '{"success": true, "projectId": "x", "projectDir": "y"}'
    fake_proc.stderr = ""

    with patch.dict(os.environ, {"VIRALX9_DURACAO": "40"}):
        with patch("subprocess.run", return_value=fake_proc) as mock_run:
            bridge.create_project(_mk_cand())

    # Extracao do --seeker-meta
    args = mock_run.call_args.args[0]
    idx = args.index("--seeker-meta")
    meta_str = args[idx + 1]
    meta = json.loads(meta_str)
    assert meta["roteiro_duracao_s"] == 40
