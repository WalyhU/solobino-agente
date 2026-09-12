"""Pulsar controles de una aplicación por su nombre accesible (UI Automation).

Alternativa determinista a mirar la pantalla: se localiza el botón en el árbol de
accesibilidad de la ventana, sin coordenadas ni capturas. Si no existe, se
devuelven los nombres disponibles para que el modelo reintente con uno real.
"""
import asyncio
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

IS_MACOS = sys.platform == "darwin"
if IS_MACOS:
    import mac_desktop
else:
    mac_desktop = None

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ui-invoke.ps1"
DEFAULT_TIMEOUT_S = 18


@dataclass(frozen=True)
class ClickResult:
    ok: bool
    detail: str
    available: list[str]


def _parse(output: str) -> ClickResult:
    text = output.strip()
    if text.startswith("OK:"):
        return ClickResult(True, text[3:].strip(), [])
    if text.startswith("NOTFOUND:"):
        names = [n.strip() for n in text[len("NOTFOUND:"):].split("|") if n.strip()]
        return ClickResult(False, "no encontré ese control", names)
    if text.startswith("NOWINDOW"):
        return ClickResult(False, "la aplicación no tiene una ventana abierta", [])
    return ClickResult(False, text or "sin respuesta de UI Automation", [])


async def click_control(window: str, controls: list[str], *,
                        timeout_s: int = DEFAULT_TIMEOUT_S) -> ClickResult:
    """`window` casa con el nombre de proceso o el título; `controls` son alternativas."""
    if IS_MACOS:
        ok, detail, available = await mac_desktop.click_control(window, controls)
        return ClickResult(ok, detail, available)
    if not SCRIPT.is_file():
        return ClickResult(False, f"falta {SCRIPT.name}", [])
    command = [
        "powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(SCRIPT),
        "-Window", window, "-Control", ",".join(controls),
        "-TimeoutSeconds", str(timeout_s),
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout_s + 10)
    except (OSError, asyncio.TimeoutError) as e:
        return ClickResult(False, f"no se pudo consultar la interfaz: {e}", [])
    return _parse(stdout.decode("utf-8", errors="replace"))
