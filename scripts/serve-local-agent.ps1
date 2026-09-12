$ErrorActionPreference = 'Stop'
$state = tailscale status --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $state.BackendState -ne 'Running') {
    throw 'Tailscale aun no esta conectado. Inicia sesion en Tailscale y vuelve a ejecutar.'
}
if (-not $state.Self.DNSName) { throw 'Tailscale no devolvio un nombre DNS.' }
# Port 8443 avoids taking over an existing default HTTPS service on 443.
$serve = tailscale serve status --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'No se pudo consultar Tailscale Serve.' }
if ($serve.TCP.'8443') { throw 'El puerto Serve 8443 ya esta configurado. Revisalo antes de cambiarlo.' }
tailscale serve --bg --https=8443 http://127.0.0.1:18790
if ($LASTEXITCODE -ne 0) { throw 'Tailscale Serve fallo; puede requerir habilitar HTTPS en tu cuenta.' }
Write-Host ('Acceso privado: https://' + $state.Self.DNSName.TrimEnd('.') + ':8443/')
Write-Host 'Solo dispositivos autorizados en tu tailnet. OpenClaw conserva autenticacion por token.'
