param([switch]$ValidateOnly, [switch]$Background)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$state = Join-Path $root '.local-solobino'
$workspace = Join-Path $state 'workspace'
$null = New-Item -ItemType Directory -Path $workspace -Force
$env:OPENCLAW_STATE_DIR = $state
$env:OPENCLAW_CONFIG_PATH = Join-Path $state 'openclaw.json'
$env:OLLAMA_HOST = '127.0.0.1:11434'

if (-not (Test-Path $env:OPENCLAW_CONFIG_PATH)) {
    $tokenBytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($tokenBytes) } finally { $rng.Dispose() }
    $gatewayToken = -join ($tokenBytes | ForEach-Object { $_.ToString('x2') })
    $config = @{
        gateway = @{
            mode = 'local'; bind = 'loopback'; port = 18790
            auth = @{ mode = 'token'; token = $gatewayToken }
            controlUi = @{ allowedOrigins = @('http://127.0.0.1:18790', 'http://localhost:18790', 'https://walter-pc.tail8db8b3.ts.net:8443') }
            http = @{ endpoints = @{ chatCompletions = @{ enabled = $true } } }
        }
        agents = @{ defaults = @{
            workspace = $workspace
            model = @{ primary = 'ollama/qwen3.5:4b' }
            thinkingDefault = 'off'
            heartbeat = @{ every = '0m' }
            experimental = @{ localModelLean = $true }
            bootstrapMaxChars = 2000
            bootstrapTotalMaxChars = 6000
            maxConcurrent = 1
        } }
        models = @{ providers = @{ ollama = @{
            baseUrl = 'http://127.0.0.1:11434'; api = 'ollama'; apiKey = 'ollama-local'
            models = @(@{
                id = 'qwen3.5:4b'; name = 'Qwen3.5 4B local'; input = @('text')
                contextWindow = 8192; maxTokens = 512; reasoning = $false
                cost = @{ input = 0; output = 0; cacheRead = 0; cacheWrite = 0 }
                params = @{ num_ctx = 8192; num_predict = 512; thinking = $false; keep_alive = '15m' }
            })
        } } }
        tools = @{ allow = @('read'); fs = @{ workspaceOnly = $true } }
        plugins = @{ allow = @('ollama'); entries = @{ ollama = @{ enabled = $true } } }
    }
    $config | ConvertTo-Json -Depth 15 | Set-Content $env:OPENCLAW_CONFIG_PATH -Encoding UTF8
    'Solobino: responde en español y de forma breve. Nunca inventes resultados de herramientas.' |
        Set-Content (Join-Path $workspace 'AGENTS.md') -Encoding UTF8
    'La clave de prueba del proyecto es SOLOBINO-462.' |
        Set-Content (Join-Path $workspace 'prueba.txt') -Encoding UTF8
}

# This isolated profile deliberately exposes only the workspace read tool.
# Add selected MCP/tools after verifying the model and their permissions.
openclaw config validate
if ($LASTEXITCODE -ne 0) { throw 'OpenClaw rechazo la configuracion local.' }
if ($ValidateOnly) { return }
if ($Background) {
    $logDir = Join-Path $root 'local-model-results'
    $null = New-Item -ItemType Directory -Path $logDir -Force
    $shellExe = (Get-Process -Id $PID).Path
    $child = Start-Process -FilePath $shellExe -WindowStyle Hidden -PassThru `
        -ArgumentList @('-NoProfile', '-File', ('"' + $PSCommandPath + '"')) `
        -RedirectStandardOutput (Join-Path $logDir 'gateway.stdout.log') `
        -RedirectStandardError (Join-Path $logDir 'gateway.stderr.log')
    Write-Host "Gateway iniciandose en segundo plano. PID del lanzador: $($child.Id)"
    return
}
Write-Host 'Gateway local: http://127.0.0.1:18790 (requiere token).'
Write-Host 'Estado y credenciales: .local-solobino/ (ignorado por Git). Ctrl+C para detener.'
openclaw gateway --port 18790 --bind loopback
if ($LASTEXITCODE -ne 0) { throw 'El gateway local termino con error.' }
