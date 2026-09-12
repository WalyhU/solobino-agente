param([string]$Model = 'qwen3.5:4b')

$ErrorActionPreference = 'Stop'
# Process-local settings: do not expose the unauthenticated Ollama API on the LAN.
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_CONTEXT_LENGTH = '8192'
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_MAX_LOADED_MODELS = '1'
$env:OLLAMA_KEEP_ALIVE = '15m'

$ollama = (Get-Command ollama -ErrorAction Stop).Source
$ready = $false
try {
    $null = Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2
    $ready = $true
} catch {}

if (-not $ready) {
    $logDir = Join-Path $PSScriptRoot '..\local-model-results'
    $null = New-Item -ItemType Directory -Path $logDir -Force
    $server = Start-Process -FilePath $ollama -ArgumentList 'serve' -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logDir 'ollama.stdout.log') `
        -RedirectStandardError (Join-Path $logDir 'ollama.stderr.log')
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $null = Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2
            $ready = $true
            break
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $ready) { throw 'Ollama no inicio. Revisa local-model-results/ollama.stderr.log.' }
    Write-Host "Ollama iniciado en loopback. PID: $($server.Id)"
}

$catalog = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags'
if ($Model -notin $catalog.models.name) {
    & $ollama pull $Model
    if ($LASTEXITCODE -ne 0) { throw "No se pudo descargar $Model" }
}
Write-Host "Modelo disponible: $Model. Ejecuta python scripts/benchmark-local-model.py"
