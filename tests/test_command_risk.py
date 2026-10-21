from seeker.command_risk import decision, is_destructive


def test_consulta_nao_e_destrutiva():
    for command in (
        "Get-ChildItem D:\\",
        "Set-Location E:\\Seeker.Bot",
        "Get-Content nota.txt",
        "git status",
        "git diff",
        "Format-Table",
        "echo oi",
        "python script.py",
        "Get-Process | Select-Object -First 5",
        "echo erro 2>&1",
    ):
        assert is_destructive(command) is False


def test_apagar_e_derrubar_pede_licenca():
    for command in (
        "Remove-Item C:\\temp\\velho -Recurse",
        "del arquivo.txt",
        "rmdir pasta",
        "Clear-Content log.txt",
        "Set-Content nota.txt 'novo'",
        "echo oi > nota.txt",
        "Stop-Process -Name notepad",
        "taskkill /IM notepad.exe",
        "Restart-Computer",
        "shutdown /s /t 0",
        "git reset --hard",
        "git clean -fd",
        "git push --force",
        "reg delete HKCU\\Software\\X /f",
        "Format-Volume -DriveLetter Z",
    ):
        assert is_destructive(command) is True, command


def test_sim_e_nao_no_chat():
    assert decision("Sim.") is True
    assert decision("pode rodar") is True
    assert decision("não") is False
    assert decision("lista a pasta") is None
