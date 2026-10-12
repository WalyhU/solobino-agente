import asyncio
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "voice-backend"))
from remote_tools import RemoteToolset


class FakeSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)


class RemoteToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_roundtrip_and_client_paths(self):
        socket = FakeSocket()
        specs = [{"function": {"name": "open_application"}}]
        tools = RemoteToolset(socket, specs, ["C:/Users/test/Documents"])
        task = asyncio.create_task(tools.call("open_application", {"app_name": "Calculadora"}))
        await asyncio.sleep(0)
        self.assertEqual(socket.messages[0]["type"], "tool_request")
        self.assertEqual(tools.writable_paths(), ["C:/Users/test/Documents"])
        tools.resolve({"id": socket.messages[0]["id"], "text": "Abrí Calculadora."})
        self.assertEqual(await task, "Abrí Calculadora.")

    async def test_unknown_tool_and_disconnect(self):
        socket = FakeSocket()
        tools = RemoteToolset(socket, [{"function": {"name": "press_key"}}])
        self.assertIn("no disponible", await tools.call("delete_all", {}))
        task = asyncio.create_task(tools.call("press_key", {"key": "enter"}))
        await asyncio.sleep(0)
        tools.close()
        self.assertIn("desconectó", await task)
