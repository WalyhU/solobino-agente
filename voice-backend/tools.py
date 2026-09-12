"""Catálogo de herramientas del agente local.

Capa de validación entre el modelo y `PCController`: el modelo solo puede pedir
acciones de esta lista, con argumentos comprobados contra una lista blanca.
Nunca se construye una línea de comandos a partir del texto del modelo.
"""
import asyncio
import sys
import webbrowser
from pathlib import Path

import httpx

import ui_automation
from agentic_control import PCController, app_index
from music_search import find_release

MAX_TOOL_ROUNDS = 3
MAX_TEXT_CHARS = 500

# Teclas y atajos permitidos. Cualquier otra combinación se rechaza.
KEY_ALLOWLIST = {
    "enter", "escape", "tab", "space", "backspace", "delete",
    "up", "down", "left", "right", "home", "end", "pageup", "pagedown",
    "f5", "volumeup", "volumedown", "volumemute",
}
HOTKEY_ALLOWLIST = {
    "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z", "ctrl+s", "ctrl+a",
    "ctrl+f", "ctrl+w", "ctrl+t", "alt+tab", "win+d", "win+e",
}
IS_MACOS = sys.platform == "darwin"
if IS_MACOS:
    import mac_desktop
else:
    mac_desktop = None

MUSIC_SCOPES = ("latest_album", "album", "song")
# Nombre del proceso del reproductor, distinto en cada sistema.
MUSIC_PROCESS = "Music" if IS_MACOS else "AppleMusic"
MAX_CONTROL_CHARS = 60
# El nombre del botón cambia con el idioma de la aplicación.
PLAY_CONTROLS = ["Reproducir", "Play"]
MEDIA_ACTIONS = {
    "reproducir": (["Reproducir", "Play"], "playpause"),
    "pausar": (["Pausar", "Pausa", "Pause"], "playpause"),
    "siguiente": (["Adelantar", "Siguiente", "Next"], "nexttrack"),
    "anterior": (["Retroceder", "Anterior", "Previous"], "prevtrack"),
}

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "open_application",
            "description": ("Abre una aplicación instalada en el PC. Usa el nombre tal "
                            "como aparece en el Menú Inicio, por ejemplo «Calculadora» "
                            "o «Google Chrome»."),
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "Nombre de la aplicación instalada",
                    }
                },
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_url",
            "description": "Abre una página web en el navegador predeterminado.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL http o https completa"}
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": "Escribe texto con el teclado en la ventana activa.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Texto a escribir"}
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "press_key",
            "description": "Pulsa una tecla o un atajo permitido, por ejemplo enter o ctrl+c.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Tecla o atajo",
                        "enum": sorted(KEY_ALLOWLIST | HOTKEY_ALLOWLIST),
                    }
                },
                "required": ["key"],
            },
        },
    },
]

TOOL_SPECS += [
    {
        "type": "function",
        "function": {
            "name": "play_music",
            "description": ("Reproduce música en Apple Music. Busca el álbum o la "
                            "canción en el catálogo real y le da a reproducir."),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": ("Artista, álbum o canción. Para «el álbum más "
                                        "reciente de X» pon solo el nombre del artista."),
                    },
                    "scope": {
                        "type": "string",
                        "description": ("latest_album para el disco más nuevo del "
                                        "artista, album para uno concreto, song para "
                                        "una canción."),
                        "enum": list(MUSIC_SCOPES),
                    },
                },
                "required": ["query", "scope"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "media_control",
            "description": "Controla la reproducción en curso del reproductor activo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": sorted(MEDIA_ACTIONS),
                    }
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_file_with",
            "description": ("Abre un archivo o una carpeta que ya existen con una "
                            "aplicación concreta. Para trabajar en un proyecto en "
                            "Visual Studio Code pasa la carpeta, no cada archivo."),
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "Aplicación instalada"},
                    "path": {"type": "string",
                             "description": "Ruta absoluta del archivo o de la carpeta"},
                },
                "required": ["app_name", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_path",
            "description": ("Abre un archivo o carpeta con el programa "
                            "predeterminado de Windows, por ejemplo un .html en el "
                            "navegador o una carpeta en el explorador."),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta absoluta"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click_in_app",
            "description": ("Pulsa un botón de una aplicación ya abierta usando su "
                            "nombre visible, por ejemplo «Reproducir» o «Guardar». "
                            "Úsalo para actuar dentro de una app, no para abrirla."),
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "Aplicación abierta"},
                    "control_name": {"type": "string",
                                     "description": "Texto del botón tal como se ve"},
                },
                "required": ["app_name", "control_name"],
            },
        },
    },
]

