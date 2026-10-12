"""Exercise the real WebSocket handler without microphone, GPU or network."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest import mock
from unittest.mock import AsyncMock, Mock, patch

import httpx
import numpy  # Load native extensions before temporarily patching sys.modules.
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1] / 'voice-backend'
sys.path.insert(0, str(BACKEND))
from local_agent import OllamaAgent


class BackendTests(unittest.TestCase):
    def setUp(self):
        whisper = Mock()
        whisper.transcribe.return_value = ([], None)
        modules = {
            'faster_whisper': types.SimpleNamespace(WhisperModel=Mock(return_value=whisper)),
            'agentic_control': types.SimpleNamespace(PCController=Mock(), app_index=Mock()),
            'wakeword_infer': types.SimpleNamespace(WakeWordDetector=Mock(return_value=types.SimpleNamespace(available=False))),
        }
        spec = importlib.util.spec_from_file_location('solobino_test_backend', BACKEND / 'main.py')
        self.backend = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {
            'AGENT_PROVIDER': 'ollama', 'WAKE_FUZZY_RATIO': '0.90'}):
            spec.loader.exec_module(self.backend)
        # No connections were opened by the original client; close it explicitly.
        asyncio.run(self.backend.local_agent.close())
        def handler(req):
            if not json.loads(req.content)['messages']:
                return httpx.Response(200, json={'done':True})
            return httpx.Response(200, text='\n'.join([
                json.dumps({'message': {'content':'Hola '}}),
                json.dumps({'message': {'content':'desde Ollama'}}),
                json.dumps({'done':True}),
            ]))
        self.backend.local_agent = OllamaAgent(transport=httpx.MockTransport(handler))
        self.backend._transcribe_async = AsyncMock(return_value='Saluda brevemente')
        self.backend.openclaw_client.start = AsyncMock()
        self.addCleanup(self.backend._whisper_pool.shutdown, wait=False)

    def test_audio_to_stream_and_no_openclaw_connection(self):
        with TestClient(self.backend.app) as client:
            self.assertEqual(client.get('/health').json()['agent_provider'], 'ollama')
            with client.websocket_connect('/ws') as ws:
                ws.send_bytes(b'synthetic audio handled by mocked STT')
                events = [ws.receive_json() for _ in range(4)]
                self.assertEqual([e['type'] for e in events],
                                 ['transcription','agent_delta','agent_delta','agent_response'])
                self.assertEqual(events[-1]['text'], 'Hola desde Ollama')
        self.backend.openclaw_client.start.assert_not_awaited()

    def test_silent_audio_returns_terminal_error(self):
        self.backend._transcribe_async.return_value = ''
        with TestClient(self.backend.app) as client:
            with client.websocket_connect('/ws') as ws:
                ws.send_bytes(b'silence')
                self.assertEqual(ws.receive_json()['type'], 'agent_error')

    def test_local_wake_candidate_requires_unambiguous_whisper_confirmation(self):
        self.backend._segment_has_voice = Mock(return_value=True)
        self.assertFalse(self.backend._is_wake_word('solo vino'))
        self.assertTrue(self.backend._is_wake_word('Solobino'))
        with TestClient(self.backend.app) as client:
            with client.websocket_connect('/ws') as ws:
                self.backend._transcribe_async.return_value = 'solo vino'
                ws.send_json({'type': 'wake_word_check', 'candidate_id': 'uno',
                              'audio': 'UklGRg=='})
                self.assertEqual(ws.receive_json(),
                                 {'type': 'wake_word_rejected', 'candidate_id': 'uno'})
                self.backend._transcribe_async.return_value = 'Solobino'
                ws.send_json({'type': 'wake_word_check', 'candidate_id': 'dos',
                              'audio': 'UklGRg=='})
                self.assertEqual(ws.receive_json(),
                                 {'type': 'wake_word_detected', 'candidate_id': 'dos'})
            with client.websocket_connect('/ws') as other_ws:
                other_ws.send_json({'type': 'wake_word_check', 'candidate_id': 'otro',
                                    'audio': 'UklGRg=='})
                self.assertEqual(other_ws.receive_json(),
                                 {'type': 'wake_word_detected', 'candidate_id': 'otro'})

    def test_legacy_pc_command_goes_through_tool_validation(self):
        # El mensaje control_pc ya no llega crudo al controlador: pasa por el
        # mismo índice y la misma validación que usan las herramientas del modelo.
        payload = {'action': 'control_pc', 'command': 'open_application',
                   'params': {'app_name': 'notepad & echo owned'}}
        with mock.patch.object(self.backend.tool_runner.__class__, 'run',
                               autospec=True) as run:
            async def refuse(runner, name, args):
                return 'Error: no encontré esa aplicación.'
            run.side_effect = refuse
            with TestClient(self.backend.app) as client:
                with client.websocket_connect('/ws') as ws:
                    ws.send_json(payload)
                    self.assertEqual(ws.receive_json(),
                                     {'type': 'agent_response',
                                      'text': 'Error: no encontré esa aplicación.'})
        self.backend.pc_controller.execute_command.assert_not_called()
        run.assert_called_once()
        self.assertEqual(run.call_args.args[1:],
                         ('open_application', {'app_name': 'notepad & echo owned'}))

    def test_disconnect_cancels_generation(self):
        started, cancelled = threading.Event(), threading.Event()
        async def waiting(*args):
            started.set()
            try:
                await asyncio.sleep(60)
            finally:
                cancelled.set()
        self.backend.local_agent.reply = waiting
        with TestClient(self.backend.app) as client:
            with client.websocket_connect('/ws') as ws:
                ws.send_bytes(b'command')
                self.assertEqual(ws.receive_json()['type'], 'transcription')
                self.assertTrue(started.wait(1))
            self.assertTrue(cancelled.wait(1))

    def test_authenticated_client_executes_its_own_tool(self):
        async def handler(req):
            body = json.loads(req.content)
            if not body['messages']:
                return httpx.Response(200, json={'done': True})
            if any(message['role'] == 'tool' for message in body['messages']):
                return httpx.Response(200, text='\n'.join([
                    json.dumps({'message': {'content': 'Listo.'}}),
                    json.dumps({'done': True}),
                ]))
            return httpx.Response(200, text='\n'.join([
                json.dumps({'message': {'tool_calls': [{
                    'function': {'name': 'open_application',
                                 'arguments': {'app_name': 'Calculadora'}}}]}}),
                json.dumps({'done': True}),
            ]))
        self.backend.local_agent = OllamaAgent(transport=httpx.MockTransport(handler))
        spec = {'type': 'function', 'function': {'name': 'open_application',
                'parameters': {'type': 'object', 'properties': {'app_name': {'type': 'string'}}}}}
        with patch.dict(os.environ, {'SOLOBINO_CLIENT_TOKEN': 'secreto-de-prueba'}):
            with TestClient(self.backend.app) as client:
                with client.websocket_connect('/ws') as ws:
                    ws.send_json({'type': 'client_hello', 'token': 'secreto-de-prueba',
                                  'tools': [spec], 'paths': []})
                    ws.send_bytes(b'orden de prueba')
                    self.assertEqual(ws.receive_json()['type'], 'transcription')
                    call = ws.receive_json()
                    self.assertEqual(call['type'], 'tool_request')
                    self.assertEqual(call['name'], 'open_application')
                    ws.send_json({'type': 'tool_result', 'id': call['id'], 'text': 'Abrí Calculadora.'})
                    self.assertEqual(ws.receive_json()['type'], 'agent_tool')
                    self.assertEqual(ws.receive_json()['type'], 'agent_delta')
                    self.assertEqual(ws.receive_json()['text'], 'Listo.')
        self.backend.pc_controller.execute_command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
