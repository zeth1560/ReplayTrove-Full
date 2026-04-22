$path = "C:\ReplayTrove\state\replay_lock.txt"

New-Item -ItemType Directory -Force -Path (Split-Path $path) | Out-Null

$epoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
Set-Content -Path $path -Value $epoch