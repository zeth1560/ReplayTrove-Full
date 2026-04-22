Set shell = CreateObject("WScript.Shell")
' Compatibility wrapper for legacy direct replay-on triggers.
' This remains non-canonical by design and is now tagged for scoreboard warning logs.
cmd = "powershell.exe -ExecutionPolicy Bypass -File ""C:\ReplayTrove\scripts\send_command.ps1"" -Target scoreboard -Action replay_on -ArgsJson ""{\""trigger_source\"":\""replay_on.vbs\""}"""
shell.Run cmd, 0, False