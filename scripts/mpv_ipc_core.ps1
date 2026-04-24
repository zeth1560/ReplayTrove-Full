# Shared mpv JSON IPC (Windows named pipe \\.\pipe\mpv).
# Each command must be followed by reading one response line or mpv can stall.
#
# mpv does not expand ${property} in show-text when the command is sent over JSON IPC;
# use get_property and format the OSD string in PowerShell.

function Invoke-MpvIpcPipeline {
    param(
        [Parameter(Mandatory)]
        [scriptblock] $ScriptBlock,
        [int] $ConnectTimeoutMs = 8000,
        [int] $ReadTimeoutMs = 3000
    )

    $pipe = New-Object System.IO.Pipes.NamedPipeClientStream(
        '.',
        'mpv',
        [System.IO.Pipes.PipeDirection]::InOut
    )

    $writer = $null
    $reader = $null
    try {
        $pipe.Connect($ConnectTimeoutMs)
        $pipe.ReadMode = [System.IO.Pipes.PipeTransmissionMode]::Byte
        $pipe.ReadTimeout = $ReadTimeoutMs
        $pipe.WriteTimeout = $ReadTimeoutMs
        $enc = [System.Text.UTF8Encoding]::new($false)
        $writer = [System.IO.StreamWriter]::new($pipe, $enc, 1024, $true)
        $writer.NewLine = "`n"
        $reader = [System.IO.StreamReader]::new($pipe, $enc, $false, 1024, $true)

        $send = {
            param($command)
            $json = if ($command -is [string]) {
                $command
            } else {
                $command | ConvertTo-Json -Compress -Depth 8
            }
            $writer.WriteLine($json)
            $writer.Flush()
            try {
                $line = $reader.ReadLine()
            } catch [System.IO.IOException] {
                throw "mpv IPC read timeout after ${ReadTimeoutMs}ms (request: $json)"
            }
            if ([string]::IsNullOrEmpty($line)) {
                throw "mpv IPC: empty response for request: $json"
            }
            $resp = $line | ConvertFrom-Json
            $err = $resp.error
            if ($null -ne $err -and [string]$err -ne 'success') {
                throw "mpv IPC error: $err (request: $json)"
            }
            return $resp
        }

        & $ScriptBlock $send
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

function Invoke-MpvIpcCommandBatch {
    param(
        [Parameter(Mandatory)]
        [string[]] $JsonLines,
        [int] $ConnectTimeoutMs = 8000,
        [int] $ReadTimeoutMs = 3000
    )

    $lines = $JsonLines
    Invoke-MpvIpcPipeline -ConnectTimeoutMs $ConnectTimeoutMs -ReadTimeoutMs $ReadTimeoutMs -ScriptBlock {
        param($send)
        foreach ($line in $lines) {
            & $send $line
        }
    }
}
