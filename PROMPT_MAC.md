# Prompt para construir Solobino en Mac

Copia este texto en Codex en la MacBook:

> Descarga el repositorio de Solobino desde https://github.com/WalyhU/solobino-agente. Si ya existe una copia local, actualízala con `git pull` conservando cualquier cambio propio. Trabaja en la raíz del repositorio.
>
> Construye un instalador `.dmg` para la arquitectura de esta Mac (Apple Silicon o Intel) del cliente Electron en `desktop-ui/`. El backend es un servicio aparte y no debe incluirse en el instalador; sí debes empaquetar el ejecutable local `solobino-tools` y el modelo `wakeword-model/wakeword.onnx`, junto con `wakeword_meta.json`, para que el cliente pueda detectar la palabra de activación y usar sus herramientas.
>
> Lee `README.md`, `INSTALACION.md`, `desktop-ui/package.json` y `.github/workflows/client-installers.yml`. Usa Python 3.12 y Node.js 22. Crea un entorno virtual `.client-build-venv`, instala `desktop-ui/client-requirements.txt` y ejecuta las pruebas `tests/test_remote_tools.py` y `tests/test_client_tools.py`. Empaqueta `voice-backend/client_tools.py` con PyInstaller siguiendo la sección macOS del workflow, de modo que el resultado quede en `desktop-ui/bin/solobino-tools`. Luego ejecuta `npm ci`, las pruebas Node del workflow y `npm run dist` desde `desktop-ui/`.
>
> Verifica que el `.dmg` se genera en `desktop-ui/dist/`, que el paquete contiene `solobino-tools`, el modelo ONNX y sus metadatos, y que la app abre y permite configurar la URL `wss://.../ws` y el token del servicio. Informa la ruta absoluta del `.dmg`, su tamaño, la arquitectura, las pruebas ejecutadas y cualquier limitación. No subas secretos ni el archivo `.env` al repositorio. Si macOS pide permisos de Micrófono, Accesibilidad o Automatización, indica cuáles se deben conceder. El paquete de desarrollo puede requerir abrirse manualmente por no estar firmado ni notarizado.

El repositorio es público, así que `git clone https://github.com/WalyhU/solobino-agente.git` no requiere autenticación para descargarlo.
