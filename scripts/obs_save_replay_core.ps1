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

    $ws = $null
    try {
        Write-ObsSaveLog "Starting OBS save replay request (in-process)"
        $ws = [System.Net.WebSockets.ClientWebSocket]::new()
        $uri = [Uri]("ws://{0}:{1}" -f $ObsHost, $Port)
        $ws.ConnectAsync($uri, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
        Write-ObsSaveLog "Connected to OBS websocket"

        $buffer = New-Object byte[] 65536
        $segment = [ArraySegment[byte]]::new($buffer)
        $result = $ws.ReceiveAsync($segment, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
        $helloJson = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count)
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
        $identifyBytes = [System.Text.Encoding]::UTF8.GetBytes($identifyJson)
        $identifySegment = [ArraySegment[byte]]::new($identifyBytes)
        $ws.SendAsync(
            $identifySegment,
            [System.Net.WebSockets.WebSocketMessageType]::Text,
            $true,
            [Threading.CancellationToken]::None
        ).GetAwaiter().GetResult()
        Write-ObsSaveLog "Identify sent"

        $result = $ws.ReceiveAsync($segment, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
        $identifiedJson = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count)
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
        $requestBytes = [System.Text.Encoding]::UTF8.GetBytes($request)
        $requestSegment = [ArraySegment[byte]]::new($requestBytes)
        $ws.SendAsync(
            $requestSegment,
            [System.Net.WebSockets.WebSocketMessageType]::Text,
            $true,
            [Threading.CancellationToken]::None
        ).GetAwaiter().GetResult()
        Write-ObsSaveLog "SaveReplayBuffer request sent"

        $result = $ws.ReceiveAsync($segment, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
        $responseJson = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count)
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
