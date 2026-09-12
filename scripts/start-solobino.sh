#!/usr/bin/env bash
# Arranca Solobino en macOS: backend local (Whisper + herramientas) y mascota.
# El modelo se usa en remoto, así que este equipo no necesita GPU.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backend="$root/voice-backend"
desktop="$root/desktop-ui"
logs="$root/local-model-results"
python="$backend/venv/bin/python"

[[ -x "$python" ]] || { echo "Falta el entorno: ejecuta scripts/setup-macos.sh"; exit 1; }
[[ -d "$desktop/node_modules" ]] || { echo "Faltan dependencias npm: ejecuta scripts/setup-macos.sh"; exit 1; }

ollama_url="${OLLAMA_BASE_URL:-$(grep -E '^OLLAMA_BASE_URL=' "$backend/.env" 2>/dev/null | cut -d= -f2- || true)}"
[[ -n "$ollama_url" ]] || { echo "Define OLLAMA_BASE_URL en voice-backend/.env (la IP de Tailscale de la PC)"; exit 1; }

# Sin el modelo accesible la mascota arrancaría para no responder nada.
if ! curl -sf --max-time 5 "$ollama_url/api/tags" >/dev/null; then
    echo "No alcanzo Ollama en $ollama_url"
    echo "Comprueba que la PC esté encendida y que 'tailscale status' la vea."
    exit 1
fi
echo "Ollama remoto accesible: $ollama_url"

mkdir -p "$logs"
export AGENT_PROVIDER="${AGENT_PROVIDER:-ollama}"
export PYTHONUNBUFFERED=1

if curl -sf --max-time 2 http://127.0.0.1:8000/health >/dev/null; then
    echo "El backend ya estaba en marcha."
else
    (cd "$backend" && "$python" main.py \
        >"$logs/voice-backend.stdout.log" 2>"$logs/voice-backend.stderr.log") &
    echo "Backend iniciando. PID: $!"
    for _ in $(seq 1 60); do
        curl -sf --max-time 1 http://127.0.0.1:8000/health >/dev/null && break
        sleep 1
    done
    curl -sf --max-time 2 http://127.0.0.1:8000/health >/dev/null \
        || { echo "El backend no respondió. Revisa $logs/voice-backend.stderr.log"; exit 1; }
fi

(cd "$desktop" && npm start >"$logs/desktop-ui.stdout.log" 2>"$logs/desktop-ui.stderr.log") &
echo "Solobino abierto. Mascota PID: $!. Backend: http://127.0.0.1:8000"
