"""Índice de aplicaciones instaladas.

Resuelve el nombre que pide el modelo contra lo que existe en el equipo. En
Windows: la lista del Menú Inicio (`Get-StartApps`, incluye apps UWP) y los
ejecutables del PATH. En macOS: los paquetes `.app` (ver `mac_desktop.py`).
El modelo nunca aporta una ruta ni una línea de comandos: solo elige una entrada
ya descubierta aquí, y el lanzamiento usa esa entrada, no su texto.
"""
import difflib
import json
import os
import shutil
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

if sys.platform == "darwin":
    import mac_desktop
else:
    mac_desktop = None

IS_MACOS = sys.platform == "darwin"
INDEX_TTL_S = 300
FUZZY_CUTOFF = 0.85
MAX_SUGGESTIONS = 8

# Aplicaciones que no deben abrirse por voz aunque estén instaladas.
DENY_KEYWORDS = (
    "uninstall", "desinstal", "regedit", "registry", "powershell", "cmd",
    "command prompt", "simbolo del sistema", "administrador de tareas",
    "task manager", "directiva", "group policy", "configuracion del sistema",
    # Equivalentes en macOS.
    "terminal", "iterm", "keychain access", "acceso a llaveros", "disk utility",
    "utilidad de discos", "activity monitor", "monitor de actividad",
)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text.casefold())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(text.replace("_", " ").replace("-", " ").split())


@dataclass(frozen=True)
class AppEntry:
    """`kind` decide cómo se lanza: por AppID del Menú Inicio o por ruta."""
    label: str
    kind: str  # "appid" | "path"
    target: str
    from_start_menu: bool
    # Ejecutable real, cuando se conoce. Es lo único que admite argumentos, así
    # que sin él no se puede abrir un archivo *con* esta aplicación.
    executable: str | None = None


def _shortcut_targets() -> dict[str, str]:
    """Nombre del acceso directo -> ejecutable al que apunta.

    `Get-StartApps` da el AppID, que sirve para abrir la aplicación pero no acepta
    argumentos. El destino del `.lnk` sí, y es lo que permite abrir un archivo con
    una aplicación concreta en vez de con la predeterminada.
    """
    if os.name != "nt":
        return {}
    script = r"""
$shell = New-Object -ComObject WScript.Shell
$roots = @("$env:APPDATA\Microsoft\Windows\Start Menu\Programs",
           "$env:ProgramData\Microsoft\Windows\Start Menu\Programs")
Get-ChildItem -Path $roots -Filter *.lnk -Recurse -ErrorAction SilentlyContinue |
  ForEach-Object {
    $link = $shell.CreateShortcut($_.FullName)
    if ($link.TargetPath -and $link.TargetPath -like "*.exe") {
      [pscustomobject]@{ Name = $_.BaseName; Target = $link.TargetPath }
    }
  } | ConvertTo-Json -Compress
"""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=60, shell=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"[AppIndex] no se pudieron leer los accesos directos: {e}", flush=True)
        return {}
    if result.returncode != 0 or not result.stdout.strip():
        return {}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        data = [data]
    targets = {}
    for item in data:
        name, target = item.get("Name"), item.get("Target")
        if name and target:
            targets.setdefault(normalize(name), target)
    return targets


def _registered_executables() -> dict[str, str]:
    """`App Paths` del registro: nombre de ejecutable -> ruta real.

    Repara los accesos directos que apuntan a una versión anterior, como pasa con
    Chrome tras una actualización.
    """
    if os.name != "nt":
        return {}
    script = r"""
$keys = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths'
Get-ChildItem -Path $keys -ErrorAction SilentlyContinue | ForEach-Object {
  $value = (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).'(default)'
  if ($value) { [pscustomobject]@{ Name = $_.PSChildName; Target = $value.Trim('"') } }
} | ConvertTo-Json -Compress
"""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=30, shell=False)
        data = json.loads(result.stdout or "[]")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return {}
    if isinstance(data, dict):
        data = [data]
    found = {}
    for item in data:
        name, target = item.get("Name"), item.get("Target")
        if name and target and Path(target).is_file():
            found.setdefault(name.lower(), target)
    return found


def _start_apps() -> list[AppEntry]:
    """Lista del Menú Inicio, igual que la ve el usuario. Incluye apps UWP."""
    if os.name != "nt":
        return []
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "Get-StartApps | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=30, shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"[AppIndex] Get-StartApps no disponible: {e}", flush=True)
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    entries = []
    for item in data:
        name, app_id = item.get("Name"), item.get("AppID")
        if name and app_id:
            entries.append(AppEntry(name, "appid", app_id, True))
    return entries


