$pipe = New-Object System.IO.Pipes.NamedPipeClientStream(".", "mpv", [System.IO.Pipes.PipeDirection]::Out)
$pipe.Connect(2000)

$writer = New-Object System.IO.StreamWriter($pipe)
$writer.AutoFlush = $true
$writer.WriteLine('{"command": ["add", "video-pan-y", 0.05]}')

$writer.Dispose()
$pipe.Dispose()