"""Acciones de escritorio en macOS.

Equivalentes de lo que en Windows hacen `Get-StartApps`, `shell:AppsFolder` y UI
Automation:

| Capacidad | Windows | macOS |
|---|---|---|
| descubrir apps | `Get-StartApps` + PATH | paquetes `.app` de las carpetas de aplicaciones |
| abrir app | `explorer.exe shell:AppsFolder\\…` | `open -a` |
| abrir archivo con app | `Popen([exe, ruta])` | `open -a <app> <ruta>` |
| pulsar un botón | UI Automation | `System Events` por accesibilidad |
| reproducir música | enlace `musics:` + botón | AppleScript sobre Music.app |

Igual que en Windows, el texto del modelo solo **selecciona** una entrada ya
descubierta: nunca se construye una línea de comandos con lo que dijo.
"""
import asyncio
import json
import plistlib
import subprocess
from pathlib import Path

APP_DIRECTORIES = (
    "/Applications",
    "/Applications/Utilities",
    "/System/Applications",
    "/System/Applications/Utilities",
    "~/Applications",
)
OSASCRIPT_TIMEOUT_S = 20
MUSIC_APP = "Music"


def _app_label(bundle: Path) -> str:
    """Nombre visible del paquete, que es el que diría una persona."""
    info = bundle / "Contents" / "Info.plist"
    try:
        with info.open("rb") as handle:
            data = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException):
        return bundle.stem
    return data.get("CFBundleDisplayName") or data.get("CFBundleName") or bundle.stem


def discover_apps() -> list[tuple[str, str]]:
    """Devuelve (nombre visible, ruta del .app) de las aplicaciones instaladas."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for directory in APP_DIRECTORIES:
        root = Path(directory).expanduser()
        if not root.is_dir():
            continue
        try:
            children = sorted(root.iterdir())
        except OSError:
            continue
        for bundle in children:
            if bundle.suffix != ".app" or str(bundle) in seen:
                continue
            seen.add(str(bundle))
            found.append((_app_label(bundle), str(bundle)))
    return found


def launch(app_path: str) -> None:
    """`open -a` no interpreta la ruta como comando: la abre como aplicación."""
    subprocess.Popen(["open", "-a", app_path], shell=False, close_fds=True)


def open_file_with(app_path: str, path: str) -> None:
    """En macOS el mismo `open -a` sirve para archivos y para carpetas."""
    subprocess.Popen(["open", "-a", app_path, path], shell=False, close_fds=True)


def open_path(path: str) -> None:
    subprocess.Popen(["open", path], shell=False, close_fds=True)


def open_deep_link(url: str) -> None:
    subprocess.Popen(["open", url], shell=False, close_fds=True)


async def _osascript(script: str, *args: str, timeout_s: int = OSASCRIPT_TIMEOUT_S) -> tuple[int, str]:
    """Ejecuta AppleScript. El script es fijo; lo variable entra como argumento."""
    command = ["osascript", "-", *args]
    try:
        process = await asyncio.create_subprocess_exec(
            *command, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(
            process.communicate(script.encode("utf-8")), timeout=timeout_s)
    except (OSError, asyncio.TimeoutError) as e:
        return 1, f"no se pudo ejecutar AppleScript: {e}"
    output = stdout.decode("utf-8", errors="replace").strip()
    error = stderr.decode("utf-8", errors="replace").strip()
    return process.returncode, output or error


# `argv` mantiene el nombre del proceso y del botón fuera del texto del script.
_CLICK_SCRIPT = """
on run argv
  set processName to item 1 of argv
  set wanted to items 2 thru -1 of argv
  tell application "System Events"
    if not (exists process processName) then return "NOWINDOW"
    tell process processName
      set available to {}
      repeat with theWindow in windows
        repeat with theButton in (every button of theWindow)
          try
            set buttonName to name of theButton
            if buttonName is not missing value then
              set end of available to buttonName
              repeat with target in wanted
                if buttonName is (target as text) then
                  click theButton
                  return "OK: " & buttonName
                end if
              end repeat
            end if
          end try
        end repeat
      end repeat
    end tell
    return "NOTFOUND: " & (available as text)
  end tell
end run
"""

_TYPE_SCRIPT = """
on run argv
  tell application "System Events" to keystroke (item 1 of argv)
end run
"""

_KEY_SCRIPT = """
on run argv
  set keyName to item 1 of argv
  set modifiers to items 2 thru -1 of argv
  tell application "System Events"
    if (count of modifiers) is 0 then
      key code (keyName as integer)
    else
      keystroke keyName using modifiers
    end if
  end tell
end run
"""

# Códigos de tecla de macOS para las teclas sin carácter imprimible.
KEY_CODES = {
    "enter": 36, "escape": 53, "tab": 48, "space": 49, "backspace": 51,
    "delete": 117, "up": 126, "down": 125, "left": 123, "right": 124,
    "home": 115, "end": 119, "pageup": 116, "pagedown": 121, "f5": 96,
    "volumeup": 72, "volumedown": 73, "volumemute": 74,
}
# Equivalencias de los atajos: en macOS la tecla de comando sustituye a Ctrl.
MODIFIER_NAMES = {
    "ctrl": "command down", "cmd": "command down", "win": "command down",
    "alt": "option down", "shift": "shift down",
}
MEDIA_SCRIPTS = {
    "reproducir": 'tell application "Music" to play',
    "pausar": 'tell application "Music" to pause',
    "siguiente": 'tell application "Music" to next track',
    "anterior": 'tell application "Music" to previous track',
}


async def click_control(process_name: str, controls: list[str]) -> tuple[bool, str, list[str]]:
    """Devuelve (pulsado, detalle, botones disponibles)."""
    code, output = await _osascript(_CLICK_SCRIPT, process_name, *controls)
    if output.startswith("OK:"):
        return True, output[3:].strip(), []
    if output.startswith("NOTFOUND:"):
        names = [n.strip() for n in output[len("NOTFOUND:"):].split(",") if n.strip()]
        return False, "no encontré ese control", names
    if output.startswith("NOWINDOW"):
        return False, "la aplicación no tiene una ventana abierta", []
    if "not allowed assistive access" in output or "1743" in output:
        return False, ("falta el permiso de accesibilidad: Ajustes del Sistema → "
                       "Privacidad y seguridad → Accesibilidad"), []
    return False, output or f"AppleScript terminó con código {code}", []


async def type_text(text: str) -> None:
    await _osascript(_TYPE_SCRIPT, text)


async def press_key(key: str) -> None:
    """`key` ya viene validado por `tools.validate`."""
    if "+" in key:
        *modifiers, base = key.split("+")
        names = [MODIFIER_NAMES[m] for m in modifiers if m in MODIFIER_NAMES]
        await _osascript(_KEY_SCRIPT, base, *names)
        return
    code = KEY_CODES.get(key)
    if code is None:
        await _osascript(_TYPE_SCRIPT, key)
        return
    await _osascript(_KEY_SCRIPT, str(code))


async def media_control(action: str) -> bool:
    """Controla Music.app directamente; más fiable que buscar su botón."""
    script = MEDIA_SCRIPTS.get(action)
    if script is None:
        return False
    code, _ = await _osascript(script)
    return code == 0


_PLAY_URL_SCRIPT = """
on run argv
  do shell script "open " & quoted form of (item 1 of argv)
  delay 4
  tell application "Music" to play
end run
"""


async def play_deep_link(url: str) -> bool:
    """Abre la ficha del álbum en Music.app y la pone a sonar."""
    code, _ = await _osascript(_PLAY_URL_SCRIPT, url, timeout_s=30)
    return code == 0
