# Solobino

Asistente de voz con cliente de escritorio para Windows y macOS. El backend ejecuta la transcripción y el agente; cada cliente escucha la palabra de activación y ejecuta las herramientas locales autorizadas en su propio equipo.

## Arquitectura

- **Servicio:** `voice-backend/` (Python, WebSocket, Whisper y proveedor Ollama).
- **Cliente:** `desktop-ui/` (Electron y herramientas locales empaquetadas).
- **Palabra de activación:** `wakeword-model/wakeword.onnx` se ejecuta en el cliente; el backend confirma los candidatos con Whisper.

Consulta [INSTALACION.md](INSTALACION.md) para configurar el servicio, conectarlo por WSS e instalar los clientes. Para crear un instalador en una Mac, usa [PROMPT_MAC.md](PROMPT_MAC.md).

El flujo de GitHub Actions [Cliente Solobino](.github/workflows/client-installers.yml) genera instaladores para Windows y macOS. Los archivos `.env`, los entornos virtuales y los instaladores generados se excluyen del repositorio.
