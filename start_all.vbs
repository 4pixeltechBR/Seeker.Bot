Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' Executa os dois arquivos bat de watchdog de forma assincrona (1 = SW_SHOWNORMAL, False = Nao aguardar termino)
WshShell.Run "cmd.exe /c """ & scriptDir & "\start_watchdog.bat""", 1, False
WshShell.Run "cmd.exe /c """ & scriptDir & "\start_agent_watchdog.bat""", 1, False
