"""Pruebas de integración del WebSocket /ws contra el sandbox en ejecución.

Se ejecutan solo si existe SANDBOX_WS_URL (por ejemplo ws://localhost:8000/ws),
así que `pytest tests` normal las omite.
"""
import asyncio
import os
import unittest

import websockets

WS_URL = os.getenv("SANDBOX_WS_URL")
TOKEN = os.getenv("SOLOBINO_CLIENT_TOKEN", "sandbox-token-de-prueba")


@unittest.skipUnless(WS_URL, "Define SANDBOX_WS_URL para probar contra el sandbox")
class WebSocketSandboxTest(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_rechaza_token_invalido(self):
        async def scenario():
            async with websockets.connect(WS_URL) as ws:
                await ws.send('{"type": "client_hello", "token": "incorrecto", "tools": []}')
                with self.assertRaises(websockets.ConnectionClosed) as ctx:
                    await asyncio.wait_for(ws.recv(), timeout=5)
                return ctx.exception.rcvd.code
        self.assertEqual(self._run(scenario()), 1008)

    def test_rechaza_mensaje_que_no_es_saludo(self):
        async def scenario():
            async with websockets.connect(WS_URL) as ws:
                await ws.send('{"type": "otra_cosa"}')
                with self.assertRaises(websockets.ConnectionClosed) as ctx:
                    await asyncio.wait_for(ws.recv(), timeout=5)
                return ctx.exception.rcvd.code
        self.assertEqual(self._run(scenario()), 1008)

    def test_acepta_token_valido(self):
        async def scenario():
            async with websockets.connect(WS_URL) as ws:
                await ws.send('{"type": "client_hello", "token": "%s", "tools": []}' % TOKEN)
                # Si el saludo es válido, la conexión sigue abierta: no llega cierre en 2 s.
                try:
                    await asyncio.wait_for(ws.recv(), timeout=2)
                except asyncio.TimeoutError:
                    pass
                return ws.state.name
        self.assertEqual(self._run(scenario()), "OPEN")


if __name__ == "__main__":
    unittest.main()