def _path_executables() -> list[AppEntry]:
    """Ejecutables del PATH: cubre herramientas sin entrada en el Menú Inicio."""
    entries = []
    seen = set()
    for raw in os.environ.get("PATH", "").split(os.pathsep):
        directory = Path(raw.strip('"')) if raw.strip() else None
        if directory is None or not directory.is_dir():
            continue
        try:
            children = list(directory.iterdir())
        except OSError:
            continue
        for child in children:
            if child.suffix.lower() not in (".exe", ".cmd", ".bat"):
                continue
            key = normalize(child.stem)
            if key and key not in seen:
                seen.add(key)
                entries.append(AppEntry(child.stem, "path", str(child), False, str(child)))
    return entries


class AppIndex:
    """Catálogo de nombre normalizado -> AppEntry. Se refresca por TTL."""

    def __init__(self, ttl_s: float = INDEX_TTL_S):
        self.ttl_s = ttl_s
        self._entries: dict[str, AppEntry] = {}
        self._built_at = 0.0

    @staticmethod
    def _denied(name: str) -> bool:
        return any(keyword in name for keyword in DENY_KEYWORDS)

    def _build(self) -> dict[str, AppEntry]:
        if IS_MACOS:
            return self._build_macos()
        return self._build_windows()

    def _build_macos(self) -> dict[str, AppEntry]:
        """En macOS el propio paquete `.app` es lo que se abre y lo que acepta
        argumentos, así que `target` y `executable` coinciden."""
        catalog: dict[str, AppEntry] = {}
        for label, bundle in mac_desktop.discover_apps():
            key = normalize(label)
            if key and key not in catalog and not self._denied(key):
                catalog[key] = AppEntry(label, "bundle", bundle, True, bundle)
        return catalog

    def _build_windows(self) -> dict[str, AppEntry]:
        catalog: dict[str, AppEntry] = {}
        # El Menú Inicio va primero: sus nombres son los que diría una persona.
        for entry in _start_apps() + _path_executables():
            key = normalize(entry.label)
            if key and key not in catalog and not self._denied(key):
                catalog[key] = entry
        shortcuts = _shortcut_targets()
        registered = _registered_executables()
        orphaned: list[str] = []
        for key, entry in catalog.items():
            if entry.executable:
                continue
            target = shortcuts.get(key)
            if target is None:
                continue
            if not Path(target).is_file():
                # El acceso directo apunta a una versión que ya no está: se busca
                # la ruta registrada para ese ejecutable.
                target = registered.get(Path(target).name.lower()) or shutil.which(Path(target).name)
            if target and Path(target).is_file():
                catalog[key] = replace(entry, executable=target)
            else:
                # Acceso directo huérfano: la aplicación ya no está en el equipo.
                orphaned.append(key)
        for key in orphaned:
            del catalog[key]
        return catalog

    def entries(self, *, refresh: bool = False) -> dict[str, AppEntry]:
        stale = time.monotonic() - self._built_at > self.ttl_s
        if refresh or not self._entries or stale:
            self._entries = self._build()
            self._built_at = time.monotonic()
            print(f"[AppIndex] {len(self._entries)} aplicaciones indexadas", flush=True)
        return self._entries

    def _lookup(self, wanted: str, catalog: dict[str, AppEntry]) -> AppEntry | None:
        if wanted in catalog:
            return catalog[wanted]
        # Coincidencia por palabra completa: "chrome" encuentra "google chrome",
        # pero "spotify" no encuentra "mpnotify".
        words = set(wanted.split())
        partial = [name for name in catalog if words <= set(name.split())
                   or name.startswith(wanted + " ") or name.endswith(" " + wanted)]
        if partial:
            best = min(partial, key=lambda name: (not catalog[name].from_start_menu, len(name)))
            return catalog[best]
        close = difflib.get_close_matches(wanted, list(catalog), n=1, cutoff=FUZZY_CUTOFF)
        return catalog[close[0]] if close else None

    def resolve(self, requested: str) -> AppEntry | None:
        wanted = normalize(requested)
        if not wanted or self._denied(wanted):
            return None
        found = self._lookup(wanted, self.entries())
        if found is None and time.monotonic() - self._built_at > 5:
            # Reintento con índice fresco: cubre apps instaladas hace un momento.
            found = self._lookup(wanted, self.entries(refresh=True))
        return found

    def suggestions(self, requested: str) -> list[str]:
        catalog = self.entries()
        # Solo se sugiere lo que el usuario reconocería del Menú Inicio.
        visible = [name for name, entry in catalog.items() if entry.from_start_menu]
        close = difflib.get_close_matches(normalize(requested), visible,
                                          n=MAX_SUGGESTIONS, cutoff=0.5)
        names = close or sorted(visible)[:MAX_SUGGESTIONS]
        return [catalog[name].label for name in names[:MAX_SUGGESTIONS]]
