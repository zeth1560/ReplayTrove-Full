param(
    [string[]]$TargetFolders = @("C:\ReplayTrove\previews", "C:\ReplayTrove\processed"),
    [int]$RetentionHours = 24,
    [string]$TmpCleanupRoot = "C:\ReplayTrove",
    [int]$TmpRetentionHours = 1,
    [int]$IntervalMinutes = 15,
    # Deprecated: central logs use logs/cleaner/cleaner-YYYY-MM-DD.jsonl (REPLAYTROVE_LOGS_ROOT).
    [string]$LogPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$rtRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $rtRoot 'scripts\replaytrove_json_log.ps1')

function Write-Log {
    param([string]$Message)
    Write-ReplayTroveJsonl -Component 'cleaner' -Event 'cleaner_bee' -Level 'INFO' -Message $Message -Data @{
        detail = $Message
    }
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

function Remove-ExpiredTmpFiles {
    param(
        [string]$Root,
        [datetime]$Cutoff
    )

    if (-not $Root) {
        return
    }

    if (-not (Test-Path -Path $Root -PathType Container)) {
        Write-Log "Skip: .tmp cleanup root missing -> $Root"
        return
    }

    $deletedCount = 0
    $deletedBytes = 0L

    Get-ChildItem -Path $Root -Filter "*.tmp" -File -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
        $file = $_
        if ($file.LastWriteTime -lt $Cutoff) {
            try {
                $deletedBytes += $file.Length
                Remove-Item -Path $file.FullName -Force -ErrorAction Stop
                $deletedCount++
            }
            catch {
                Write-Log "Failed deleting .tmp: $($file.FullName) | $($_.Exception.Message)"
            }
        }
    }

    if ($deletedCount -gt 0) {
        $deletedMb = [Math]::Round($deletedBytes / 1MB, 2)
        Write-Log "Deleted $deletedCount .tmp file(s) under '$Root' (~$deletedMb MB)."
    }
    else {
        Write-Log "No expired .tmp files under '$Root'."
    }
}

Write-Log "Cleaner Bee started. Retention=${RetentionHours}h, .tmp retention=${TmpRetentionHours}h, interval=${IntervalMinutes}m."

while ($true) {
    try {
        $cutoffTime = (Get-Date).AddHours(-$RetentionHours)
        Remove-ExpiredFiles -Folders $TargetFolders -Cutoff $cutoffTime
        if ($TmpCleanupRoot) {
            $tmpCutoff = (Get-Date).AddHours(-$TmpRetentionHours)
            Remove-ExpiredTmpFiles -Root $TmpCleanupRoot -Cutoff $tmpCutoff
        }
    }
    catch {
        Write-Log "Cycle failed: $($_.Exception.Message)"
    }

    Start-Sleep -Seconds ([Math]::Max(60, $IntervalMinutes * 60))
}
