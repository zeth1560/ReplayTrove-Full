#Requires -Version 5.1
<#
.SYNOPSIS
  Drop a JSON command file into the scoreboard or encoder command-bus pending folder.

.DESCRIPTION
  Resolves the command bus root the same way as the scoreboard: unified config
  scoreboard.commandsRoot first, then COMMANDS_ROOT env, then C:\ReplayTrove\commands.
  Uses REPLAYTROVE_SETTINGS_FILE or config\settings.json next to the repo root.

  For replay ingest (OBS + worker), use scripts/save_replay_and_trigger.ps1 — see
  docs/operator-replay-trigger-runbook.md. replay_on/replay_off here are scoreboard-only.
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('scoreboard', 'encoder')]
    [string] $Target,

    [Parameter(Mandatory = $true)]
    [string] $Action,

    [Parameter(Mandatory = $false)]
    [string] $ArgsJson = '{}'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Fail([string] $Message) {
    Write-Error -Message $Message -Category InvalidArgument
    exit 1
}

if ([string]::IsNullOrWhiteSpace($Action)) {
    Write-Fail 'Action must not be empty.'
}

$defaultCommandsRoot = 'C:\ReplayTrove\commands'
$repoRoot = Split-Path -Parent $PSScriptRoot

function Resolve-CommandsRoot {
    param(
        [string] $RepoRoot,
        [string] $DefaultRoot
    )
    $cfgPath = if (-not [string]::IsNullOrWhiteSpace($env:REPLAYTROVE_SETTINGS_FILE)) {
        $env:REPLAYTROVE_SETTINGS_FILE
    } else {
        Join-Path $RepoRoot 'config\settings.json'
    }
    if (Test-Path -LiteralPath $cfgPath) {
        try {
            $j = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
            $cr = $j.scoreboard.commandsRoot
            if ($null -ne $cr -and $cr -is [string] -and -not [string]::IsNullOrWhiteSpace($cr)) {
                return @{ Root = $cr.Trim().Trim('"').Trim("'"); Source = 'unified' }
            }
        } catch {
            # fall through to env/default
        }
    }
    $e = [Environment]::GetEnvironmentVariable('COMMANDS_ROOT')
    if (-not [string]::IsNullOrWhiteSpace($e)) {
        return @{ Root = $e.Trim().Trim('"').Trim("'"); Source = 'env' }
    }
    return @{ Root = $DefaultRoot; Source = 'default' }
}

$resolvedRoot = Resolve-CommandsRoot -RepoRoot $repoRoot -DefaultRoot $defaultCommandsRoot
$commandRoot = $resolvedRoot.Root
$commandRootSource = $resolvedRoot.Source
if (-not [System.IO.Path]::IsPathRooted($commandRoot)) {
    $commandRoot = Join-Path $repoRoot $commandRoot
}
try {
    $commandRoot = [System.IO.Path]::GetFullPath($commandRoot)
} catch {
    Write-Fail ("Invalid command bus root path '{0}': {1}" -f $commandRoot, $_.Exception.Message)
}

$pendingDir = Join-Path -Path $commandRoot -ChildPath $Target | Join-Path -ChildPath 'pending'

try {
    $argsParsed = $ArgsJson | ConvertFrom-Json -ErrorAction Stop
} catch {
    Write-Fail ("ArgsJson is not valid JSON: {0}" -f $_.Exception.Message)
}

if ($null -eq $argsParsed) {
    $argsParsed = [pscustomobject]@{}
} elseif ($argsParsed -is [System.Array]) {
    Write-Fail 'ArgsJson must be a JSON object (e.g. {}), not an array.'
} else {
    $argType = $argsParsed.GetType()
    if ($argType -eq [string] -or $argType -eq [bool] -or $argType.IsPrimitive) {
        Write-Fail 'ArgsJson must be a JSON object (e.g. {}), not a primitive value.'
    }
    if (
        $argType.FullName -ne 'System.Management.Automation.PSCustomObject' -and
        $argType -ne [hashtable]
    ) {
        Write-Fail ("ArgsJson must be a JSON object; got type '{0}'." -f $argType.FullName)
    }
}

$id = [guid]::NewGuid().ToString('n')
$createdUtc = [datetime]::UtcNow
$createdIso = $createdUtc.ToString("yyyy-MM-ddTHH:mm:ss.fff'Z'")

$safeAction = ($Action -replace '[^\w\-]+', '_').Trim('_')
if ([string]::IsNullOrWhiteSpace($safeAction)) {
    $safeAction = 'action'
}

$tsFile = $createdUtc.ToString('yyyyMMddHHmmssfff')
$fileBase = '{0}_{1}' -f $tsFile, $safeAction

$tmpName = "$fileBase.tmp"
$jsonName = "$fileBase.json"

$tmpPath = Join-Path -Path $pendingDir -ChildPath $tmpName
$finalPath = Join-Path -Path $pendingDir -ChildPath $jsonName

$payload = [ordered]@{
    id         = $id
    action     = $Action
    created_at = $createdIso
    source     = 'streamdeck'
    args       = $argsParsed
}

try {
    New-Item -ItemType Directory -Path $pendingDir -Force | Out-Null
} catch {
    Write-Fail ("Could not create pending directory '{0}': {1}" -f $pendingDir, $_.Exception.Message)
}

try {
    $jsonText = $payload | ConvertTo-Json -Depth 20 -Compress
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($tmpPath, $jsonText, $utf8NoBom)
} catch {
    Write-Fail ("Could not write temp file '{0}': {1}" -f $tmpPath, $_.Exception.Message)
}

try {
    Rename-Item -LiteralPath $tmpPath -NewName $jsonName
} catch {
    try {
        if (Test-Path -LiteralPath $tmpPath) {
            Remove-Item -LiteralPath $tmpPath -Force -ErrorAction SilentlyContinue
        }
    } catch { }
    Write-Fail ("Could not rename '{0}' to '{1}': {2}" -f $tmpPath, $jsonName, $_.Exception.Message)
}

Write-Host ("command_sent ok path={0} command_root={1} command_root_source={2}" -f $finalPath, $commandRoot, $commandRootSource)
exit 0