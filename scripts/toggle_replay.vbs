' =============================================================================
' DEPRECATED — Legacy compatibility entrypoint only (historically misnamed "toggle").
' Canonical operator path: scripts\save_replay_and_trigger.ps1
' This .vbs forwards to the full canonical pipeline (same as replay_on.vbs).
' Logs: state\deprecated_replay_entrypoints.log (non_canonical_path=vbs)
' Full guide: docs/operator-replay-trigger-runbook.md
' =============================================================================

Set shell = CreateObject("WScript.Shell")
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""C:\ReplayTrove\scripts\forward_vbs_to_canonical_replay.ps1"" -Source ""toggle_replay.vbs"""
shell.Run cmd, 0, False
