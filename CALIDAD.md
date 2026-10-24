# Calidad de software en Solobino

| Herramienta | Qué hace aquí | Archivos |
|---|---|---|
| **Sandbox (Docker)** | Levanta el backend aislado, en CPU y sin GPU | `Dockerfile`, `docker-compose.yml`, `.env.sandbox` |
| **Pruebas unitarias** | 52 pruebas existentes + cobertura | `tests/test_*.py`, `.coveragerc` |
| **Postman / Newman** | Pruebas de la API HTTP (13 aserciones) | `tests/postman/solobino.postman_collection.json` |
| **Integración WebSocket** | Autenticación de `/ws` con token (Newman no soporta WebSocket) | `tests/integration/test_ws_sandbox.py` |
| **Selenium** | 9 pruebas de la ventana de configuración del cliente | `tests/selenium/test_settings_ui.py` |
| **Jenkins** | Ejecuta todo lo anterior en cada cambio | `Jenkinsfile`, `jenkins/` |

Requisitos en tu PC: **Docker Desktop**, **Git**, y para probar localmente **Python 3.11+** y **Node.js**.

---

## Paso 1 — Sandbox

```bash
docker compose up -d --build --wait
```
Abre http://localhost:8000/health → debe responder `{"status":"ok",...}`.
La primera vez descarga el modelo Whisper `tiny` (~75 MB). Para apagarlo: `docker compose down`.

## Paso 2 — Pruebas unitarias y cobertura (local)

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows (en Linux/macOS: source .venv/bin/activate)
pip install -r voice-backend/requirements.txt pytest pytest-cov selenium
python -m pytest tests --ignore=tests/selenium --ignore=tests/integration --cov --cov-report=xml:coverage.xml
```

## Paso 3 — Postman

1. Postman → **Import** → `tests/postman/solobino.postman_collection.json`.
2. Con el sandbox encendido, clic derecho en la colección → **Run collection** → 13 pruebas en verde.
3. WebSocket (manual, para evidencia): **New → WebSocket** → `ws://localhost:8000/ws` → **Connect** → envía
   `{"type":"client_hello","token":"sandbox-token-de-prueba","tools":[]}`. Con un token incorrecto el servidor cierra con código **1008**.

Desde consola (igual que Jenkins):
```bash
npm i -g newman newman-reporter-htmlextra
newman run tests/postman/solobino.postman_collection.json -r cli,htmlextra
```

## Paso 4 — Selenium y WebSocket (local)

```bash
python -m pytest tests/selenium -v          # abre Chrome headless; capturas en reports/selenium/
set SELENIUM_HEADLESS=0                     # (opcional, Windows) para ver el navegador
set SANDBOX_WS_URL=ws://localhost:8000/ws   # Linux/macOS: export ...
python -m pytest tests/integration -v
```
Necesitas Google Chrome instalado; Selenium descarga solo el ChromeDriver correcto.

## Paso 5 — Jenkins

```bash
docker compose -f jenkins/docker-compose.yml up -d --build
```
La imagen ya trae Python, Node, Chromium, Newman, los plugins y el cliente de Docker. Al arrancar,
Jenkins **crea solo** el job `solobino-calidad` (rama `calidad-software`) y lanza la primera ejecución:
no hay asistente de instalación ni contraseña. Por eso solo escucha en `127.0.0.1:8080`
(accesible únicamente desde tu PC).

Abre http://localhost:8080/job/solobino-calidad/ y usa **Build Now** para volver a ejecutarlo.
Antes, apaga el sandbox manual (`docker compose down`): el pipeline levanta el suyo en el puerto 8000.

### Etapas del pipeline
`Checkout → Preparar entorno → Pruebas unitarias + cobertura → Levantar sandbox → API Postman/Newman → Integración WebSocket → UI Selenium`
Al terminar publica los resultados JUnit, el **Reporte Postman** (HTML), las capturas de Selenium y el log del sandbox.

---

## Evidencias sugeridas para la entrega
- Jenkins: **Stage View** con todas las etapas en verde y la pestaña **Test Result**.
- Postman: resultado del **Collection Runner** y la conexión WebSocket.
- Selenium: capturas en `reports/selenium/` (o en los artefactos del build).

## Cambio en el código
`voice-backend/agentic_control.py` importaba `pyautogui` en cualquier sistema que no fuera macOS, pero
esa librería solo se instala en Windows. En Linux (Docker, Jenkins) eso rompía 3 pruebas y el arranque
del backend. Ahora, si no está disponible, el control de teclado queda desactivado con un error claro;
en Windows y macOS el comportamiento no cambia.
