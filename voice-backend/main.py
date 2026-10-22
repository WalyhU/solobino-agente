import asyncio
import base64
import concurrent.futures
import contextlib
import difflib
import functools
import json
import os
import sys
import re
import secrets
import tempfile
import time
import unicodedata
import uuid
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
import httpx

def _register_cuda_dll_dirs() -> None:
    """En Windows, faster-whisper/CTranslate2 necesitan las DLLs de cuBLAS/cuDNN/cudart
    (paquetes nvidia-*-cu12) localizables. CTranslate2 las carga sin respetar
    os.add_dll_directory, así que las prepende al PATH ANTES de importar el modelo.
    Sin esto el GPU carga pero la transcripción falla con 'cublas64_12.dll is not found'."""
    if os.name != "nt":
        return
    import glob
    import site

    roots = list(site.getsitepackages())
    user_site = site.getusersitepackages()
    if isinstance(user_site, str):
        roots.append(user_site)

    bindirs = []
    seen = set()
    for sp in roots:
        for bindir in glob.glob(os.path.join(sp, "nvidia", "*", "bin")):
            if os.path.isdir(bindir) and bindir not in seen:
                seen.add(bindir)
                bindirs.append(bindir)

    if bindirs:
        os.environ["PATH"] = os.pathsep.join(bindirs) + os.pathsep + os.environ.get("PATH", "")


_register_cuda_dll_dirs()

import websockets as ws_client
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from faster_whisper import WhisperModel
import uvicorn

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    # python-dotenv is optional. Environment variables still work without it.
    pass

from agentic_control import PCController, app_index
from mcp_client import MCPToolset
from tools import ToolRunner
from wakeword_infer import WakeWordDetector
from local_agent import OllamaAgent
from remote_tools import RemoteToolset

# `features.load_audio` (de wakeword-model/) decodifica webm/opus a PCM mono float32 a 16 kHz
# usando PyAV. Lo reusamos como gate de energía para descartar segmentos silenciosos
# antes de transcribir y evitar alucinaciones de Whisper sobre ruido.
# wakeword_infer.py añade wakeword-model/ a sys.path al importarse.
try:
    from features import load_audio as _load_audio_pcm  # type: ignore
except Exception as _e:
    print(f"[WakeWord] features.load_audio no disponible ({_e}); energy gate desactivado.")
    _load_audio_pcm = None


# --- Configuration & Globals ---
# En macOS no hay CUDA: faster-whisper corre en CPU con int8, y un modelo
# grande dispararía la latencia. El .env puede sobrescribir cualquiera de los tres.
_IS_MACOS = sys.platform == "darwin"
MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "small" if _IS_MACOS else "medium")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu" if _IS_MACOS else "cuda")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE_TYPE", "int8" if _IS_MACOS else "float16")


def _load_whisper() -> WhisperModel:
    """Carga Whisper en GPU; si falla CUDA, cae a CPU int8 para no romper la demo.
    Hace warm-up con un buffer de silencio para pagar la inicialización de kernels CUDA
    y allocadores ahora y no en el primer comando real."""
    try:
        print(f"Loading Whisper '{MODEL_SIZE}' on {WHISPER_DEVICE} ({WHISPER_COMPUTE})...")
        m = WhisperModel(MODEL_SIZE, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE)
        print("Model loaded successfully.")
    except Exception as e:
        print(f"[Whisper] No se pudo cargar en {WHISPER_DEVICE} ({e}). Cayendo a CPU int8.")
        m = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
        print("Model loaded on CPU.")

    try:
        warm = np.zeros(16000, dtype=np.float32)
        list(m.transcribe(warm, language="es", beam_size=1, without_timestamps=True)[0])
        print("[Whisper] Warm-up listo.")
    except Exception as e:
        print(f"[Whisper] Warm-up falló (no crítico): {e}")

    return m


model = _load_whisper()

# Pool dedicado de 1 worker para Whisper. Evita que la transcripción comparta
# el ThreadPoolExecutor por defecto con DNS/IO y se serializa correctamente
# (el modelo no es thread-safe para llamadas concurrentes).
_whisper_pool = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="whisper"
)

pc_controller = PCController()
tool_runner = ToolRunner(pc_controller)
mcp_tools = MCPToolset()

# Detector de wake-word con la CNN propia (ONNX). Si no hay modelo entrenado,
# `available` es False y se usa Whisper + regex como fallback.
wake_detector = WakeWordDetector()

# Anti-rebote por cliente: no dispares el wake más de una vez cada N segundos.
WAKE_COOLDOWN_S = float(os.getenv("WAKE_COOLDOWN_S", "8.0"))

# Umbral RMS (float32 normalizado, rango ~[0,1]) por debajo del cual ignoramos un
# segmento como silencio/ruido y NO lo transcribimos ni inferimos.
WAKE_VOICE_RMS = float(os.getenv("WAKE_VOICE_RMS", "0.012"))

# Si True, cuando la CNN dispara, transcribimos con Whisper y solo confirmamos el
# wake si el texto contiene "solobino". Mata casi todos los falsos positivos de
# una CNN poco generalizada a costa de ~150-300 ms extra.
WAKEWORD_REQUIRE_STT_CONFIRM = os.getenv("WAKEWORD_REQUIRE_STT_CONFIRM", "true").strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


