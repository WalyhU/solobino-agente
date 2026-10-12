"""Proceso auxiliar del cliente: herramientas locales para Windows y macOS.

Protocolo JSON Lines por stdin/stdout. Solo Electron inicia este proceso.
"""
import asyncio
import base64
import json
import itertools
import sys
from pathlib import Path

from tools import TOOL_SPECS, ToolRunner
from wakeword_infer import WakeWordDetector

MAX_WAKE_PCM_BYTES = 16000 * 4


FILE_TOOL_SPECS = [
    ("read_text_file", "Lee un archivo de texto del Escritorio, Documentos o Descargas.", {"path": "Ruta absoluta"}),
    ("write_file", "Crea o reemplaza un archivo de texto en el Escritorio, Documentos o Descargas.", {"path": "Ruta absoluta", "content": "Contenido"}),
    ("edit_file", "Reemplaza un fragmento exacto en un archivo de texto.", {"path": "Ruta absoluta", "oldText": "Texto anterior", "newText": "Texto nuevo"}),
    ("create_directory", "Crea una carpeta dentro del Escritorio, Documentos o Descargas.", {"path": "Ruta absoluta"}),
    ("list_directory", "Lista los elementos de una carpeta permitida.", {"path": "Ruta absoluta"}),
    ("move_file", "Mueve un archivo o carpeta dentro de las carpetas permitidas.", {"source": "Ruta origen", "destination": "Ruta destino"}),
    ("search_files", "Busca nombres de archivos dentro de una carpeta permitida.", {"path": "Carpeta absoluta", "pattern": "Texto del nombre"}),
]


def _spec(name: str, description: str, fields: dict[str, str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": {
                key: {"type": "string", "description": hint} for key, hint in fields.items()},
                "required": list(fields)}}}


SPECS = TOOL_SPECS + [_spec(*item) for item in FILE_TOOL_SPECS]
FILE_NAMES = {item[0] for item in FILE_TOOL_SPECS}
MAX_FILE_BYTES = 1_000_000


class FileTools:
    def __init__(self):
        home = Path.home()
        self.roots = [p.resolve() for p in (home / "Desktop", home / "Documents", home / "Downloads") if p.is_dir()]

    def _path(self, raw: object) -> Path:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("Falta una ruta absoluta.")
        path = Path(raw).expanduser()
        if not path.is_absolute():
            raise ValueError("La ruta debe ser absoluta.")
        resolved = path.resolve()
        if not any(resolved == root or root in resolved.parents for root in self.roots):
            raise ValueError("La ruta está fuera de Escritorio, Documentos y Descargas.")
        return resolved

    def run(self, name: str, args: object) -> str:
        if name not in FILE_NAMES or not isinstance(args, dict):
            return "Error: herramienta o argumentos inválidos."
        try:
            if name == "move_file":
                source = self._path(args.get("source"))
                destination = self._path(args.get("destination"))
                if destination.exists() or not destination.parent.is_dir():
                    raise ValueError("El destino ya existe o falta su carpeta.")
                source.rename(destination)
                return f"Moví {source.name} a {destination}."
            path = self._path(args.get("path"))
            if name == "read_text_file":
                if path.stat().st_size > MAX_FILE_BYTES:
                    raise ValueError("El archivo supera 1 MB.")
                return path.read_text(encoding="utf-8")[:30000]
            if name == "write_file":
                content = args.get("content")
                if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_FILE_BYTES:
                    raise ValueError("Contenido inválido o mayor de 1 MB.")
                if not path.parent.is_dir():
                    raise ValueError("La carpeta de destino no existe.")
                path.write_text(content, encoding="utf-8")
                return f"Guardé {path}."
            if name == "edit_file":
                old, new = args.get("oldText"), args.get("newText")
                if not isinstance(old, str) or not old or not isinstance(new, str):
                    raise ValueError("Faltan oldText o newText.")
                if path.stat().st_size > MAX_FILE_BYTES:
                    raise ValueError("El archivo supera 1 MB.")
                content = path.read_text(encoding="utf-8")
                if content.count(old) != 1:
                    raise ValueError("oldText debe aparecer exactamente una vez.")
                updated = content.replace(old, new, 1)
                if len(updated.encode("utf-8")) > MAX_FILE_BYTES:
                    raise ValueError("El archivo editado superaría 1 MB.")
                path.write_text(updated, encoding="utf-8")
                return f"Edité {path}."
            if name == "create_directory":
                path.mkdir(parents=True, exist_ok=True)
                return f"Creé {path}."
            if name == "list_directory":
                return "\n".join(sorted(item.name for item in path.iterdir())[:200]) or "Carpeta vacía."
            pattern = args.get("pattern")
            if not isinstance(pattern, str) or not pattern.strip():
                raise ValueError("Falta pattern.")
            matches = (str(item) for item in path.rglob("*") if pattern.casefold() in item.name.casefold())
            return "\n".join(itertools.islice(matches, 100)) or "Sin resultados."
        except (OSError, UnicodeError, ValueError) as exc:
            return f"Error: {exc}"


async def main() -> None:
    protocol_output = sys.stdout
    protocol_output.reconfigure(encoding="utf-8", write_through=True)
    sys.stdout = sys.stderr  # bibliotecas existentes registran diagnósticos por stdout
    runner = ToolRunner()
    files = FileTools()
    wake_detector = WakeWordDetector()
    def send(payload: dict) -> None:
        protocol_output.write(json.dumps(payload, ensure_ascii=False) + "\n")
        protocol_output.flush()
    send({"type": "ready", "tools": SPECS, "paths": [str(root) for root in files.roots],
          "wake_available": wake_detector.available})
    try:
        while line := await asyncio.to_thread(sys.stdin.readline):
            request = None
            try:
                request = json.loads(line)
                if request.get("type") == "wake_score":
                    import numpy as np
                    raw = base64.b64decode(request.get("pcm", ""), validate=True)
                    if len(raw) != MAX_WAKE_PCM_BYTES:
                        raise ValueError("Ventana de wake word inválida.")
                    score = await asyncio.to_thread(
                        wake_detector.score_samples, np.frombuffer(raw, dtype="<f4")
                    )
                    send({"id": request.get("id"), "score": score,
                          "threshold": max(wake_detector.threshold, 0.70)})
                    continue
                name = request.get("name")
                args = request.get("arguments")
                result = files.run(name, args) if name in FILE_NAMES else await runner.run(name, args)
                send({"id": request.get("id"), "text": result})
            except Exception as exc:
                send({"id": request.get("id") if isinstance(request, dict) else None,
                      "text": f"Error: {type(exc).__name__}: {exc}"})
    finally:
        await runner.close()


if __name__ == "__main__":
    asyncio.run(main())
