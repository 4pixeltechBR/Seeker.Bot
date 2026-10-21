from seeker.skills.gpu import busiest, format_gpu, gpu_skill, parse_samples, parse_summary


def test_separa_a_placa_mais_usada_e_soma_o_mesmo_pid():
    text = "\n".join([
        "pid_10_luid_0x00000000_0x0000aaaa_phys_0=1048576",
        "pid_10_luid_0x00000000_0x0000aaaa_phys_0=1048576",
        "pid_11_luid_0x00000000_0x0000bbbb_phys_0=100",
    ])
    chosen = busiest(parse_samples(text))
    assert chosen[10] == 2097152
    assert 11 not in chosen


def test_relatorio_diz_o_total_e_cada_programa():
    text = format_gpu(
        (9974, 12288, 10),
        {20: 8298201088, 21: 783130624, 22: 1024},
        {20: "python.exe", 21: "pythonw.exe", 22: "dwm.exe"},
    )
    assert "9974 MiB de 12288 MiB" in text
    assert "python: 7914 MiB" in text
    assert "pythonw: 747 MiB" in text
    assert "N/A" in text


def test_skill_de_leitura_usa_o_contador_quando_o_nvidia_nao_separa():
    calls = []

    def run(args):
        calls.append(args[0])
        if args[0] == "nvidia-smi":
            return "100, 200, 4\n"
        return "pid_7_luid_0x00000000_0x0000aaaa_phys_0=209715200\n"

    skill = gpu_skill(run, lambda pid: "chrome.exe")
    assert skill.needs_approval is False
    report = skill.run({})
    assert calls == ["nvidia-smi", "powershell"]
    assert "chrome: 200 MiB" in report
    assert parse_summary("ruim") is None
