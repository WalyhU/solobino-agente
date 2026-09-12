param([ValidateSet('ollama', 'openclaw')][string]$Provider = 'ollama')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$backend = Join-Path $root 'voice-backend'
$desktop = Join-Path $root 'desktop-ui'
$python = Join-Path $backend 'venv\Scripts\python.exe'
$electron = Join-Path $desktop 'node_modules\electron\dist\electron.exe'
$configPath = Join-Path $root '.local-solobino\openclaw.json'
$logDir = Join-Path $root 'local-model-results'

foreach ($required in @($python, $electron)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Falta: $required" }
}
# These overrides apply only to this launcher and its children, not to .env.
$env:AGENT_PROVIDER = $Provider
if ($Provider -eq 'ollama') {
    $catalog = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5
    $env:OLLAMA_MODEL = 'qwen3.5:4b'
    $env:OLLAMA_BASE_URL = 'http://127.0.0.1:11434'
    if ($env:OLLAMA_MODEL -notin $catalog.models.name) { throw 'Falta qwen3.5:4b. Ejecuta scripts/start-local-model.ps1.' }
} else {
    $null = Invoke-RestMethod 'http://127.0.0.1:18790/health' -TimeoutSec 5
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    $env:OPENCLAW_GATEWAY_URL = 'ws://127.0.0.1:18790'
    $env:OPENCLAW_HTTP_BASE_URL = 'http://127.0.0.1:18790'
    $env:OPENCLAW_GATEWAY_TOKEN = $config.gateway.auth.token
    $env:OPENCLAW_SEND_MODE = 'http'
    $env:OPENCLAW_MODEL = 'openclaw/default'
    $env:OPENCLAW_SESSION_KEY = 'agent:main:solobino-voice'
}
$env:PYTHONUNBUFFERED = '1'
$null = New-Item -ItemType Directory -Path $logDir -Force

$ready = $false
try {
    $null = Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 2
    $ready = $true
} catch {}
if (-not $ready) {
    $backendProcess = Start-Process -FilePath $python -ArgumentList 'main.py' `
        -WorkingDirectory $backend -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logDir 'voice-backend.stdout.log') `
        -RedirectStandardError (Join-Path $logDir 'voice-backend.stderr.log')
    Write-Host "Backend iniciando. PID: $($backendProcess.Id)"
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        if ($backendProcess.HasExited) { throw 'El backend termino. Revisa local-model-results/voice-backend.stderr.log.' }
        try {
            $null = Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 1
            $ready = $true
            break
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $ready) { throw 'El backend aun no esta listo. Revisa sus logs antes de reintentar.' }
}
$health = Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 5
if ($health.agent_provider -ne $Provider) { throw "Ya existe un backend diferente en 8000. Detenlo antes de iniciar $Provider." }

$env:ELECTRON_RUN_AS_NODE = $null
# The mascot is the interactive window requested by the user.
$ui = Start-Process -FilePath $electron -ArgumentList '.' -WorkingDirectory $desktop -PassThru `
    -RedirectStandardOutput (Join-Path $logDir 'desktop-ui.stdout.log') `
    -RedirectStandardError (Join-Path $logDir 'desktop-ui.stderr.log')
Write-Host "Solobino abierto. PID de Electron: $($ui.Id). Backend: http://127.0.0.1:8000"
