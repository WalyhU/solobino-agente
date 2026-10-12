# Solobino: conversación local directa

Para usar este backend como servicio central y clientes instalables en Windows y
macOS, consulta [INSTALACION.md](../INSTALACION.md). Las instrucciones siguientes
describen el modo local de desarrollo.

El modo predeterminado conecta FastAPI directamente a Ollama, sin iniciar un
cliente de OpenClaw. Usa Whisper para transcribir y envía `agent_delta` a Electron
conforme se genera texto. `agent_response` finaliza el turno; `agent_error` permite
recuperar la interfaz y volver a intentarlo.

Desde la raíz, con las dependencias instaladas:

```powershell
.\scripts\start-local-model.ps1
.\scripts\start-solobino.ps1
```

Para ejecutar solo el backend, activar su entorno y ejecutar `python main.py`
dentro de `voice-backend`. Instalar dependencias con `pip install -r requirements.txt`.

| Variable | Predeterminado | Uso |
|---|---|---|
| `AGENT_PROVIDER` | `ollama` | `openclaw` conserva la ruta anterior |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Servicio de inferencia |
| `OLLAMA_MODEL` | `qwen3.5:4b` | Modelo local descargado |

El cliente precarga el modelo al iniciar y solicita mantenerlo cargado 15 minutos.
Usa thinking desactivado, salida máxima de 256 tokens y cuatro turnos anteriores
por conexión. Una desconexión o un mensaje `{"type":"cancel"}` cancela la petición
HTTP; las respuestas parciales fallidas no se guardan en el historial.
`GET /health` identifica el proveedor activo; no comprueba que Ollama siga disponible.

En modo remoto, el cliente ejecuta las herramientas y detecta candidatos de
"Solobino" con ONNX. El backend confirma cada candidato con Whisper. La URL
privada de Tailscale configurada anteriormente sigue apuntando al gateway
OpenClaw independiente, no a este backend de voz.

Para volver temporalmente a OpenClaw, detener primero el backend actual y ejecutar:

```powershell
.\scripts\start-local-agent.ps1 -Background
.\scripts\start-solobino.ps1 -Provider openclaw
```

Los lanzadores aplican sus variables solo al proceso; no reemplazan `.env`.
El launcher se niega a usar un backend activo de otro proveedor.

## Verificación

```powershell
.\voice-backend\venv\Scripts\python.exe -m unittest discover -s tests -v
node --test desktop-ui/test-streaming.cjs
node --test desktop-ui/test-wake.cjs
```

Las pruebas cubren streaming antes del final, historial limitado y aislado,
desconexión/cancelación, respuesta incompleta, servidor con error, audio sin voz,
ausencia de conexión a OpenClaw y recuperación de la interfaz.

Prueba real en RTX 3060, con audio sintético español enviado al WebSocket y
Whisper `small` en GPU: primer texto en **0,29–0,63 s** y respuesta completa en
**0,65–0,98 s** (dos solicitudes). Los resultados están en
`local-model-results/voice-direct.json`. Incluye STT y generación, pero excluye
duración de habla, detección de wake word, espera de silencio y red externa.
Es una muestra pequeña con el modelo precargado, no una garantía de latencia.

## Herramientas locales (paso 3)

El agente ya ejecuta acciones sobre el PC sin pasar por OpenClaw.

| Herramienta | Argumento | Validación |
|---|---|---|
| `open_application` | `app_name` | debe resolverse en `app_index` (Menú Inicio + PATH) |
| `open_url` | `url` | solo `http://` y `https://`, sin espacios ni comillas |
| `type_text` | `text` | máximo 500 caracteres |
| `press_key` | `key` | teclas y atajos de `tools.KEY_ALLOWLIST` / `HOTKEY_ALLOWLIST` |
| `play_music` | `query`, `scope` | `scope` en `latest_album`/`album`/`song` |
| `media_control` | `action` | `reproducir`/`pausar`/`siguiente`/`anterior` |
| `click_in_app` | `app_name`, `control_name` | nombre de botón de ≤60 caracteres |
| `open_file_with` | `app_name`, `path` | la ruta debe existir y la app tener ejecutable |
| `open_path` | `path` | la ruta debe existir |

Flujo: Ollama devuelve `tool_calls` → `tools.validate` normaliza los argumentos →
`PCController` lanza el ejecutable con `subprocess.Popen([...], shell=False)` → el
resultado vuelve al modelo como mensaje `role: "tool"`. Máximo `MAX_TOOL_ROUNDS = 3`
vueltas; en la última se retiran las herramientas para forzar una respuesta de texto.

La mascota recibe un evento `agent_tool` (`{name, text}`) por cada acción ejecutada.
El mensaje WS `control_pc` pasa por la misma validación que el modelo.

