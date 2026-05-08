#Requires -Version 5.1
<#
.SYNOPSIS
  Booking overlay test helper (command-bus based).

.DESCRIPTION
  Sends manual booking overlay commands to the scoreboard command bus and can inject
  a fake booking payload for local dry-run validation.

.EXAMPLES
  .\scripts\test_booking_overlay.ps1 -Mode welcome
  .\scripts\test_booking_overlay.ps1 -Mode goodbye
  .\scripts\test_booking_overlay.ps1 -Mode inject -BookingId "test-123"
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('welcome', 'goodbye', 'inject')]
    [string] $Mode,

    [Parameter(Mandatory = $false)]
    [string] $BookingId = 'fake-booking',

    [Parameter(Mandatory = $false)]
    [string] $StartTime = '',

    [Parameter(Mandatory = $false)]
    [string] $EndTime = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$sendScript = Join-Path $PSScriptRoot 'send_command.ps1'

if (-not (Test-Path -LiteralPath $sendScript)) {
    throw "send_command.ps1 not found at $sendScript"
}

if ($Mode -eq 'welcome' -or $Mode -eq 'goodbye') {
    $argsObj = @{ overlay_type = $Mode }
    & $sendScript -Target 'scoreboard' -Action 'show_booking_overlay' -ArgsJson ($argsObj | ConvertTo-Json -Compress)
    exit $LASTEXITCODE
}

if ([string]::IsNullOrWhiteSpace($StartTime)) {
    $StartTime = [DateTime]::UtcNow.AddMinutes(-5).ToString("yyyy-MM-ddTHH:mm:ssZ")
}
if ([string]::IsNullOrWhiteSpace($EndTime)) {
    $EndTime = [DateTime]::UtcNow.AddMinutes(5).ToString("yyyy-MM-ddTHH:mm:ssZ")
}

$injectArgs = @{
    booking_id = $BookingId
    start_time = $StartTime
    end_time   = $EndTime
}
& $sendScript -Target 'scoreboard' -Action 'inject_fake_booking' -ArgsJson ($injectArgs | ConvertTo-Json -Compress)
exit $LASTEXITCODE
