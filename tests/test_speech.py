"""Sanitizacao e sintese local. Nenhum teste chama a internet nem carrega o Kokoro."""

from seeker.speech import PART_CHARS, MIN_CHARS, VRAM_NEED_MB, LocalVoice, choose_device, pad_short, sanitize, spoken_parts
from seeker.store import Store


def test_termos_tecnicos_viram_leitura_portuguesa():
    out = sanitize("Use a API do Gemini para chamar /v1/chat/completions em Python.")
    assert "a pê i" in out
    assert "djémini" in out
    assert "páiton" in out
    assert "API" not in out
    assert "Python" not in out


def test_siglas_de_hardware_e_unidades():
    out = sanitize("A CPU usou 350 MB de RAM a 24 kHz com RTF de 0,04.")
    assert "cê p ê u" in out
    assert "rã m" in out
    assert "quilórts" in out
    assert "CPU" not in out
    assert "kHz" not in out


def test_porcentagem_lida_por_extenso():
    assert "95 por cento" in sanitize("O disco D esta com 95% de ocupacao.")
    assert "12,5 por cento" in sanitize("Caiu para 12,5%.")


def test_relogio_lido_por_extenso():
    assert "9 horas e 30 minutos" in sanitize("Agendei as 9:30.")
    assert "8 horas" in sanitize("Reuniao as 08:00.")


def test_milissegundos_expandidos_antes_de_ponto():
    assert "120 milissegundos." in sanitize("Respondeu em 120 ms.")


def test_url_removida_inteira_inclusive_protocolo_em_maiusculas():
    lower = sanitize("Veja https://example.com/doc agora.")
    upper = sanitize("O endpoint HTTPS://api.exemplo.br/v1 caiu.")
    ftp = sanitize("Baixe ftp://servidor/arquivo.zip.")
    for out in (lower, upper, ftp):
        assert "//" not in out
        assert "example.com" not in out
        assert "exemplo.br" not in out
        assert "servidor" not in out
    assert "agora." in lower
    assert "caiu." in upper


def test_markdown_e_simbolos_fora_de_palavras_saem():
    out = sanitize("**Nota** `codigo` #titulo <tag> | barra \\ caminho @mail")
    for junk in ("*", "`", "#", "<", ">", "|", "\\", "@"):
        assert junk not in out


def test_frase_curta_gana_apoio_sem_estourar_o_limite():
    short = pad_short("Entendido!")
    assert len(short) >= MIN_CHARS
    assert short.startswith("Entendido!,")
    assert pad_short("") == ""
    long_text = "x" * 40
    assert pad_short(long_text) == long_text


def test_texto_longo_vira_varios_trechos_sem_corte_de_700():
    sentence = "Esta frase explica o ponto com calma e sem pressa."
    text = " ".join([sentence] * 30)
    parts = spoken_parts(text)
    assert len(parts) > 1
    assert all(len(part) <= PART_CHARS for part in parts)
    assert len(" ".join(parts)) > 700
    assert parts[0].startswith("Esta frase")
    assert parts[-1].endswith("pressa.")


def test_frase_sem_ponto_tambem_e_partida():
    text = " ".join(["palavra"] * 80)
    parts = spoken_parts(text)
    assert len(parts) > 1
    assert all(len(part) <= PART_CHARS for part in parts)
    assert " ".join(parts).split() == ["palavra"] * 80


def test_placa_so_entra_com_folga_de_um_giga():
    assert choose_device("cuda", VRAM_NEED_MB) == "cuda"
    assert choose_device("cuda", VRAM_NEED_MB - 1) == "cpu"
    assert choose_device("cuda", None) == "cpu"
    assert choose_device("cpu", 8000) == "cpu"


def test_depois_do_prazo_a_placa_volta_para_a_ram(tmp_path):
    store = Store(tmp_path / "s.db")
    voice = LocalVoice(store, device="cuda")

    class Model:
        def __init__(self):
            self.place = "cuda"

        def to(self, device):
            self.place = device
            return self

    class Pipeline:
        def __init__(self):
            self.model = Model()

    voice._pipeline = Pipeline()
    voice._loaded_device = "cuda"
    voice.device = "cuda"
    voice.release_gpu()
    assert voice.device == "cpu"
    assert voice._pipeline.model.place == "cpu"


def test_perfil_devolve_motor_local_e_sexo_escolhido(tmp_path):
    store = Store(tmp_path / "s.db")
    voice = LocalVoice(store, device="cpu")
    assert voice.profile()["engine"] == "kokoro"
    assert voice.profile()["voice"] == "pm_santa"
    voice.save_profile("", "", "female")
    assert voice.profile()["voice"] == "pf_dora"
    voice.save_profile("", "", "")
    assert voice.profile()["voice"] == "pm_santa"


def test_pipeline_nao_carrega_na_importacao(tmp_path):
    store = Store(tmp_path / "s.db")
    voice = LocalVoice(store, device="cuda")
    assert voice._pipeline is None