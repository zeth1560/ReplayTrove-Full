' Compatibility wrapper: toggle-based replay control is deprecated for operators.
' Keep this entrypoint for external tools, but route deterministically to replay_on.
Set shell = CreateObject("WScript.Shell")
cmd = "powershell.exe -ExecutionPolicy Bypass -File ""C:\ReplayTrove\scripts\send_command.ps1"" -Target scoreboard -Action replay_on -ArgsJson ""{\""trigger_source\"":\""toggle_replay.vbs\""}"""
shell.Run cmd, 0, False
