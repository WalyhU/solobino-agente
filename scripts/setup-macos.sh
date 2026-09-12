#!/usr/bin/env bash
# Prepara Solobino en un Mac: entorno Python, dependencias npm y comprobaciones.
# El modelo no se instala aquí: se usa el de la PC por Tailscale.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backend="$root/voice-backend"
desktop="$root/desktop-ui"

echo "== Requisitos =="
for tool in python3 node npm; do
    command -v "$tool" >/dev/null || { echo "Falta $tool"; exit 1; }
    echo "  $tool $("$tool" --version 2>&1 | head -1)"
done
command -v tailscale >/dev/null && echo "  tailscale presente" || echo "  aviso: tailscale no está en el PATH"

echo "== Entorno Python =="
[[ -d "$backend/venv" ]] || python3 -m venv "$backend/venv"
"$backend/venv/bin/python" -m pip install --quiet --upgrade pip
# pyautogui no se instala: en macOS las acciones van por AppleScript.
"$backend/venv/bin/python" -m pip install --quiet \
    fastapi uvicorn "websockets" httpx faster-whisper numpy "mcp>=2.0" python-dotenv
echo "  dependencias instaladas"

echo "== Dependencias de la mascota =="
(cd "$desktop" && npm install --silent)

echo "== Configuración =="
if [[ ! -f "$backend/.env" ]]; then
    cp "$backend/.env.example" "$backend/.env"
    echo "  creado voice-backend/.env desde la plantilla"
fi
pc_ip="$(grep -E '^OLLAMA_BASE_URL=' "$backend/.env" | cut -d= -f2- || true)"
echo "  Ollama configurado en: ${pc_ip:-sin definir}"
if [[ -n "$pc_ip" ]] && curl -sf --max-time 5 "$pc_ip/api/tags" >/dev/null; then
    echo "  modelo accesible"
else
    echo "  aviso: no alcanzo ese Ollama. Edita OLLAMA_BASE_URL con la IP de"
    echo "  Tailscale de la PC (la ves con 'tailscale status') y vuelve a probar."
fi

cat <<'NOTA'

== Permisos de macOS ==
Solobino necesita que le concedas, la primera vez que lo intente:
  - Micrófono: Ajustes del Sistema -> Privacidad y seguridad -> Micrófono
  - Accesibilidad (pulsar botones y escribir): Privacidad y seguridad -> Accesibilidad
  - Automatización (controlar Music y otras apps): Privacidad y seguridad -> Automatización
El permiso se pide para la app que lanza las acciones: si arrancas desde la
Terminal, concédeselo a la Terminal.

Listo. Arranca con: scripts/start-solobino.sh
NOTA
