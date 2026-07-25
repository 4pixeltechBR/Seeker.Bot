Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' Executa os dois watchdogs originais em background invisivel (0 = SW_HIDE, False = Nao aguardar)
WshShell.Run "cmd.exe /c """ & scriptDir & "\start_watchdog.bat""", 0, False
WshShell.Run "cmd.exe /c """ & scriptDir & "\start_agent_watchdog.bat""", 0, False
