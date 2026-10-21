import json

from seeker.brain import Brain
from seeker.skills.vault import command, destination, find_existing, parse_result, publish, render_folder, slug, vault_skill, video_id


def test_url_de_video_vira_um_comando_e_uma_pasta(tmp_path):
    engine = tmp_path / "yt2md.py"
    python = tmp_path / "python.exe"
    dest = destination(tmp_path, "https://www.youtube.com/watch?v=abc123XYZ", {"title": "Agentes", "author": "Ana"}, "um")
    argv = command(engine, python, "https://www.youtube.com/watch?v=abc123XYZ", dest, "um")
    assert argv[argv.index("-o") + 1] == str(dest)
    assert argv[-1] == "--single-video"
    assert dest.name == "Agentes - Ana"
    assert video_id("https://youtu.be/abc123XYZ") == "abc123XYZ"


def test_tema_em_lote_pede_tres_videos(tmp_path):
    argv = command(tmp_path / "yt2md.py", tmp_path / "python.exe", "agentes autonomos", tmp_path / "saida", "lote")
    assert "-s" in argv and "3" in argv and "--all" in argv
    assert destination(tmp_path, "agentes autonomos", None, "lote").name.startswith("Pesquisa")


def test_nota_existente_nao_baixa_de_novo(tmp_path):
    folder = tmp_path / "Agentes - Ana"
    folder.mkdir()
    (folder / "video_info.json").write_text(json.dumps({"title": "Agentes", "url": "https://www.youtube.com/watch?v=abc123XYZ", "duration": 125}), encoding="utf-8")
    (folder / "INDEX.md").write_text("# indice", encoding="utf-8")
    (folder / "STRATEGIES.md").write_text("Passo 1. Rode o teste.", encoding="utf-8")
    assert find_existing(tmp_path, "https://www.youtube.com/watch?v=abc123XYZ") == folder
    called = []

    def run(argv, key):
        called.append(argv)
        return "{}"

    engine = tmp_path / "yt2md.py"
    engine.write_text("", encoding="utf-8")
    skill = vault_skill(vault=tmp_path, engine=engine, run=run, probe=lambda query: None)
    text = skill.run({"query": "https://www.youtube.com/watch?v=abc123XYZ"})
    assert called == []
    assert "já estava no cofre" in text
    assert "file:///" in text
    assert "Passo 1" in text
    assert (folder / "FICHA.md").exists()
    assert skill.needs_approval is True


def test_ficha_curta_vai_para_o_cerebro_e_relaciona(tmp_path):
    brain = Brain(tmp_path / "cerebro")
    first = _note(tmp_path / "um", "Agentes", ["agentes", "python"], "A tese é usar um agente local.", "1. Rode o teste.")
    second = _note(tmp_path / "dois", "Voz local", ["agentes"], "Outra tese sobre voz.", "1. Ouça a amostra.")
    publish(first, brain)
    publish(second, brain)
    ficha = (first / "FICHA.md").read_text(encoding="utf-8")
    assert "[[um/INDEX|Índice]]" in ficha or "[[Agentes - Ana/INDEX|Índice]]" in ficha
    assert len(ficha) < 1800
    assert "transcrição enorme transcrição enorme transcrição enorme" not in ficha
    card = (brain.root / "cofre" / "Voz local.md").read_text(encoding="utf-8")
    assert "[[Agentes]]" in card
    assert "file:///" in card
    assert brain.search("agente local")
    publish(first, brain)
    assert ficha.count("tipo: cofre") == 1


def _note(root, title, tags, thesis, step):
    folder = root / f"{title} - Ana"
    folder.mkdir(parents=True)
    (folder / "video_info.json").write_text(
        json.dumps({"title": title, "author": "Ana", "url": "https://www.youtube.com/watch?v=abc", "tags": tags}),
        encoding="utf-8",
    )
    (folder / "INDEX.md").write_text("# indice", encoding="utf-8")
    (folder / "STRATEGIES.md").write_text(f"# SOP\n\n{thesis}\n\n{step}\n", encoding="utf-8")
    (folder / "transcript.md").write_text("transcrição enorme " * 80, encoding="utf-8")
    return folder


def test_json_de_erro_nao_vira_nota():
    try:
        parse_result('{"status": "error", "message": "sem rede"}')
    except ValueError as exc:
        assert "sem rede" in str(exc)
    else:
        raise AssertionError("aceitou erro")
    folder = render_folder
    assert folder
    assert slug('a<>:"b') == "a b"


def test_resultado_novo_lista_os_arquivos(tmp_path):
    folder = tmp_path / "Nota"
    folder.mkdir()
    (folder / "INDEX.md").write_text("indice", encoding="utf-8")
    text = render_folder(folder, reused=False, payload={"title": "Nota", "author": "Ana", "output_dir": str(folder)})
    assert "Nota nova" in text
    assert "Índice" in text or "INDEX" in text
