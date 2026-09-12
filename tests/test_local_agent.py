import asyncio
import json
from pathlib import Path
import sys
import unittest

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'voice-backend'))
from local_agent import HISTORY_TURNS, OllamaAgent
from tools import MAX_TOOL_ROUNDS


def chunk(text='', done=False, tool_calls=None):
    message = {'content': text}
    if tool_calls:
        message['tool_calls'] = tool_calls
    return json.dumps({'message': message, 'done': done}) + '\n'


def call(name, **arguments):
    return {'function': {'name': name, 'arguments': arguments}}


class FakeTools:
    """Sustituye a ToolRunner: registra llamadas sin tocar el PC."""

    def __init__(self, result='Abrí calculadora.'):
        self.result = result
        self.calls = []

    async def run(self, name, arguments):
        self.calls.append((name, arguments))
        return self.result


class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def make_agent(self, handler, tool_runner=None):
        agent = OllamaAgent(transport=httpx.MockTransport(handler),
                            tool_runner=tool_runner or FakeTools())
        self.addAsyncCleanup(agent.close)
        return agent

    async def test_stream_arrives_before_completion(self):
        release = asyncio.Event()
        first = asyncio.Event()
        events = []

        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield chunk('Hola ').encode()
                await release.wait()
                yield chunk('mundo').encode()
                yield chunk(done=True).encode()

        async def emit(event):
            events.append(event)
            first.set()

        agent = await self.make_agent(lambda req: httpx.Response(200, stream=Stream()))
        history = []
        task = asyncio.create_task(agent.reply('Saluda', history, emit))
        try:
            await asyncio.wait_for(first.wait(), 1)
            self.assertFalse(task.done())
            self.assertEqual(events, [{'type': 'agent_delta', 'text': 'Hola '}])
            self.assertEqual(history, [])
        finally:
            release.set()
            await task
        self.assertEqual(events[-1], {'type': 'agent_response', 'text': 'Hola mundo'})
        self.assertEqual(history[-1]['content'], 'Hola mundo')

    async def test_context_is_bounded_and_private(self):
        requests = []
        def handler(req):
            requests.append(json.loads(req.content))
            return httpx.Response(200, text=chunk('Sí') + chunk(done=True))
        agent = await self.make_agent(handler)
        history = []
        async def emit(event): pass
        for i in range(7):
            await agent.reply(f'Pregunta {i}', history, emit)
        self.assertEqual(len(history), HISTORY_TURNS * 2)
        self.assertLessEqual(len(requests[-1]['messages']), 2 + HISTORY_TURNS * 2)
        await agent.reply('Otra conexión', [], emit)
        self.assertEqual(len(requests[-1]['messages']), 2)
        self.assertFalse(requests[-1]['think'])
        self.assertTrue(requests[-1]['stream'])
        self.assertEqual(requests[-1]['options']['num_predict'], 256)

    async def test_broken_stream_does_not_commit_history(self):
        agent = await self.make_agent(lambda req: httpx.Response(200, text=chunk('Parcial')))
        history, events = [], []
        async def emit(event): events.append(event)
        with self.assertRaisesRegex(RuntimeError, 'no completó'):
            await agent.reply('Hola', history, emit)
        self.assertEqual(history, [])
        self.assertFalse(any(e['type'] == 'agent_response' for e in events))

    async def test_server_error_does_not_commit_history(self):
        agent = await self.make_agent(lambda req: httpx.Response(404, json={'error':'model missing'}))
        history = []
        async def emit(event): self.fail('An error must not appear as an answer')
        with self.assertRaises(httpx.HTTPStatusError):
            await agent.reply('Hola', history, emit)
        self.assertEqual(history, [])

    async def test_cancel_closes_stream_and_releases_slot(self):
        started, closed = asyncio.Event(), asyncio.Event()
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                started.set()
                await asyncio.Event().wait()
                yield b''
            async def aclose(self): closed.set()
        agent = await self.make_agent(lambda req: httpx.Response(200, stream=Stream()))
        history = []
        async def emit(event): pass
        task = asyncio.create_task(agent.reply('Hola', history, emit))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(closed.is_set())
        self.assertEqual(history, [])
        await asyncio.wait_for(agent._slot.acquire(), 1)
        agent._slot.release()

    async def test_tool_call_is_executed_and_result_feeds_the_model(self):
        requests = []
        rounds = [
            chunk(tool_calls=[call('open_application', app_name='calculadora')]) + chunk(done=True),
            chunk('Listo, abrí la calculadora.') + chunk(done=True),
        ]

        def handler(req):
            requests.append(json.loads(req.content))
            return httpx.Response(200, text=rounds[len(requests) - 1])

        fake = FakeTools()
        agent = await self.make_agent(handler, fake)
        history, events = [], []
        async def emit(event): events.append(event)
        metrics = await agent.reply('Abre la calculadora', history, emit)

        self.assertEqual(fake.calls, [('open_application', {'app_name': 'calculadora'})])
        self.assertEqual(metrics['tools'], ['open_application'])
        self.assertEqual(events[0], {'type': 'agent_tool', 'name': 'open_application',
                                     'text': 'Abrí calculadora.'})
        self.assertEqual(events[-1], {'type': 'agent_response',
                                      'text': 'Listo, abrí la calculadora.'})
        roles = [m['role'] for m in requests[-1]['messages']]
        self.assertEqual(roles[-3:], ['user', 'assistant', 'tool'])
        self.assertEqual(requests[-1]['messages'][-1]['content'], 'Abrí calculadora.')
        # El historial solo guarda el texto final, no las llamadas intermedias.
        self.assertEqual([m['role'] for m in history], ['user', 'assistant'])

    async def test_tool_loop_is_bounded_and_ends_with_text(self):
        requests = []

        def handler(req):
            body = json.loads(req.content)
            requests.append(body)
            if 'tools' in body:
                return httpx.Response(200, text=chunk(
                    tool_calls=[call('press_key', key='enter')]) + chunk(done=True))
            return httpx.Response(200, text=chunk('No pude terminar la acción.') + chunk(done=True))

        fake = FakeTools(result='Pulsé enter.')
        agent = await self.make_agent(handler, fake)
        history, events = [], []
        async def emit(event): events.append(event)
        await agent.reply('Pulsa enter sin parar', history, emit)

        self.assertEqual(len(fake.calls), MAX_TOOL_ROUNDS)
        self.assertNotIn('tools', requests[-1])
        self.assertEqual(events[-1], {'type': 'agent_response',
                                      'text': 'No pude terminar la acción.'})

    async def test_tool_failure_does_not_abort_the_turn(self):
        rounds = [
            chunk(tool_calls=[call('open_application', app_name='spotify')]) + chunk(done=True),
            chunk('Spotify no está instalado.') + chunk(done=True),
        ]
        seen = []

        def handler(req):
            seen.append(json.loads(req.content))
            return httpx.Response(200, text=rounds[len(seen) - 1])

        agent = await self.make_agent(handler, FakeTools(result='Error: no está instalada.'))
        history, events = [], []
        async def emit(event): events.append(event)
        await agent.reply('Abre Spotify', history, emit)
        self.assertEqual(events[-1]['text'], 'Spotify no está instalado.')
        self.assertEqual(seen[-1]['messages'][-1]['content'], 'Error: no está instalada.')


