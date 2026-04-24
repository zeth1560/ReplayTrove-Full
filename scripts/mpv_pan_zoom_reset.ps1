#Requires -Version 5.1
<#
.SYNOPSIS
  Reset mpv pan/zoom for scoreboard replay (JSON IPC on \\.\pipe\mpv).

.NOTES
  mpv emits one JSON response line per command. Clients must read each reply or the IPC
  server can block; this script uses one duplex connection and drains replies (unlike
  one-shot Out-only scripts that only send a single command).
#>
$ErrorActionPreference = 'Stop'

function Invoke-MpvCommandBatch {
    param(
        [Parameter(Mandatory)]
        [string[]] $JsonLines
    )

    $pipe = New-Object System.IO.Pipes.NamedPipeClientStream(
        '.',
        'mpv',
        [System.IO.Pipes.PipeDirection]::InOut
    )

    $writer = $null
    $reader = $null
    try {
        $pipe.Connect(5000)
        $enc = [System.Text.UTF8Encoding]::new($false)
        # leaveOpen: do not close the pipe when disposing reader/writer; we dispose $pipe last.
        $writer = [System.IO.StreamWriter]::new($pipe, $enc, 1024, $true)
        $writer.NewLine = "`n"
        $reader = [System.IO.StreamReader]::new($pipe, $enc, $false, 1024, $true)

        foreach ($line in $JsonLines) {
            $writer.WriteLine($line)
            $writer.Flush()
            $null = $reader.ReadLine()
        }
    }
    finally {
        if ($null -ne $writer) {
            try { $writer.Dispose() } catch { }
        }
        if ($null -ne $reader) {
            try { $reader.Dispose() } catch { }
        }
        if ($null -ne $pipe) {
            try { $pipe.Dispose() } catch { }
        }
    }
}

Invoke-MpvCommandBatch @(
    '{"command": ["set", "video-zoom", 0]}',
    '{"command": ["set", "video-pan-x", 0]}',
    '{"command": ["set", "video-pan-y", 0]}'
)
