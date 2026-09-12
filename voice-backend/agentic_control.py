"""Acciones sobre el equipo. Lanza entradas ya descubiertas, nunca una cadena de shell.

Las acciones de macOS viven en `mac_desktop.py`; aquí solo se elige el camino.
`pyautogui` se importa únicamente en Windows: en macOS necesitaría permisos de
accesibilidad y AppleScript hace lo mismo sin dependencias nativas.
"""
import asyncio
import os
import subprocess
import sys

from app_index import AppEntry, AppIndex

IS_MACOS = sys.platform == "darwin"
if IS_MACOS:
    import mac_desktop

    pyautogui = None
else:
    import pyautogui

    mac_desktop = None

app_index = AppIndex()


class PCController:
    def __init__(self):
        if pyautogui is not None:
            # Mover el ratón a una esquina aborta cualquier automatización.
            pyautogui.FAILSAFE = True

    def execute_command(self, action: str, params: dict) -> str:
        """Ejecuta una acción ya validada por `tools.validate`."""
        print(f"[Agentic] Executing action: {action} with params: {params}", flush=True)

        if action == "open_application":
            entry = params["entry"]
            self._launch(entry)
            return f"Abrí {entry.label}."

        if action == "press_key":
            key = params["key"]
            if IS_MACOS:
                asyncio.run(mac_desktop.press_key(key))
            elif "+" in key:
                pyautogui.hotkey(*key.split("+"))
            else:
                pyautogui.press(key)
            return f"Pulsé {key}."

        if action == "type_text":
            if IS_MACOS:
                asyncio.run(mac_desktop.type_text(params["text"]))
            else:
                pyautogui.write(params["text"], interval=0.02)
            return "Escribí el texto."

        raise ValueError(f"Acción no soportada: {action}")

    def open_file_with(self, entry: AppEntry, path: str) -> None:
        """Abre un archivo o carpeta CON esta aplicación. `path` ya fue comprobado.

        Solo un ejecutable acepta argumentos. Lanzar además la app por su AppID
        abría una segunda ventana vacía, y `os.startfile` abría el archivo con el
        programa predeterminado en vez de con el pedido.
        """
        if os.name != "nt":
            raise NotImplementedError("Solo se admite Windows en esta versión.")
        if IS_MACOS:
            mac_desktop.open_file_with(entry.target, path)
            return
        if not entry.executable:
            raise RuntimeError(
                f"{entry.label} no admite abrir archivos desde fuera; "
                "usa open_path para abrirlo con el programa predeterminado")
        subprocess.Popen([entry.executable, path], shell=False, close_fds=True)

    def open_path(self, path: str) -> None:
        """Abre un archivo o carpeta con el programa predeterminado del sistema."""
        if IS_MACOS:
            mac_desktop.open_path(path)
            return
        if os.name != "nt":
            raise NotImplementedError("Sistema no admitido.")
        os.startfile(path)

    def open_deep_link(self, url: str) -> None:
        """Abre un enlace de aplicación (por ejemplo musics:) ya validado."""
        if IS_MACOS:
            mac_desktop.open_deep_link(url)
            return
        if os.name != "nt":
            raise NotImplementedError("Sistema no admitido.")
        os.startfile(url)

    def press_media_key(self, key: str) -> None:
        if IS_MACOS:
            # En macOS no hay tecla multimedia accesible: lo hace AppleScript.
            return
        pyautogui.press(key)

    def _launch(self, entry: AppEntry) -> None:
        """`entry` proviene del índice del equipo, nunca del texto del modelo."""
        if IS_MACOS:
            mac_desktop.launch(entry.target)
            return
        if os.name != "nt":
            raise NotImplementedError("Sistema no admitido.")
        if entry.kind == "appid":
            # shell:AppsFolder abre igual apps clásicas y UWP; el AppID va como
            # argumento propio, sin interpretación de shell.
            subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + entry.target],
                             shell=False, close_fds=True)
            return
        os.startfile(entry.target)  # ruta del índice: ShellExecute sin línea de comandos