class FakeMCP:
    """Sustituye a MCPToolset sin lanzar servidores externos."""

    def __init__(self):
        self.calls = []
        self.spec = {'type': 'function', 'function': {'name': 'archivos__write_file',
                                                      'description': 'escribe',
                                                      'parameters': {'type': 'object'}}}

    def specs(self): return [self.spec]
    def handles(self, name): return name == 'archivos__write_file'
    def writable_paths(self): return ['C:' + chr(92) + 'Users' + chr(92) + 'x' + chr(92) + 'Desktop']

    async def call(self, name, arguments):
        self.calls.append((name, arguments))
        return 'Successfully wrote'


class McpRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_tools_are_offered_and_routed(self):
        requests = []
        rounds = [
            chunk(tool_calls=[call('archivos__write_file', path='C:/x/a.html', content='<h1>')]) + chunk(done=True),
            chunk('Archivo creado.') + chunk(done=True),
        ]

        def handler(req):
            requests.append(json.loads(req.content))
            return httpx.Response(200, text=rounds[len(requests) - 1])

        fake_mcp, local = FakeMCP(), FakeTools()
        agent = OllamaAgent(transport=httpx.MockTransport(handler),
                            tool_runner=local, mcp_tools=fake_mcp)
        self.addAsyncCleanup(agent.close)
        events = []
        async def emit(event): events.append(event)
        await agent.reply('Crea un archivo', [], emit)

        offered = [t['function']['name'] for t in requests[0]['tools']]
        self.assertIn('archivos__write_file', offered)
        self.assertIn('open_application', offered)
        # La llamada va al servidor MCP, no al runner local.
        self.assertEqual(fake_mcp.calls,
                         [('archivos__write_file', {'path': 'C:/x/a.html', 'content': '<h1>'})])
        self.assertEqual(local.calls, [])
        self.assertEqual(events[-1]['text'], 'Archivo creado.')

    async def test_writable_paths_reach_the_system_prompt(self):
        requests = []

        def handler(req):
            requests.append(json.loads(req.content))
            return httpx.Response(200, text=chunk('Hecho.') + chunk(done=True))

        agent = OllamaAgent(transport=httpx.MockTransport(handler),
                            tool_runner=FakeTools(), mcp_tools=FakeMCP())
        self.addAsyncCleanup(agent.close)
        async def emit(event): pass
        await agent.reply('Hola', [], emit)
        system = requests[0]['messages'][0]['content']
        self.assertIn('Desktop', system)
        self.assertIn('rutas absolutas', system)



if __name__ == '__main__':
    unittest.main()