Medición contra Ollama real (sin voz, controlador simulado):

| Caso | Primer texto | Total |
|---|---:|---:|
| «Abre la calculadora» (con herramienta) | 1,15 s | 1,25 s |
| Pregunta sin herramienta | 0,37 s | 0,62 s |

Pruebas: `voice-backend/venv/Scripts/python.exe -m unittest discover -s tests` (21).

### Índice de aplicaciones (`app_index.py`)

No hay lista blanca de apps: se abre cualquier aplicación instalada. El índice se
construye con `Get-StartApps` (lo mismo que muestra el Menú Inicio, incluidas apps
UWP) más los ejecutables del PATH, y se refresca cada 5 minutos o cuando falla una
búsqueda. Se precarga al arrancar el backend (~1,4 s, 1.400 entradas en este PC).

Resolución del nombre: exacta → por palabras (`chrome` encuentra `Google Chrome`) →
aproximada con `difflib` (corte 0,85). Si no hay coincidencia, el modelo recibe un
error con nombres parecidos y puede reintentar.

`DENY_KEYWORDS` excluye del índice lo que no debería abrirse por voz:
desinstaladores, `regedit`, PowerShell, `cmd`, administrador de tareas y directivas
de grupo.

El texto del modelo solo **selecciona** una entrada del índice; nunca se convierte
en ruta ni en línea de comandos. El lanzamiento usa
`Popen(["explorer.exe", "shell:AppsFolder\<AppID>"])` o `os.startfile(ruta)`, ambos
sin shell.


## Actuar dentro de las apps

Dos mecanismos, ninguno necesita ver la pantalla.

**Catálogo real de música** (`music_search.py`). La API pública de búsqueda de
iTunes (sin clave) resuelve el artista y su discografía: «el álbum más reciente de
Bruno Mars» se convierte en un enlace concreto en vez de un título inventado. Para
`latest_album` se consulta `lookup` por `artistId`, lo que evita discos tributo de
otros intérpretes, y se descartan los sencillos (<5 pistas).

**Pulsar controles por nombre** (`ui_automation.py` + `scripts/ui-invoke.ps1`).
UI Automation localiza el botón en el árbol de accesibilidad de la ventana y lo
invoca. Sin coordenadas ni capturas, así que no se rompe al mover la ventana. Si el
botón no existe, devuelve los nombres reales disponibles y el modelo reintenta.
Cuando un mismo nombre aparece varias veces se elige el control más grande: el de
la vista principal, no el de la barra de transporte.

Flujo de `play_music`: iTunes resuelve el álbum → `os.startfile("musics://…")` abre
la ficha en la app de Apple Music → UI Automation pulsa «Reproducir». `media_control`
usa los botones de la app y, si no hay ventana, cae a las teclas multimedia.

Medición real, orden completa «abre Apple Music y reproduce el álbum más reciente de
Bruno Mars»: **4,5 s** (dos herramientas, 1.262 tokens de entrada). «Pausa la
música»: **1,8 s**.

Pendiente: respaldo con visión para lo que no tenga receta ni control accesible.


## MCP: herramientas sin programarlas aquí

`mcp_client.py` conecta servidores MCP declarados en `voice-backend/mcp.json`
(mismo formato `mcpServers` que otros clientes). Al arrancar descubre sus
herramientas, las traduce al formato de Ollama y el modelo las llama igual que las
locales. `allowedTools` limita cuáles se exponen: cada herramienta extra suma
tokens de entrada y confunde más a un modelo de 4B.

Servidor activo: `@modelcontextprotocol/server-filesystem` sobre Escritorio,
Documentos y Descargas, con 7 de sus 14 herramientas. Añadir otro servidor es
editar `mcp.json`; no hay que tocar código.

Si un servidor no arranca, se registra el fallo y el asistente sigue con el resto.
Las rutas permitidas se inyectan en el prompt del sistema: sin ellas el modelo
inventaba rutas relativas y escribía fuera de las carpetas concedidas.

Medición real, con 14 herramientas ofrecidas (7 locales + 7 MCP):

| Orden | Herramienta | Total | Tokens de entrada |
|---|---|---:|---:|
| «Crea hola.html en el escritorio con un título…» | `archivos__write_file` | 3,4 s | 2.373 |
| «Ábrelo en Visual Studio Code» | `open_file_with` | 2,6 s | 2.342 |

Sigue muy por debajo de los ~7.600 tokens por turno de OpenClaw.


## Abrir archivos con la aplicación correcta

