Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' Executa apenas o watchdog do Seeker Agent de forma assincrona (1 = SW_SHOWNORMAL, False = Nao aguardar termino)
WshShell.Run "cmd.exe /c """ & scriptDir & "\start_agent_watchdog.bat""", 1, False
