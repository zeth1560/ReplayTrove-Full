param(
    [string]$ObsHost = "127.0.0.1",
    [int]$Port = 4455,
    [string]$Password = "",
    [string]$CorrelationId = ""
)

$logPath = "C:\ReplayTrove\state\obs_save_replay_log.txt"

function Log-Line($msg) {
    $stamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss.fff")
    $cid = if ([string]::IsNullOrWhiteSpace($CorrelationId)) { "-" } else { $CorrelationId }
    Add-Content -Path $logPath -Value "$stamp cid=$cid  $msg"
}

function Get-ObsAuthString {
    param(
        [string]$Password,
        [string]$Salt,
        [string]$Challenge
    )

    $sha = [System.Security.Cryptography.SHA256]::Create()

    $secretBytes = [System.Text.Encoding]::UTF8.GetBytes($Password + $Salt)
    $secretHash = $sha.ComputeHash($secretBytes)
    $secretB64 = [Convert]::ToBase64String($secretHash)

    $authBytes = [System.Text.Encoding]::UTF8.GetBytes($secretB64 + $Challenge)
    $authHash = $sha.ComputeHash($authBytes)
    return [Convert]::ToBase64String($authHash)
}

$ws = $null
$writer = $null

try {
    Log-Line "Starting OBS save replay request"

    $ws = [System.Net.WebSockets.ClientWebSocket]::new()
    $uri = [Uri]("ws://{0}:{1}" -f $ObsHost, $Port)
    $ws.ConnectAsync($uri, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
    Log-Line "Connected to OBS websocket"

    $buffer = New-Object byte[] 65536
    $segment = [ArraySegment[byte]]::new($buffer)

    $result = $ws.ReceiveAsync($segment, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
    $helloJson = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count)
    Log-Line "Hello: $helloJson"
    $hello = $helloJson | ConvertFrom-Json

    $identify = @{
        op = 1
        d  = @{
            rpcVersion = 1
        }
    }

    if ($hello.d.authentication) {
        $identify.d.authentication = Get-ObsAuthString `
            -Password $Password `
            -Salt $hello.d.authentication.salt `
            -Challenge $hello.d.authentication.challenge
        Log-Line "Auth challenge received; auth response generated"
    } else {
        Log-Line "No OBS auth challenge present"
    }

    $identifyJson = $identify | ConvertTo-Json -Compress
    $identifyBytes = [System.Text.Encoding]::UTF8.GetBytes($identifyJson)
    $identifySegment = [ArraySegment[byte]]::new($identifyBytes)

    $ws.SendAsync(
        $identifySegment,
        [System.Net.WebSockets.WebSocketMessageType]::Text,
        $true,
        [Threading.CancellationToken]::None
    ).GetAwaiter().GetResult()
    Log-Line "Identify sent"

    $result = $ws.ReceiveAsync($segment, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
    $identifiedJson = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count)
    Log-Line "Identify response: $identifiedJson"
    $identified = $identifiedJson | ConvertFrom-Json

    if ($identified.op -ne 2) {
        throw "OBS Identify failed: $identifiedJson"
    }

    $request = @{
        op = 6
        d  = @{
            requestType = "SaveReplayBuffer"
            requestId   = "save-replay-buffer"
        }
    } | ConvertTo-Json -Compress

    $requestBytes = [System.Text.Encoding]::UTF8.GetBytes($request)
    $requestSegment = [ArraySegment[byte]]::new($requestBytes)

    $ws.SendAsync(
        $requestSegment,
        [System.Net.WebSockets.WebSocketMessageType]::Text,
        $true,
        [Threading.CancellationToken]::None
    ).GetAwaiter().GetResult()
    Log-Line "SaveReplayBuffer request sent"

    $result = $ws.ReceiveAsync($segment, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
    $responseJson = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count)
    Log-Line "SaveReplayBuffer response: $responseJson"
    $response = $responseJson | ConvertFrom-Json

    if ($response.op -ne 7 -or -not $response.d.requestStatus.result) {
        throw "OBS SaveReplayBuffer failed: $responseJson"
    }

    Log-Line "OBS replay buffer save succeeded"
    exit 0
}
catch {
    Log-Line "ERROR: $($_.Exception.Message)"
    exit 1
}
finally {
    if ($ws) {
        $ws.Dispose()
    }
}