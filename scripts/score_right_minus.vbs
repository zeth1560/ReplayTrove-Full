Set shell = CreateObject("WScript.Shell")
cmd = "powershell.exe -ExecutionPolicy Bypass -File ""C:\ReplayTrove\scripts\send_command.ps1"" -Target scoreboard -Action score_right_minus"
shell.Run cmd, 0, False