# Si False, ignoramos la CNN aunque exista el modelo y detectamos el wake solo con
# Whisper + regex. La CNN confunde palabras fonéticamente parecidas ("salud vino")
# incluso reentrenada con negativos; Whisper transcribe y el regex filtra mejor.
WAKEWORD_USE_CNN = _env_bool("WAKEWORD_USE_CNN", False)

# Palabra clave que pasamos a Whisper como `hotwords` SOLO al verificar el wake,
# para que emita "Solobino" en vez de castearla a "solo vino". No se usa en la
# transcripción normal de comandos (no queremos sesgar todo hacia el wake).
WAKE_HOTWORD = os.getenv("WAKE_HOTWORD", "Solobino")


def _env_list(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def _normalize_text(text: str) -> str:
    """Minúsculas, sin acentos, sin puntuación. Espacios colapsados."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# Solo "solobino"/"solabina" cercanos. Antes aceptábamos [bvmpf] como segunda
# consonante, lo que matcheaba alucinaciones comunes de Whisper sobre silencio
# ("sólo vino", "sola pino", "solo fino") y disparaba el wake sin que hablaras.
_WAKE_WORD_RE = re.compile(r"\bsol[oa]\s*bin[oa]\b")

# Umbral conservador: 0.82 aceptaba "solo vino" (similitud 0.875) como wake.
# Se prefieren variantes exactas y se deja una tolerancia mínima a Whisper.
_WAKE_TARGETS = ("solobino", "solabina")
_WAKE_FUZZY_RATIO = float(os.getenv("WAKE_FUZZY_RATIO", "0.90"))


def _is_wake_word(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    if _WAKE_WORD_RE.search(normalized):
        return True
    # Pega palabras (Whisper mete espacios: "solo vino" -> "solovino") y compara.
    collapsed = normalized.replace(" ", "")
    return any(
        difflib.SequenceMatcher(None, collapsed, target).ratio() >= _WAKE_FUZZY_RATIO
        for target in _WAKE_TARGETS
    )


_WHISPER_KW = dict(
    beam_size=1,                       # 1 ~ 2-3x más rápido que 5; pérdida WER mínima en cortos
    vad_filter=True,                   # silero VAD: corta silencios antes de inferir
    vad_parameters={"min_silence_duration_ms": 500, "threshold": 0.5},
    condition_on_previous_text=False,  # evita reintentos por temperatura/contexto arrastrado
    without_timestamps=True,           # ahorra alineamiento
    temperature=0.0,                   # determinista; sin escalado de temperatura
    # Anti-alucinación: Whisper se entrenó con subtítulos de YouTube y suelta
    # "gracias por ver / suscríbete" sobre silencio. Subimos los umbrales:
    no_speech_threshold=0.8,           # default 0.6: más estricto al marcar "no hay habla"
    log_prob_threshold=-0.7,           # default -1.0: descarta tokens de baja confianza
    compression_ratio_threshold=2.2,   # default 2.4: alucinaciones suelen comprimir mucho
)


# Frases típicas que Whisper alucina sobre silencio o ruido (canal YouTube).
# Si la transcripción cae aquí, la descartamos sin mandarla al agente.
_HALLUCINATION_PHRASES = (
    "gracias por ver",
    "gracias por su atencion",
    "suscribete",
    "subscribete",
    "subtitulos realizados por la comunidad",
    "subtitulado por la comunidad",
    "subtitulos por la comunidad",
    "amara org",
    "no te olvides de suscribirte",
    "dale like",
    "dale me gusta",
    "nos vemos en el proximo video",
    "hasta la proxima",
    "hasta el proximo video",
    "comenta y suscribete",
)


def _is_hallucination(text: str) -> bool:
    if not text:
        return True
    norm = _normalize_text(text)
    return any(p in norm for p in _HALLUCINATION_PHRASES)


def _transcribe_blocking(
    audio: bytes | np.ndarray, language: str = "es", hotwords: str | None = None
) -> str:
    """Transcribe síncronamente. Pensado para ejecutarse en el pool dedicado.
    Acepta bytes (webm/opus) o ndarray PCM float32 16k mono. PCM directo evita
    el tempfile y ahorra ~50-80 ms por chunk. `hotwords` sesga el decoder hacia
    una palabra (ej. el wake "Solobino", que al no ser palabra real Whisper
    castea a "solo vino"/"sorrino")."""
    if isinstance(audio, np.ndarray):
        source = audio
        tmp_path: str | None = None
    elif _load_audio_pcm is not None:
        try:
            source = _load_audio_pcm(audio)
        except Exception:
            # Si PyAV no decodifica, fallback al temp file de toda la vida.
            source = None
            tmp_path = None
        else:
            tmp_path = None
        if source is None:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".webm")
            tmp.write(audio); tmp.close()
            tmp_path = tmp.name
            source = tmp_path
    else:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".webm")
        tmp.write(audio); tmp.close()
        tmp_path = tmp.name
        source = tmp_path

    try:
        kw = dict(_WHISPER_KW)
        if hotwords:
            kw["hotwords"] = hotwords
        segments, _info = model.transcribe(source, language=language, **kw)
        return "".join(segment.text for segment in segments).strip()
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def _transcribe_async(
    audio: bytes | np.ndarray, language: str = "es", hotwords: str | None = None
) -> str:
    """Ejecuta `_transcribe_blocking` en el pool dedicado de Whisper."""
    loop = asyncio.get_running_loop()
    func = functools.partial(
        _transcribe_blocking, audio, language, hotwords=hotwords
    )
    return await loop.run_in_executor(_whisper_pool, func)


def _segment_has_voice(audio_bytes: bytes, threshold: float | None = None) -> bool:
    """True si el segmento parece tener voz (RMS sobre umbral). Si no podemos
    decodificar, asumimos True para no perder voz real."""
    if _load_audio_pcm is None:
        return True
    thr = WAKE_VOICE_RMS if threshold is None else threshold
    try:
        samples = _load_audio_pcm(audio_bytes)
        if samples is None or len(samples) == 0:
            return False
        rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
        return rms >= thr
    except Exception as e:
        print(f"[WakeWord] energy gate decode error: {e}")
        return True


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast_json(self, message: dict):
        stale_connections: list[WebSocket] = []

        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                print(f"Failed to send to Electron client: {e}")
                stale_connections.append(connection)

        for connection in stale_connections:
            self.disconnect(connection)


manager = ConnectionManager()


# --- OpenClaw Client ---
class OpenClawGatewayClient:
    """
    OpenClaw Gateway WS client.

    Expected env vars:
      OPENCLAW_GATEWAY_URL=ws://127.0.0.1:18789
      OPENCLAW_GATEWAY_TOKEN=<real gateway token>
      OPENCLAW_SESSION_KEY=agent:main:main

    Optional:
      OPENCLAW_SEND_MODE=auto  # auto | ws | http
      OPENCLAW_HTTP_BASE_URL=http://127.0.0.1:18789
      OPENCLAW_MODEL=openclaw/default

      OPENCLAW_CLIENT_ID=gateway-client
      OPENCLAW_CLIENT_MODE=backend
      OPENCLAW_SCOPES=operator.read,operator.write
      OPENCLAW_CHAT_DELIVER=false
    """

    def __init__(self):
        self.uri = os.getenv("OPENCLAW_GATEWAY_URL", "ws://127.0.0.1:18789")
        self.session_key = os.getenv("OPENCLAW_SESSION_KEY", "agent:main:main")
        self.chat_deliver = _env_bool("OPENCLAW_CHAT_DELIVER", False)

        # Sending options:
        # - ws: use Gateway WS RPC chat.send only.
        # - http: use OpenAI-compatible HTTP endpoint only.
        # - auto: try WS first, then fall back to HTTP if the Gateway returns missing scope.
        self.send_mode = os.getenv("OPENCLAW_SEND_MODE", "auto").strip().lower()
        if self.send_mode not in {"auto", "ws", "http"}:
            print(f"[OpenClaw] Invalid OPENCLAW_SEND_MODE={self.send_mode!r}; using auto.")
            self.send_mode = "auto"

        self.http_base_url = os.getenv("OPENCLAW_HTTP_BASE_URL", "").strip() or self._derive_http_base_url(self.uri)
        self.http_chat_url = self.http_base_url.rstrip("/") + "/v1/chat/completions"
        self.openclaw_model = os.getenv("OPENCLAW_MODEL", "openclaw/default")

        # For direct loopback helper flows, OpenClaw supports gateway-client/backend.
        # Keep these configurable in case your installed OpenClaw build expects cli/operator.
        self.client_id = os.getenv("OPENCLAW_CLIENT_ID", "gateway-client")
        self.client_mode = os.getenv("OPENCLAW_CLIENT_MODE", "backend")
        self.client_platform = os.getenv("OPENCLAW_CLIENT_PLATFORM", "python")
        self.user_agent = os.getenv("OPENCLAW_USER_AGENT", "backend-agente/1.0.0")

        # Tolerancia a freezes del gateway (event loop bloqueado bajo carga). Ping
        # timeout alto para no soltar la conexión mientras el gateway no responde.
        self.ws_open_timeout = float(os.getenv("OPENCLAW_WS_OPEN_TIMEOUT", "60"))
        self.ws_ping_interval = float(os.getenv("OPENCLAW_WS_PING_INTERVAL", "20"))
        self.ws_ping_timeout = float(os.getenv("OPENCLAW_WS_PING_TIMEOUT", "90"))

        self.min_protocol = int(os.getenv("OPENCLAW_MIN_PROTOCOL", "3"))
        self.max_protocol = int(os.getenv("OPENCLAW_MAX_PROTOCOL", "4"))
        self.requested_scopes = _env_list(
            "OPENCLAW_SCOPES",
            ["operator.read", "operator.write"],
        )

        self.connection = None
        self.running = False
        self.reconnect_delay = 2
        self.is_authenticated = False
        self.connect_req_id: str | None = None
        self.granted_scopes: list[str] | None = None
        self.available_methods: set[str] = set()
        self.pending_ws_chats: dict[str, str] = {}

    @staticmethod
    def _derive_http_base_url(ws_url: str) -> str:
        parsed = urllib.parse.urlparse(ws_url)
        scheme = "https" if parsed.scheme == "wss" else "http"
        return urllib.parse.urlunparse((scheme, parsed.netloc, "", "", "", ""))

    def _shared_secret(self) -> str | None:
        token = os.getenv("OPENCLAW_GATEWAY_TOKEN", "").strip()
        password = os.getenv("OPENCLAW_GATEWAY_PASSWORD", "").strip()

        if token and token != "__OPENCLAW_REDACTED__":
            return token
        if password:
            return password
        return None

    def _auth_payload(self) -> dict | None:
        token = os.getenv("OPENCLAW_GATEWAY_TOKEN", "").strip()
        password = os.getenv("OPENCLAW_GATEWAY_PASSWORD", "").strip()

        if token and token != "__OPENCLAW_REDACTED__":
            return {"token": token}

        if password:
            return {"password": password}

        return None

    async def start(self):
        self.running = True

        while self.running:
            try:
                print(f"[OpenClaw] Connecting to {self.uri}...")

                # El gateway corre el agente (gpt-5.4) en el mismo event loop de Node
                # y, con Whisper saturando la CPU, llega a congelarse ~60s (visto en
                # liveness warning: eventLoopDelayMaxMs≈60000). Con los defaults de
                # websockets (ping_timeout=20, open_timeout=10) el cliente suelta la
                # conexión en pleno freeze y el run se pierde. Subimos los timeouts
                # para sobrevivir el bloqueo y recibir la respuesta del agente.
                async with ws_client.connect(
                    self.uri,
                    open_timeout=self.ws_open_timeout,
                    ping_interval=self.ws_ping_interval,
                    ping_timeout=self.ws_ping_timeout,
                    close_timeout=10,
                    max_size=None,
                ) as websocket:
                    self.connection = websocket
                    self.is_authenticated = False
                    self.granted_scopes = None
                    self.available_methods = set()
                    self.connect_req_id = None
                    self.pending_ws_chats = {}
                    self.reconnect_delay = 2

                    print("[OpenClaw] Connected. Waiting for connect.challenge...")
                    await self._listen()

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[OpenClaw] Connection error: {e}")
            finally:
                self.connection = None
                self.is_authenticated = False
                self.granted_scopes = None
                self.available_methods = set()

            if self.running:
                print(f"[OpenClaw] Reconnecting in {self.reconnect_delay} seconds...")
                await asyncio.sleep(self.reconnect_delay)
                self.reconnect_delay = min(self.reconnect_delay * 2, 30)

    async def stop(self):
        self.running = False

        if self.connection:
            await self.connection.close()

    async def _send_handshake(self, nonce: str, ts: int):
        auth = self._auth_payload()

        if not auth:
            print(
                "[OpenClaw] Missing auth. Define OPENCLAW_GATEWAY_TOKEN "
                "or OPENCLAW_GATEWAY_PASSWORD. Do not use __OPENCLAW_REDACTED__."
            )
            if self.connection:
                await self.connection.close()
            return

        self.connect_req_id = str(uuid.uuid4())

        msg = {
            "type": "req",
            "id": self.connect_req_id,
            "method": "connect",
            "params": {
                "minProtocol": self.min_protocol,
                "maxProtocol": self.max_protocol,
                "client": {
                    "id": self.client_id,
                    "version": "1.0.0",
                    "platform": self.client_platform,
                    "mode": self.client_mode,
                },
                "role": "operator",
                "scopes": self.requested_scopes,
                "caps": [],
                "commands": [],
                "permissions": {},
                "auth": auth,
                "locale": "es-ES",
                "userAgent": self.user_agent,
                # Direct loopback gateway-client/backend shared-secret flows may omit device.
                # The server still sends connect.challenge; we wait for it before connect.
                # Do not add fake device/signature fields here.
            },
        }

        await self._send_raw(msg)
        print(f"[OpenClaw] Handshake sent: {self.connect_req_id}")
        print(f"[OpenClaw] Requested scopes: {self.requested_scopes}")

    async def send_chat(self, text: str):
        text = text.strip()

        if not text:
            return

        if self.send_mode == "http":
            await self._send_chat_http(text)
            return

        if not self.connection or not self.is_authenticated:
            print("[OpenClaw] Cannot send chat: not connected or not authenticated.")

            if self.send_mode == "auto":
                print("[OpenClaw] Trying HTTP fallback because WS is not ready.")
                await self._send_chat_http(text)
            return

        # Some OpenClaw builds authenticate successfully but still reject chat.send
        # with missing scope: operator.write. In auto mode we try WS first, then
        # fall back to the documented HTTP compatibility endpoint if that happens.
        if self.granted_scopes is not None and "operator.write" not in self.granted_scopes:
            print(
                "[OpenClaw] Warning: hello-ok.auth.scopes did not include operator.write. "
                f"Scopes reported by gateway: {self.granted_scopes}. Trying chat.send anyway."
            )

        if self.available_methods and "chat.send" not in self.available_methods:
            print(
                "[OpenClaw] Warning: chat.send was not advertised in hello-ok.features.methods. "
                "Trying anyway because the gateway may expose it despite incomplete discovery."
            )

        req_id = str(uuid.uuid4())

        msg = {
            "type": "req",
            "id": req_id,
            "method": "chat.send",
            "params": {
                "sessionKey": self.session_key,
                "message": text,
                "deliver": self.chat_deliver,
                "idempotencyKey": f"voice-{req_id}",
            },
        }

        if self.send_mode == "auto":
            self.pending_ws_chats[req_id] = text

        await self._send_raw(msg)
        print(f"[OpenClaw] Chat sent to {self.session_key}: {text[:40]}...")

    async def _send_chat_http(self, text: str):
        secret = self._shared_secret()

        if not secret:
            error = (
                "No hay token/password para HTTP. Define OPENCLAW_GATEWAY_TOKEN "
                "o OPENCLAW_GATEWAY_PASSWORD."
            )
            print(f"[OpenClaw HTTP] {error}")
            await manager.broadcast_json({"type": "agent_response", "text": error})
            return

        body = {
            "model": self.openclaw_model,
            "messages": [{"role": "user", "content": text}],
            "stream": False,
            # Helps OpenClaw derive stable session behavior in the HTTP surface.
            "user": self.session_key,
        }

        headers = {
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
            "x-openclaw-session-key": self.session_key,
            "x-openclaw-message-channel": "voice",
        }

        print(f"[OpenClaw HTTP] Sending to {self.http_chat_url}: {text[:40]}...")

        try:
            response = await asyncio.to_thread(
                self._post_json_blocking,
                self.http_chat_url,
                body,
                headers,
            )
        except Exception as e:
            error = str(e)
            print(f"[OpenClaw HTTP] Request failed: {error}")

            if "404" in error or "405" in error or "disabled" in error.lower():
                error += (
                    "\n\nActiva el endpoint HTTP de OpenClaw y reinicia el Gateway:\n"
                    "openclaw config set gateway.http.endpoints.chatCompletions.enabled true\n"
                    "openclaw gateway restart"
                )

            await manager.broadcast_json({"type": "agent_response", "text": f"OpenClaw HTTP error: {error}"})
            return

        response_text = self._extract_openai_chat_text(response)

        if response_text:
            print(f"[OpenClaw HTTP] Agent response: {response_text[:80]}...")
            await manager.broadcast_json({"type": "agent_response", "text": response_text})
        else:
            print(f"[OpenClaw HTTP] Response received: {response}")
            await manager.broadcast_json({"type": "agent_response", "text": json.dumps(response, ensure_ascii=False)})

    @staticmethod
    def _post_json_blocking(url: str, body: dict, headers: dict) -> dict:
        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=payload, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {e.code}: {raw}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"URL error: {e.reason}") from e

        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON HTTP response: {raw[:500]}") from e

    @staticmethod
    def _extract_openai_chat_text(response: dict) -> str | None:
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str) and content.strip():
                        return content
                text = first.get("text")
                if isinstance(text, str) and text.strip():
                    return text

        output = response.get("output")
        if isinstance(output, list):
            parts: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict):
                            value = part.get("text") or part.get("content")
                            if isinstance(value, str):
                                parts.append(value)
                elif isinstance(content, str):
                    parts.append(content)
            if parts:
                return "".join(parts).strip()

        for key in ("output_text", "text", "message", "content"):
            value = response.get(key)
            if isinstance(value, str) and value.strip():
                return value

        return None

    async def _send_raw(self, data: dict):
        if not self.connection:
            print("[OpenClaw] Cannot send raw message: no active connection.")
            return

        await self.connection.send(json.dumps(data))

    def _handle_connect_response(self, data: dict):
        if data.get("ok"):
            payload = data.get("payload", {})
            if not isinstance(payload, dict):
                payload = {}

            features = payload.get("features", {})
            if not isinstance(features, dict):
                features = {}

            methods = features.get("methods", [])
            if isinstance(methods, list):
                self.available_methods = {m for m in methods if isinstance(m, str)}
            else:
                self.available_methods = set()

            auth = payload.get("auth")
            if isinstance(auth, dict):
                scopes = auth.get("scopes")
                if isinstance(scopes, list):
                    self.granted_scopes = [s for s in scopes if isinstance(s, str)]
                else:
                    self.granted_scopes = None
            else:
                # Protocol v3 / some builds may omit auth metadata in hello-ok.
                # Omitted metadata is not the same thing as denied scopes.
                self.granted_scopes = None

            self.is_authenticated = True

            print("[OpenClaw] Authenticated successfully.")
            print(f"[OpenClaw] Protocol: {payload.get('protocol')}")
            print(f"[OpenClaw] chat.send advertised: {'chat.send' in self.available_methods}")

            if self.granted_scopes is None:
                print(
                    "[OpenClaw] Gateway did not return hello-ok.auth.scopes; "
                    "continuing because auth succeeded and chat.send availability will be checked by RPC."
                )
            else:
                print(f"[OpenClaw] Granted scopes: {self.granted_scopes}")

        else:
            print(f"[OpenClaw] Authentication failed: {data.get('error')}")
            self.is_authenticated = False

    @staticmethod
    def _extract_chat_event(data: dict) -> tuple[str | None, str | None]:
        """Devuelve (delta, final). Solo uno suele estar presente.
        delta = trozo incremental para streaming a la UI.
        final = texto completo cuando state=='final'."""
        if not (data.get("type") == "event" and data.get("event") == "chat"):
            return None, None
        payload = data.get("payload", {})
        if not isinstance(payload, dict):
            return None, None

        if payload.get("state") == "final":
            message = payload.get("message", {})
            content = message.get("content", [])
            if isinstance(content, list) and content:
                item = content[0]
                if isinstance(item, dict) and item.get("type") == "text":
                    return None, item.get("text")
            # Algunos builds: payload.message.text directo.
            if isinstance(message, dict):
                t = message.get("text")
                if isinstance(t, str) and t.strip():
                    return None, t
            return None, None

        delta = payload.get("delta")
        if isinstance(delta, str) and delta:
            return delta, None
        return None, None

    @staticmethod
    def _extract_response_text(data: dict) -> str | None:
        """
        Best-effort parser para respuestas que NO son event:chat (RPC res, otros eventos).
        """
        if data.get("type") == "event" and data.get("event") == "chat":
            return None  # se maneja en _extract_chat_event

        payload = data.get("payload")
        if not isinstance(payload, dict):
            payload = {}

        # Common event: {"type":"event","event":"chat","payload":{"delta":"..."}}
        for key in ("text", "message", "delta", "content", "final"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value

        # Nested message shapes.
        message = payload.get("message")
        if isinstance(message, dict):
            for key in ("text", "content", "message"):
                value = message.get(key)
                if isinstance(value, str) and value.strip():
                    return value

        # Generic successful response payload.
        result = data.get("result")
        if isinstance(result, dict):
            for key in ("text", "message", "content"):
                value = result.get(key)
                if isinstance(value, str) and value.strip():
                    return value

        params = data.get("params")
        if isinstance(params, dict):
            for key in ("text", "message", "content"):
                value = params.get(key)
                if isinstance(value, str) and value.strip():
                    return value

        return None

    async def _listen(self):
        while self.running and self.connection:
            try:
                message = await self.connection.recv()

                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    print("[OpenClaw] Invalid JSON received.")
                    continue

                msg_type = data.get("type")

                # No imprimas los ticks (llegan ~1/s): inundan stdout y en Windows
                # el flush síncrono de consola arrastra el event loop del WS.
                if not (msg_type == "event" and data.get("event") == "tick"):
                    print(f"[OpenClaw] Received: {message[:300]}")

                if msg_type == "event" and data.get("event") == "connect.challenge":
                    payload = data.get("payload", {})
                    nonce = payload.get("nonce")
                    ts = payload.get("ts", 0)

                    if nonce:
                        await self._send_handshake(nonce, ts)
                    else:
                        print("[OpenClaw] connect.challenge arrived without nonce.")
                    continue

                if msg_type == "res" and data.get("id") == self.connect_req_id:
                    self._handle_connect_response(data)
                    continue

                if msg_type == "res" and not data.get("ok", True):
                    error = data.get("error")
                    print(f"[OpenClaw] RPC failed: {error}")

                    error_message = ""
                    if isinstance(error, dict):
                        error_message = str(error.get("message", ""))

                    request_id = data.get("id")
                    pending_text = self.pending_ws_chats.pop(request_id, None)

                    if (
                        self.send_mode == "auto"
                        and pending_text
                        and "missing scope: operator.write" in error_message
                    ):
                        print(
                            "[OpenClaw] WS chat.send lacks operator.write. "
                            "Falling back to HTTP Chat Completions endpoint."
                        )
                        await self._send_chat_http(pending_text)
                        continue

                    if isinstance(error, dict):
                        await manager.broadcast_json(
                            {
                                "type": "agent_response",
                                "text": f"OpenClaw RPC error: {error_message or error}",
                            }
                        )

                    continue

                if msg_type == "event" and data.get("event") == "tick":
                    continue

                # Streaming: si llega un delta o un final del agente, despacha ya.
                delta, final = self._extract_chat_event(data)
                if delta:
                    await manager.broadcast_json({"type": "agent_delta", "text": delta})
                    continue
                if final is not None:
                    await manager.broadcast_json({"type": "agent_response", "text": final})
                    continue

                response_text = self._extract_response_text(data)
                if response_text:
                    await manager.broadcast_json(
                        {"type": "agent_response", "text": response_text}
                    )

            except asyncio.CancelledError:
                break
            except ws_client.ConnectionClosed:
                print("[OpenClaw] Connection closed by server.")
                break
            except Exception as e:
                print(f"[OpenClaw] Listen error: {e}")
                break


openclaw_client = OpenClawGatewayClient()
AGENT_PROVIDER = os.getenv("AGENT_PROVIDER", "ollama").strip().lower()
if AGENT_PROVIDER not in {"ollama", "openclaw"}:
    raise ValueError("AGENT_PROVIDER debe ser ollama u openclaw")
local_agent = OllamaAgent(
    model=os.getenv("OLLAMA_MODEL", "qwen3.5:4b"),
    base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
    tool_runner=tool_runner,
    mcp_tools=mcp_tools,
)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("SOLOBINO_CLIENT_TOKEN") and AGENT_PROVIDER != "ollama":
        raise RuntimeError("El servicio remoto requiere AGENT_PROVIDER=ollama para ejecutar herramientas en el cliente.")
    if os.getenv("SOLOBINO_HOST", "127.0.0.1") not in {"127.0.0.1", "localhost", "::1"}:
        if not os.getenv("SOLOBINO_CLIENT_TOKEN"):
            raise RuntimeError("SOLOBINO_CLIENT_TOKEN es obligatorio al exponer el servicio en red.")
    openclaw_task = None
    if AGENT_PROVIDER == "openclaw":
        openclaw_task = asyncio.create_task(openclaw_client.start())
    else:
        try:
            await local_agent.warmup()
            print(f"[Ollama] Modelo listo: {local_agent.model}")
        except Exception as e:
            print(f"[Ollama] No se pudo precargar el modelo: {e}")
        # En modo servicio las herramientas pertenecen al cliente instalado.
        if not os.getenv("SOLOBINO_CLIENT_TOKEN"):
            with contextlib.suppress(Exception):
                await asyncio.to_thread(app_index.entries)
            await mcp_tools.start()

    try:
        yield
    finally:
        if openclaw_task is not None:
            await openclaw_client.stop()
            openclaw_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await openclaw_task
        await local_agent.close()
        await tool_runner.close()
        with contextlib.suppress(Exception):
            await mcp_tools.close()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "agent_provider": AGENT_PROVIDER,
            "model": local_agent.model if AGENT_PROVIDER == "ollama" else openclaw_client.openclaw_model}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Local Electron app. Tighten this if you expose it beyond localhost.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Audio Processing ---
def save_audio_chunk(data: bytes) -> str:
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".webm")
    temp_file.write(data)
    temp_file.close()
    return temp_file.name


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    history = []
    local_task = None
    remote_tools = None
    last_wake_ts = 0.0

    def wake_allowed() -> bool:
        nonlocal last_wake_ts
        now = time.monotonic()
        if now - last_wake_ts < WAKE_COOLDOWN_S:
            return False
        last_wake_ts = now
        return True

    client_token = os.getenv("SOLOBINO_CLIENT_TOKEN", "")
    if client_token:
        try:
            async with asyncio.timeout(10):
                hello = await websocket.receive_json()
            if (not isinstance(hello, dict) or hello.get("type") != "client_hello"
                    or not secrets.compare_digest(str(hello.get("token", "")), client_token)):
                await websocket.close(code=1008)
                return
            offered = hello.get("tools")
            if not isinstance(offered, list) or len(offered) > 100:
                await websocket.close(code=1008)
                return
            specs = [spec for spec in offered if isinstance(spec, dict)
                     and isinstance(spec.get("function"), dict)
                     and isinstance(spec["function"].get("name"), str)]
            paths = hello.get("paths")
            paths = [item for item in paths[:10] if isinstance(item, str) and len(item) < 1000] if isinstance(paths, list) else []
            remote_tools = RemoteToolset(websocket, specs, paths)
        except (Exception, asyncio.TimeoutError):
            await websocket.close(code=1008)
            return
    manager.active_connections.append(websocket)
    print("Electron client connected.")

    async def local_command(audio):
        try:
            async with asyncio.timeout(180):
                started = time.perf_counter()
                text = await _transcribe_async(audio, "es")
                print(f"[Voice] STT={time.perf_counter() - started:.3f}s")
                if not text or _is_hallucination(text):
                    await websocket.send_json({"type": "agent_error", "text": "No escuché un comando. Inténtalo de nuevo."})
                    return
                await websocket.send_json({"type": "transcription", "text": text})
                if remote_tools is None:
                    await local_agent.reply(text, history, websocket.send_json)
                else:
                    await local_agent.reply(text, history, websocket.send_json,
                                            remote_tools=remote_tools)
        except WebSocketDisconnect:
            return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[Ollama] Turn failed: {type(e).__name__}: {e}")
            if isinstance(e, (TimeoutError, httpx.TimeoutException)):
                message = "El modelo local tardó demasiado en responder. Inténtalo de nuevo."
            elif isinstance(e, httpx.ConnectError):
                message = "No pude conectar con Ollama. Comprueba que esté iniciado."
            else:
                message = "No pude completar la respuesta local. Revisa el servicio Solobino."
            with contextlib.suppress(Exception):
                await websocket.send_json({"type": "agent_error", "text": message})

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break

            if "bytes" in message and message["bytes"] is not None:
                audio_data = message["bytes"]
                print(f"Received audio chunk: {len(audio_data)} bytes")
                if AGENT_PROVIDER == "ollama":
                    if local_task is None or local_task.done():
                        local_task = asyncio.create_task(local_command(audio_data))
                    continue

                try:
                    # PCM directo: ahorra tempfile + I/O. Pool dedicado de Whisper.
                    text = await _transcribe_async(audio_data, "es")

                    if not text:
                        pass
                    elif _is_hallucination(text):
                        # Whisper alucinó subtítulos de YouTube sobre silencio. No mandes al agente.
                        print(f"[Whisper] Alucinación descartada: {text!r}")
                    else:
                        print(f"[Whisper] Transcribed: {text}")

                        await manager.broadcast_json(
                            {"type": "transcription", "text": text}
                        )

                        await openclaw_client.send_chat(text=text)

                except Exception as e:
                    print(f"Transcription error: {e}")

            elif "text" in message and message["text"] is not None:
                try:
                    data = json.loads(message["text"])
                except json.JSONDecodeError:
                    await manager.broadcast_json(
                        {"type": "agent_response", "text": "Mensaje JSON inválido."}
                    )
                    continue

                if not isinstance(data, dict):
                    continue

                if data.get("type") == "client_hello" and not client_token:
                    offered = data.get("tools")
                    if isinstance(offered, list) and len(offered) <= 100:
                        specs = [spec for spec in offered if isinstance(spec, dict)
                                 and isinstance(spec.get("function"), dict)
                                 and isinstance(spec["function"].get("name"), str)]
                        paths = data.get("paths")
                        paths = [item for item in paths[:10] if isinstance(item, str) and len(item) < 1000] if isinstance(paths, list) else []
                        remote_tools = RemoteToolset(websocket, specs, paths)
                    continue

                if data.get("type") == "tool_result" and remote_tools is not None:
                    remote_tools.resolve(data)
                    continue
                if data.get("type") == "cancel" and AGENT_PROVIDER == "ollama":
                    if local_task and not local_task.done():
                        local_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await local_task
                    continue

                if data.get("type") == "wake_word_check":
                    if local_task and not local_task.done():
                        continue
                    audio_b64 = data.get("audio")
                    if not audio_b64:
                        continue

                    candidate_id = data.get("candidate_id")
                    if not isinstance(candidate_id, str) or len(candidate_id) > 64:
                        candidate_id = None
                    async def reject_candidate() -> None:
                        if candidate_id:
                            await websocket.send_json({"type": "wake_word_rejected",
                                                       "candidate_id": candidate_id})

                    audio_bytes = base64.b64decode(audio_b64)

                    # Gate de energía: si no hay voz audible, no transcribimos ni
                    # inferimos. Evita falsos positivos por alucinación de Whisper
                    # sobre silencio y carga inútil de CPU/GPU.
                    if not _segment_has_voice(audio_bytes):
                        await reject_candidate()
                        continue

                    if wake_detector.available and WAKEWORD_USE_CNN:
                        # Detector neuronal propio (CNN -> ONNX). ONNX también es CPU bound.
                        try:
                            detected, prob = await asyncio.to_thread(
                                wake_detector.is_wake, audio_bytes
                            )
                            print(f"[WakeWord-CNN] prob={prob:.3f} (umbral={wake_detector.threshold:.3f})")
                            if not detected:
                                await reject_candidate()
                                continue
                            # Doble check: la CNN puede tener falsos positivos por
                            # overfit del dataset pequeño. Antes de notificar al frontend,
                            # transcribe con Whisper y confirma que sí dijo "solobino".
                            if WAKEWORD_REQUIRE_STT_CONFIRM:
                                try:
                                    text = await _transcribe_async(audio_bytes, "es", hotwords=WAKE_HOTWORD)
                                except Exception as e:
                                    print(f"[WakeWord-CNN] STT confirm error: {e}")
                                    text = ""
                                norm = _normalize_text(text) if text else ""
                                if _is_hallucination(text) or not _is_wake_word(text):
                                    print(f"[WakeWord-CNN] Rechazado por STT (prob={prob:.3f}, heard={norm!r})")
                                    await reject_candidate()
                                    continue
                                print(f"[WakeWord-CNN] Confirmado por STT: {text!r}")

                            if not wake_allowed():
                                await reject_candidate()
                                continue
                            print(f"[WakeWord-CNN] Detected (prob={prob:.3f})")
                            await websocket.send_json({"type": "wake_word_detected",
                                                       "candidate_id": candidate_id})
                        except Exception as e:
                            print(f"Wake word (CNN) error: {e}")
                    else:
                        # Detector principal (o fallback si la CNN está apagada/ausente):
                        # Whisper + regex (PCM directo, sin tempfile).
                        try:
                            text = await _transcribe_async(audio_bytes, "es", hotwords=WAKE_HOTWORD)
                            if text:
                                print(f"[WakeWord] Heard: {text!r} -> norm: {_normalize_text(text)!r}")
                            if _is_hallucination(text):
                                await reject_candidate()
                                continue
                            if _is_wake_word(text) and wake_allowed():
                                print(f"[WakeWord] Detected: {text}")
                                await websocket.send_json({"type": "wake_word_detected",
                                                           "candidate_id": candidate_id})
                            else:
                                await reject_candidate()
                        except Exception as e:
                            print(f"Wake word error: {e}")

                # Fallback for manual agentic commands from UI directly.
                elif data.get("action") == "control_pc":
                    # Pasa por la misma validación que las herramientas del modelo.
                    executor = remote_tools.call if remote_tools is not None else tool_runner.run
                    result = await executor(
                        data.get("command"),
                        data.get("params", {}),
                    )
                    await websocket.send_json(
                        {"type": "agent_response", "text": result}
                    )

    except WebSocketDisconnect:
        print("Electron client disconnected.")
        manager.disconnect(websocket)

    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(websocket)
    finally:
        if remote_tools is not None:
            remote_tools.close()
        if local_task and not local_task.done():
            local_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await local_task
        manager.disconnect(websocket)


if __name__ == "__main__":
    # ws_ping_timeout alto: el handler puede tardar varios segundos en transcribir
    # (Whisper) o llamar a OpenClaw (HTTP). Aunque to_thread libera el loop, dejamos
    # margen para evitar cierres por ping perdido en redes lentas.
    uvicorn.run(
        app,
        host=os.getenv("SOLOBINO_HOST", "127.0.0.1"),
        port=int(os.getenv("SOLOBINO_PORT", "8000")),
        ws_ping_interval=20,
        ws_ping_timeout=60,
    )