TOOL_NAMES = {spec["function"]["name"] for spec in TOOL_SPECS}


class ToolError(ValueError):
    """Argumentos inválidos: se devuelve al modelo, nunca se ejecuta la acción."""


def _require_str(args: dict, key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"Falta el argumento «{key}».")
    return value.strip()


def validate(name: str, args: object) -> dict:
    """Normaliza los argumentos del modelo o lanza ToolError."""
    if name not in TOOL_NAMES:
        raise ToolError(f"Herramienta desconocida: {name}.")
    if not isinstance(args, dict):
        raise ToolError("Los argumentos deben ser un objeto JSON.")

    if name == "open_application":
        requested = _require_str(args, "app_name")
        entry = app_index.resolve(requested)
        if entry is None:
            suggestions = ", ".join(app_index.suggestions(requested))
            raise ToolError(
                f"No encontré «{requested}» instalada. Parecidas: {suggestions}."
            )
        # Se devuelve la entrada del índice, no el texto del modelo.
        return {"entry": entry}

    if name == "open_url":
        url = _require_str(args, "url")
        if not url.lower().startswith(("http://", "https://")):
            raise ToolError("La URL debe empezar por http:// o https://.")
        if any(c in url for c in " \t\r\n\"'"):
            raise ToolError("La URL contiene caracteres no válidos.")
        return {"url": url}

    if name == "type_text":
        text = _require_str(args, "text")
        if len(text) > MAX_TEXT_CHARS:
            raise ToolError(f"El texto supera {MAX_TEXT_CHARS} caracteres.")
        return {"text": text}

    if name == "play_music":
        scope = _require_str(args, "scope").lower()
        if scope not in MUSIC_SCOPES:
            raise ToolError(f"scope debe ser uno de: {', '.join(MUSIC_SCOPES)}.")
        return {"query": _require_str(args, "query")[:120], "scope": scope}

    if name == "media_control":
        action = _require_str(args, "action").lower()
        if action not in MEDIA_ACTIONS:
            raise ToolError(f"action debe ser uno de: {', '.join(sorted(MEDIA_ACTIONS))}.")
        return {"action": action}

    if name == "open_path":
        path = Path(_require_str(args, "path")).expanduser()
        if not path.exists():
            raise ToolError(f"No existe «{path}».")
        return {"path": str(path)}

    if name == "open_file_with":
        path = Path(_require_str(args, "path")).expanduser()
        if not path.exists():
            raise ToolError(f"No existe «{path}».")
        requested = _require_str(args, "app_name")
        entry = app_index.resolve(requested)
        if entry is None:
            raise ToolError(f"No encontré «{requested}» instalada.")
        if not entry.executable:
            raise ToolError(
                f"No puedo abrir archivos con {entry.label}; usa open_path "
                "para abrirlo con el programa predeterminado.")
        return {"entry": entry, "path": str(path)}

    if name == "click_in_app":
        control = _require_str(args, "control_name")
        if len(control) > MAX_CONTROL_CHARS:
            raise ToolError(f"El nombre del botón supera {MAX_CONTROL_CHARS} caracteres.")
        return {"app_name": _require_str(args, "app_name"), "control_name": control}

    key = _require_str(args, "key").lower().replace(" ", "")
    if key not in KEY_ALLOWLIST and key not in HOTKEY_ALLOWLIST:
        raise ToolError(f"La tecla «{key}» no está permitida.")
    return {"key": key}


