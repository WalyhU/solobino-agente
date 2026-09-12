"""Cliente MCP: añade herramientas de servidores externos sin programarlas aquí.

Los servidores se declaran en `voice-backend/mcp.json` con el mismo formato que
usan otros clientes MCP (`mcpServers`). Al arrancar se descubren sus herramientas
y se traducen al formato de Ollama, de modo que el modelo las llama igual que las
locales. Si un servidor no arranca, el resto del asistente sigue funcionando.
"""
import asyncio
import json
import os
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CONFIG_PATH = Path(__file__).resolve().parent / "mcp.json"
NAME_SEPARATOR = "__"
STARTUP_TIMEOUT_S = 45
CALL_TIMEOUT_S = 60
MAX_RESULT_CHARS = 1500


@dataclass(frozen=True)
class RemoteTool:
    server: str
    tool: str
    spec: dict

    @property
    def qualified(self) -> str:
        return f"{self.server}{NAME_SEPARATOR}{self.tool}"


def _load_config() -> dict[str, dict]:
    if not CONFIG_PATH.is_file():
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        print(f"[MCP] {CONFIG_PATH.name} no es JSON válido: {e}", flush=True)
        return {}
    servers = data.get("mcpServers", {})
    return {name: config for name, config in servers.items()
            if isinstance(config, dict) and not config.get("disabled")}


def _expand(value: str) -> str:
    """Permite `~` y variables en la configuración: la misma `mcp.json` sirve
    en Windows y en macOS, donde las carpetas del usuario están en otra ruta."""
    return os.path.expandvars(os.path.expanduser(value))


def _summarize(result) -> str:
    """Convierte el resultado MCP en texto para el modelo."""
    parts = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            parts.append(text)
        else:
            parts.append(f"[{getattr(item, 'type', 'contenido')} no textual]")
    text = "\n".join(parts).strip() or "Hecho."
    if getattr(result, "isError", False):
        return f"Error: {text}"
    if len(text) > MAX_RESULT_CHARS:
        return text[:MAX_RESULT_CHARS] + "\n… (recortado)"
    return text


class MCPToolset:
    """Mantiene vivas las sesiones MCP y expone sus herramientas al agente."""

    def __init__(self, config: dict[str, dict] | None = None):
        self.config = config if config is not None else _load_config()
        self.tools: dict[str, RemoteTool] = {}
        self._sessions: dict[str, ClientSession] = {}
        self._stack = AsyncExitStack()
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        for name, server in self.config.items():
            try:
                async with asyncio.timeout(STARTUP_TIMEOUT_S):
                    await self._connect(name, server)
            except Exception as e:
                # Un servidor caído no debe impedir que el asistente arranque.
                print(f"[MCP] {name}: no se pudo conectar ({type(e).__name__}: {e})", flush=True)

    async def _connect(self, name: str, server: dict) -> None:
        command = server.get("command")
        if not command:
            raise ValueError("falta 'command'")
        params = StdioServerParameters(
            command=command,
            args=[_expand(str(a)) for a in server.get("args", [])],
            env={**os.environ, **server.get("env", {})},
            cwd=server.get("cwd"),
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._sessions[name] = session
        listed = await session.list_tools()
        allowed = set(self.config[name].get("allowedTools") or [])
        for tool in listed.tools:
            if allowed and tool.name not in allowed:
                continue
            remote = RemoteTool(name, tool.name, {
                "type": "function",
                "function": {
                    "name": f"{name}{NAME_SEPARATOR}{tool.name}",
                    "description": (tool.description or tool.name)[:300],
                    "parameters": tool.input_schema or {"type": "object", "properties": {}},
                },
            })
            self.tools[remote.qualified] = remote
        print(f"[MCP] {name}: {len(listed.tools)} herramientas "
              f"({len(self.tools)} activas en total)", flush=True)

    def writable_paths(self) -> list[str]:
        """Carpetas que los servidores aceptan. El modelo necesita rutas absolutas."""
        found = []
        for server in self.config.values():
            for argument in server.get("args", []):
                candidate = Path(_expand(str(argument)))
                if candidate.is_absolute() and candidate.is_dir():
                    found.append(str(candidate))
        return found

    def specs(self) -> list[dict]:
        return [tool.spec for tool in self.tools.values()]

    def handles(self, name: str) -> bool:
        return name in self.tools

    async def call(self, name: str, arguments: object) -> str:
        remote = self.tools.get(name)
        if remote is None:
            return f"Error: la herramienta {name} no está disponible."
        if not isinstance(arguments, dict):
            return "Error: los argumentos deben ser un objeto JSON."
        session = self._sessions.get(remote.server)
        if session is None:
            return f"Error: el servidor {remote.server} no está conectado."
        try:
            # Una sola llamada a la vez por proceso: las sesiones stdio no son
            # seguras para uso concurrente.
            async with self._lock:
                async with asyncio.timeout(CALL_TIMEOUT_S):
                    result = await session.call_tool(remote.tool, arguments)
        except asyncio.TimeoutError:
            return f"Error: {remote.tool} no respondió en {CALL_TIMEOUT_S} segundos."
        except Exception as e:
            return f"Error al ejecutar {remote.tool}: {type(e).__name__}: {e}"
        return _summarize(result)

    async def close(self) -> None:
        await self._stack.aclose()
        self._sessions.clear()
        self.tools.clear()
