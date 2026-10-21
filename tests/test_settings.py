from pathlib import Path

from seeker.config import Config, ProviderConfig, save_env_keys, save_models, settings_view


def _config(root: Path) -> Config:
    return Config(
        root=root,
        roots=(root,),
        shell_timeout_seconds=30,
        max_tool_steps=8,
        output_cap_chars=8000,
        file_cap_chars=1000,
        providers=(ProviderConfig("Gemini", "gemini", "gemini-2.5-flash", "GEMINI_API_KEY", "https://example"),),
        voice_engine="kokoro",
        voice_device="cuda",
        voice_name="pm_santa",
        voice_language="pt-BR",
        vault=root,
        review_hour=21,
        morning_hour=8,
        morning_minute=30,
    )


def test_ajustes_nao_devolvem_a_chave(tmp_path):
    view = settings_view(_config(tmp_path), {"GEMINI_API_KEY": "segredo"})
    assert view["keys"][0] == {"id": "GEMINI_API_KEY", "label": "Gemini", "set": True}
    assert "segredo" not in str(view)
    assert view["models"][0]["model"] == "gemini-2.5-flash"


def test_grava_chave_nova_e_modelo(tmp_path):
    env = tmp_path / ".env"
    env.write_text("GEMINI_API_KEY=antiga\n", encoding="utf-8")
    assert save_env_keys(env, {"GEMINI_API_KEY": "nova", "OUTRA": "nao"}) == ["GEMINI_API_KEY"]
    assert "nova" in env.read_text(encoding="utf-8")
    assert "OUTRA" not in env.read_text(encoding="utf-8")
    toml = tmp_path / "config.toml"
    toml.write_text('[[providers]]\nname = "Gemini"\nmodel = "velho"\n', encoding="utf-8")
    save_models(toml, {"Gemini": "novo"})
    assert 'model = "novo"' in toml.read_text(encoding="utf-8")
