' Scoreboard-only: hide replay via command bus (replay_off). Not a full ingest path.
' For the canonical replay-on pipeline, see docs/operator-replay-trigger-runbook.md
' and scripts\save_replay_and_trigger.ps1.

Set shell = CreateObject("WScript.Shell")
cmd = "powershell.exe -ExecutionPolicy Bypass -File ""C:\ReplayTrove\scripts\send_command.ps1"" -Target scoreboard -Action replay_off"
shell.Run cmd, 0, False