class ToolRunner:
    """Ejecuta las acciones validadas fuera del event loop (pyautogui bloquea)."""

    def __init__(self, controller: PCController | None = None, *,
                 http: httpx.AsyncClient | None = None):
        self.controller = controller or PCController()
        self.http = http or httpx.AsyncClient()

    async def close(self) -> None:
        await self.http.aclose()

    def _run_sync(self, name: str, args: dict) -> str:
        if name == "open_file_with":
            self.controller.open_file_with(args["entry"], args["path"])
            target = Path(args["path"])
            kind = "la carpeta" if target.is_dir() else ""
            return f"Abrí {kind} {target.name} en {args['entry'].label}.".replace("  ", " ")
        if name == "open_path":
            self.controller.open_path(args["path"])
            return f"Abrí {Path(args['path']).name} con el programa predeterminado."
        if name == "open_url":
            webbrowser.open(args["url"], new=2)
            return f"Abrí {args['url']} en el navegador."
        return self.controller.execute_command(name, args)

    async def _play_music(self, args: dict) -> str:
        release = await find_release(args["query"], args["scope"], self.http)
        if release is None:
            return f"Error: no encontré «{args['query']}» en el catálogo de Apple Music."
        summary = f"«{release.label}» de {release.artist} ({release.year})"
        if IS_MACOS:
            # Music.app se controla por AppleScript: no hace falta buscar el botón.
            if await mac_desktop.play_deep_link(release.app_url):
                return f"Reproduciendo {summary}."
            return (f"Abrí {summary} en Music, pero no pude darle a reproducir "
                    "(revisa el permiso de accesibilidad).")
        # El enlace musics: abre la ficha en la app; el botón la pone a sonar.
        await asyncio.to_thread(self.controller.open_deep_link, release.app_url)
        clicked = await ui_automation.click_control(MUSIC_PROCESS, PLAY_CONTROLS)
        if clicked.ok:
            return f"Reproduciendo {summary}."
        return (f"Abrí {summary} en Apple Music, pero no pude darle a reproducir "
                f"({clicked.detail}).")

    async def _media_control(self, args: dict) -> str:
        controls, media_key = MEDIA_ACTIONS[args["action"]]
        if IS_MACOS:
            if await mac_desktop.media_control(args["action"]):
                return f"Hecho: {args['action']}."
            return f"Error: no pude {args['action']} en Music."
        clicked = await ui_automation.click_control(MUSIC_PROCESS, controls, timeout_s=4)
        if clicked.ok:
            return f"Hecho: {args['action']}."
        # Sin ventana de Apple Music se usa la tecla multimedia del sistema.
        await asyncio.to_thread(self.controller.press_media_key, media_key)
        return f"Hecho: {args['action']} (tecla multimedia)."

    async def _click_in_app(self, args: dict) -> str:
        clicked = await ui_automation.click_control(args["app_name"], [args["control_name"]])
        if clicked.ok:
            return f"Pulsé «{clicked.detail}» en {args['app_name']}."
        if clicked.available:
            options = ", ".join(clicked.available[:10])
            return (f"Error: no vi «{args['control_name']}» en {args['app_name']}. "
                    f"Botones disponibles: {options}.")
        return f"Error: {clicked.detail}."

    async def run(self, name: str, raw_args: object) -> str:
        """Devuelve siempre texto para el modelo; los errores no interrumpen el turno."""
        try:
            args = validate(name, raw_args)
        except ToolError as e:
            return f"Error: {e}"
        handlers = {
            "play_music": self._play_music,
            "media_control": self._media_control,
            "click_in_app": self._click_in_app,
        }
        try:
            handler = handlers.get(name)
            if handler is not None:
                return await handler(args)
            return await asyncio.to_thread(self._run_sync, name, args)
        except Exception as e:  # la acción falló en el PC, no en la validación
            return f"Error al ejecutar {name}: {type(e).__name__}: {e}"
