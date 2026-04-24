# Dot-source this file; defines Invoke-ReplayTroveObsSaveReplayBuffer for in-process OBS SaveReplayBuffer.
# Avoids a second powershell.exe cold start (often 2–4s on appliance hardware).

function Invoke-ReplayTroveObsSaveReplayBuffer {
    param(
        [string]$ObsHost = "127.0.0.1",
        [int]$Port = 4455,
        [string]$Password = "",
        [string]$CorrelationId = ""
    )

    function Write-ObsSaveLog([string]$msg) {
        $cid = if ([string]::IsNullOrWhiteSpace($CorrelationId)) { "-" } else { $CorrelationId }
        try {
            Write-ReplayTroveJsonl -Component 'scripts' -ScriptName 'obs_save_replay_core.ps1' -Event 'obs_save_replay' -Level 'INFO' -Message $msg -Data @{
                correlation_id = $cid
                detail         = $msg
            }
        }
        catch {
            # Never fail the WebSocket path due to logging.
        }
    }

    function Get-ObsAuthStringCore {
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

    function Receive-ObsWebSocketText {
        param(
            [Parameter(Mandatory = $true)]
            [System.Net.WebSockets.ClientWebSocket]$Socket,
            [int]$TimeoutMs = 8000
        )
        $buffer = New-Object byte[] 65536
        $segment = [ArraySegment[byte]]::new($buffer)
        $acc = New-Object System.Text.StringBuilder
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        while ($true) {
            $remaining = [Math]::Max(1, $TimeoutMs - [int]$sw.ElapsedMilliseconds)
            $cts = [System.Threading.CancellationTokenSource]::new($remaining)
            try {
                $result = $Socket.ReceiveAsync($segment, $cts.Token).GetAwaiter().GetResult()
            } catch [System.OperationCanceledException] {
                throw "OBS websocket receive timeout after ${TimeoutMs}ms"
            } finally {
                $cts.Dispose()
            }
            if ($result.MessageType -eq [System.Net.WebSockets.WebSocketMessageType]::Close) {
                throw "OBS websocket closed by peer while awaiting response"
            }
            if ($result.Count -gt 0) {
                [void]$acc.Append([System.Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count))
            }
            if ($result.EndOfMessage) {
                return $acc.ToString()
            }
            if ($sw.ElapsedMilliseconds -ge $TimeoutMs) {
                throw "OBS websocket fragmented response timeout after ${TimeoutMs}ms"
            }
        }
    }

    function Send-ObsWebSocketText {
        param(
            [Parameter(Mandatory = $true)]
            [System.Net.WebSockets.ClientWebSocket]$Socket,
            [Parameter(Mandatory = $true)]
            [string]$Payload,
            [int]$TimeoutMs = 8000
        )
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Payload)
        $seg = [ArraySegment[byte]]::new($bytes)
        $cts = [System.Threading.CancellationTokenSource]::new($TimeoutMs)
        try {
            $Socket.SendAsync(
                $seg,
                [System.Net.WebSockets.WebSocketMessageType]::Text,
                $true,
                $cts.Token
            ).GetAwaiter().GetResult()
        } catch [System.OperationCanceledException] {
            throw "OBS websocket send timeout after ${TimeoutMs}ms"
        } finally {
            $cts.Dispose()
        }
    }

    $ws = $null
    try {
        Write-ObsSaveLog "Starting OBS save replay request (in-process)"
        $ws = [System.Net.WebSockets.ClientWebSocket]::new()
        $uri = [Uri]("ws://{0}:{1}" -f $ObsHost, $Port)
        $connectCts = [System.Threading.CancellationTokenSource]::new(5000)
        try {
            $ws.ConnectAsync($uri, $connectCts.Token).GetAwaiter().GetResult()
        } catch [System.OperationCanceledException] {
            throw "OBS websocket connect timeout after 5000ms"
        } finally {
            $connectCts.Dispose()
        }
        Write-ObsSaveLog "Connected to OBS websocket"

        $helloJson = Receive-ObsWebSocketText -Socket $ws -TimeoutMs 8000
        Write-ObsSaveLog "Hello: $helloJson"
        $hello = $helloJson | ConvertFrom-Json

        $identify = @{
            op = 1
            d  = @{
                rpcVersion = 1
            }
        }
        if ($hello.d.authentication) {
            $identify.d.authentication = Get-ObsAuthStringCore `
                -Password $Password `
                -Salt $hello.d.authentication.salt `
                -Challenge $hello.d.authentication.challenge
            Write-ObsSaveLog "Auth challenge received; auth response generated"
        }
        else {
            Write-ObsSaveLog "No OBS auth challenge present"
        }

        $identifyJson = $identify | ConvertTo-Json -Compress
        Send-ObsWebSocketText -Socket $ws -Payload $identifyJson -TimeoutMs 8000
        Write-ObsSaveLog "Identify sent"

        $identifiedJson = Receive-ObsWebSocketText -Socket $ws -TimeoutMs 8000
        Write-ObsSaveLog "Identify response: $identifiedJson"
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
        Send-ObsWebSocketText -Socket $ws -Payload $request -TimeoutMs 8000
        Write-ObsSaveLog "SaveReplayBuffer request sent"

        $responseJson = Receive-ObsWebSocketText -Socket $ws -TimeoutMs 8000
        Write-ObsSaveLog "SaveReplayBuffer response: $responseJson"
        $response = $responseJson | ConvertFrom-Json
        if ($response.op -ne 7 -or -not $response.d.requestStatus.result) {
            throw "OBS SaveReplayBuffer failed: $responseJson"
        }
        Write-ObsSaveLog "OBS replay buffer save succeeded"
    }
    catch {
        Write-ObsSaveLog "ERROR: $($_.Exception.Message)"
        throw
    }
    finally {
        if ($null -ne $ws) {
            $ws.Dispose()
        }
    }
}
