function Send-MpvCommand($json) {
    $pipe = New-Object System.IO.Pipes.NamedPipeClientStream(".", "mpv", [System.IO.Pipes.PipeDirection]::Out)
    $pipe.Connect(2000)

    $writer = New-Object System.IO.StreamWriter($pipe)
    $writer.AutoFlush = $true
    $writer.WriteLine($json)

    $writer.Dispose()
    $pipe.Dispose()
}

Send-MpvCommand '{"command": ["set", "video-zoom", 0]}'
Start-Sleep -Milliseconds 50

Send-MpvCommand '{"command": ["set", "video-pan-x", 0]}'
Start-Sleep -Milliseconds 50

Send-MpvCommand '{"command": ["set", "video-pan-y", 0]}'