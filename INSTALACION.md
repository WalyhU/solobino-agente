# Solobino en Windows y macOS

## Arquitectura

Una instalación del backend ejecuta Whisper y el modelo de Ollama. Cada PC o Mac
instala la app Electron. La app captura el micrófono y ejecuta **en ese equipo**
las acciones de aplicaciones, teclado, música y archivos. No necesita Python,
Node, Ollama ni OpenClaw después de instalarse.

El servicio y cada cliente se comunican por WebSocket. Para equipos distintos,
publica el servicio detrás de HTTPS/WSS (por ejemplo, un proxy con TLS en una
red privada). El cliente solo admite `ws://` cuando el servidor es localhost.

## Preparar el servicio

En Windows o macOS, instala Python 3.11 o superior y Ollama en el equipo servidor:

```sh
cd voice-backend
python -m venv venv
# Windows: venv\Scripts\python.exe -m pip install -r requirements.txt
# macOS:   venv/bin/python -m pip install -r requirements.txt
```

Copia `voice-backend/.env.example` a `voice-backend/.env`. Configura:

```dotenv
AGENT_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
SOLOBINO_HOST=0.0.0.0
SOLOBINO_PORT=8000
SOLOBINO_CLIENT_TOKEN=un-token-aleatorio-largo
```

Desde `voice-backend`, inicia `venv/Scripts/python.exe main.py` en Windows o
`venv/bin/python main.py` en macOS. El endpoint `/health` comprueba que está
arriba. Usa un proxy TLS para exponer `/ws` como `wss://.../ws`; no publiques el
puerto 8000 sin cifrado en Internet. Cada cliente usa el mismo token del servicio.

## Instalar el cliente

El flujo de GitHub Actions `.github/workflows/client-installers.yml` genera un
instalador `.exe` para Windows y paquetes `.dmg` para Mac con Apple Silicon e
Intel. Descarga el artefacto de tu sistema e instala Solobino. Al abrir por
primera vez, introduce la URL
`wss://.../ws` y el token. El menú **Solobino → Configurar servidor** permite
cambiarlos después. También se abre la configuración al hacer clic derecho
sobre la mascota.

En macOS concede Micrófono, Accesibilidad y Automatización cuando el sistema lo
pida. Los paquetes de desarrollo no llevan firma de distribución: Windows puede
mostrar SmartScreen y macOS puede mostrar Gatekeeper. Para distribución pública
sin esos avisos hacen falta certificados de firma y notarización de Apple.

## Desarrollar el cliente sin instalador

Instala el entorno Python ligero del cliente en `voice-backend/venv` con
`desktop-ui/client-requirements.txt`, instala Electron con `npm ci` en
`desktop-ui` y ejecuta `npm start`. El cliente usará el mismo proceso de
herramientas que se empaqueta en los instaladores.

Las herramientas de archivos operan únicamente bajo Escritorio, Documentos y
Descargas del usuario del cliente. El modelo no puede ejecutar comandos de
shell arbitrarios. La ruta heredada `AGENT_PROVIDER=openclaw` sigue siendo
local; para el servicio remoto usa `AGENT_PROVIDER=ollama`.

La palabra de activación se evalúa en el cliente con el modelo ONNX incluido en
el instalador. Se analizan ventanas solapadas de audio continuo. Solo cuando el
modelo marca un candidato se envía un clip corto al backend para confirmarlo con
Whisper. Si el modelo local no se puede cargar, el cliente usa el detector remoto
anterior. En desarrollo, instala también `desktop-ui/client-requirements.txt` en
el entorno Python que ejecuta `voice-backend/client_tools.py`.
