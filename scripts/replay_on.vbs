' =============================================================================
' DEPRECATED — Legacy compatibility entrypoint only.
' Canonical operator path: PowerShell scripts\save_replay_and_trigger.ps1
'   (OBS SaveReplayBuffer + worker /replay + scoreboard replay_on on success)
' This .vbs forwards to that script and logs to state\deprecated_replay_entrypoints.log
' Do not use for new shortcuts; prefer the .ps1 or worker_notify_instant_replay.ps1 -Http.
' Full guide: docs/operator-replay-trigger-runbook.md
' =============================================================================

Set shell = CreateObject("WScript.Shell")
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""C:\ReplayTrove\scripts\forward_vbs_to_canonical_replay.ps1"" -Source ""replay_on.vbs"""
shell.Run cmd, 0, False
