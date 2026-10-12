"""Herramientas ejecutadas en el equipo que mantiene la conexión WebSocket."""
import asyncio
import uuid


class RemoteToolset:
    def __init__(self, websocket, specs: list[dict], paths: list[str] | None = None):
        self.websocket = websocket
        self._specs = specs
        self._names = {spec["function"]["name"] for spec in specs}
        self._paths = paths or []
        self._pending: dict[str, asyncio.Future[str]] = {}

    def specs(self) -> list[dict]:
        return self._specs

    def writable_paths(self) -> list[str]:
        return self._paths

    async def call(self, name: str, arguments: object) -> str:
        if name not in self._names:
            return f"Error: herramienta {name} no disponible en este equipo."
        call_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self._pending[call_id] = future
        try:
            await self.websocket.send_json({"type": "tool_request", "id": call_id,
                                            "name": name, "arguments": arguments})
            return await asyncio.wait_for(future, timeout=65)
        except asyncio.TimeoutError:
            return f"Error: {name} no respondió en 65 segundos."
        except Exception as exc:
            return f"Error al llamar {name}: {exc}"
        finally:
            self._pending.pop(call_id, None)

    def resolve(self, message: dict) -> None:
        future = self._pending.get(message.get("id"))
        if future is not None and not future.done():
            result = message.get("text")
            future.set_result(result if isinstance(result, str) else "Error: respuesta inválida.")

    def close(self) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_result("Error: el cliente se desconectó.")
        self._pending.clear()
