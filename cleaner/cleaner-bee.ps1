param(
    [string[]]$TargetFolders = @("C:\ReplayTrove\previews", "C:\ReplayTrove\processed"),
    [int]$RetentionHours = 24,
    [int]$IntervalMinutes = 15,
    [string]$LogPath = "C:\ReplayTrove\cleaner\cleaner-bee.log"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogPath -Value "[$timestamp] $Message"
}

function Remove-ExpiredFiles {
    param(
        [string[]]$Folders,
        [datetime]$Cutoff
    )

    foreach ($folder in $Folders) {
        if (-not (Test-Path -Path $folder -PathType Container)) {
            Write-Log "Skip: folder missing -> $folder"
            continue
        }

        $deletedCount = 0
        $deletedBytes = 0L

        Get-ChildItem -Path $folder -File -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
            $file = $_
            if ($file.LastWriteTime -lt $Cutoff) {
                try {
                    $deletedBytes += $file.Length
                    Remove-Item -Path $file.FullName -Force -ErrorAction Stop
                    $deletedCount++
                }
                catch {
                    Write-Log "Failed deleting: $($file.FullName) | $($_.Exception.Message)"
                }
            }
        }

        if ($deletedCount -gt 0) {
            $deletedMb = [Math]::Round($deletedBytes / 1MB, 2)
            Write-Log "Deleted $deletedCount file(s) from '$folder' (~$deletedMb MB)."
        }
        else {
            Write-Log "No expired files in '$folder'."
        }
    }
}

$logDir = Split-Path -Path $LogPath -Parent
if ($logDir -and -not (Test-Path -Path $logDir -PathType Container)) {
    New-Item -Path $logDir -ItemType Directory -Force | Out-Null
}

Write-Log "Cleaner Bee started. Retention=${RetentionHours}h, interval=${IntervalMinutes}m."

while ($true) {
    try {
        $cutoffTime = (Get-Date).AddHours(-$RetentionHours)
        Remove-ExpiredFiles -Folders $TargetFolders -Cutoff $cutoffTime
    }
    catch {
        Write-Log "Cycle failed: $($_.Exception.Message)"
    }

    Start-Sleep -Seconds ([Math]::Max(60, $IntervalMinutes * 60))
}