Solo un **ejecutable** acepta argumentos. Las entradas del Menú Inicio son AppIDs y
no los admiten, así que la primera versión lanzaba la app por su AppID *y además*
abría el archivo con `os.startfile`: dos ventanas, y el archivo iba al programa
predeterminado en vez de al pedido. De ahí «abre el navegador pero no el archivo» y
«abre VS Code sin la carpeta».

Ahora `app_index` guarda el ejecutable real de cada aplicación, resolviéndolo en
tres pasos: destino del acceso directo del Menú Inicio → clave `App Paths` del
registro si ese destino ya no existe → `shutil.which`. Las entradas cuyo acceso
directo quedó huérfano (la app ya no está instalada) se eliminan del índice, para
que el asistente diga «no la encuentro» en vez de abrir una ventana vacía.

- `open_file_with(app, ruta)` → `Popen([ejecutable, ruta])`. Una sola ventana, con
  la aplicación pedida. Acepta **carpetas**: para un proyecto en VS Code se pasa la
  carpeta, no cada archivo.
- `open_path(ruta)` → programa predeterminado de Windows. Es la opción explícita
  cuando da igual con qué se abra.
- Si la aplicación no tiene ejecutable (por ejemplo una app UWP como Calculadora),
  `open_file_with` se niega y sugiere `open_path`, en lugar de abrir dos cosas.

Comprobado: «crea una carpeta sitio-prueba con index.html y style.css» (7,4 s, tres
herramientas MCP) y «ábrela en Visual Studio Code» (4,7 s) dejan VS Code abierto con
esa carpeta y sus dos archivos en el explorador, en una única ventana.


## Usarlo en un Mac con el modelo en la PC

El Mac ejecuta el asistente completo (micrófono, Whisper, herramientas) y solo el
modelo es remoto: `OLLAMA_BASE_URL` apunta al Ollama de la PC por Tailscale. Las
acciones ocurren **en el Mac**, que es la diferencia con usar la mascota como mando
a distancia de la PC.

```
Mac: mascota -> WS 8000 local -> Whisper (CPU) -> herramientas del Mac
                                      |
                                      +-> Tailscale -> Ollama de la PC (RTX 3060)
```

### Puesta en marcha

```bash
git pull
scripts/setup-macos.sh          # venv, npm install y comprobaciones
# edita voice-backend/.env si la IP de Tailscale de la PC cambió
scripts/start-solobino.sh
```

`setup-macos.sh` no instala `pyautogui`: en macOS todo va por AppleScript.
`start-solobino.sh` se niega a arrancar si no alcanza el Ollama remoto, para no
abrir una mascota que no podría responder.

### Equivalencias por sistema

| Capacidad | Windows | macOS (`mac_desktop.py`) |
|---|---|---|
| Descubrir apps | `Get-StartApps` + PATH + `App Paths` | paquetes `.app` y su `CFBundleDisplayName` |
| Abrir app | `explorer.exe shell:AppsFolder\<AppID>` | `open -a <ruta del .app>` |
| Abrir archivo o carpeta con una app | `Popen([ejecutable, ruta])` | `open -a <app> <ruta>` |
| Pulsar un botón por su nombre | UI Automation | `System Events` (accesibilidad) |
| Escribir y teclas | `pyautogui` | `keystroke` / `key code` de AppleScript |
| Atajos | `ctrl+…` | se traduce a `command` |
| Música | enlace `musics:` + pulsar «Reproducir» | AppleScript sobre Music.app |
| Whisper | `medium` en CUDA `float16` | `small` en CPU `int8` (automático) |

En ambos sistemas el nombre que dice el modelo solo **selecciona** una entrada ya
descubierta, y en AppleScript viaja como argumento (`on run argv`), nunca
interpolado en el texto del script.

También cambia lo vetado: en macOS se excluyen del índice Terminal, iTerm, Acceso a
Llaveros, Utilidad de Discos y Monitor de Actividad.

### Permisos de macOS

Se conceden a la aplicación que lanza las acciones (si arrancas desde la Terminal,
a la Terminal): Micrófono, Accesibilidad (pulsar botones y escribir) y Automatización
(controlar Music y demás). Sin Accesibilidad, `click_in_app` devuelve un aviso que
lo dice en vez de fallar en silencio.

### Rutas del MCP

`mcp.json` usa `~/Desktop`, `~/Documents` y `~/Downloads`; `mcp_client` expande `~`
y las variables de entorno, así que el mismo archivo vale en los dos sistemas.

### Pendiente de comprobar en el Mac

Nada de la parte macOS se ha ejecutado en un Mac real todavía: las pruebas
(`tests/test_mac_desktop.py`) verifican la lógica, no la respuesta del sistema.
Quedan por medir la latencia de Whisper en CPU y por confirmar los nombres de los
botones de Music.app en español.
