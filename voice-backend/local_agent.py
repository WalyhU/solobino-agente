"""Cliente conversacional de Ollama con ejecución de herramientas locales."""
import asyncio
import json
import os
import time

import httpx

from tools import MAX_TOOL_ROUNDS, TOOL_SPECS, ToolRunner


SYSTEM_PROMPT = (
    "Eres Solobino, un asistente de escritorio. Responde en español con una o dos "
    "frases claras, sin preámbulos. Dispones de herramientas para abrir aplicaciones "
    "y páginas, crear y editar archivos, reproducir música, controlar la reproducción, "
    "pulsar botones de una "
    "app abierta, abrir archivos o carpetas con un programa concreto "
    "(para un proyecto en un editor, pasa la carpeta), "
    "app abierta, escribir texto y usar teclas: úsalas cuando te pidan actuar sobre el "
    "PC, y responde solo con texto cuando sea una pregunta. Para poner música usa "
    "play_music directamente, sin abrir antes la aplicación. Nunca afirmes haber hecho "
    "una acción si la herramienta devolvió un error; explica el problema en una frase."
)
MAX_INPUT_CHARS = 2000
HISTORY_TURNS = 4


class OllamaAgent:
    def __init__(self, model="qwen3.5:4b", base_url="http://127.0.0.1:11434", *,
                 transport=None, tool_runner=None, mcp_tools=None):
        self.model = model
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip('/'),
            timeout=httpx.Timeout(20, connect=5),
            transport=transport,
        )
        self.tools = tool_runner if tool_runner is not None else ToolRunner()
        self.mcp = mcp_tools
        self._slot = asyncio.Semaphore(1)

    def _system_prompt(self, remote_tools=None):
        """Añade las rutas reales: sin ellas el modelo inventa rutas relativas."""
        paths = remote_tools.writable_paths() if remote_tools else (self.mcp.writable_paths() if self.mcp else [])
        if not paths:
            return SYSTEM_PROMPT
        return (SYSTEM_PROMPT + " Usa siempre rutas absolutas de Windows. "
                "Carpetas disponibles: " + ", ".join(paths) + ".")

    def _body(self, messages, with_tools=True, remote_tools=None):
        options = dict(num_ctx=8192, num_predict=256, temperature=0.3)
        num_gpu = os.getenv("OLLAMA_NUM_GPU")
        if num_gpu is not None:
            options["num_gpu"] = int(num_gpu)
        body = dict(model=self.model, messages=messages, think=False, stream=True,
                    keep_alive="15m",
                    options=options)
        if with_tools:
            body['tools'] = (remote_tools.specs() if remote_tools else
                             TOOL_SPECS + (self.mcp.specs() if self.mcp else []))
        return body

    async def warmup(self):
        body = self._body([], with_tools=False)
        body['stream'] = False
        response = await self.client.post('/api/chat', json=body, timeout=60)
        response.raise_for_status()
        if response.json().get('error'):
            raise RuntimeError(response.json()['error'])

    async def close(self):
        await self.client.aclose()

    async def _round(self, messages, emit, with_tools, parts, timing, remote_tools=None):
        """Consume un turno de Ollama. Devuelve (texto, tool_calls, evento final)."""
        round_text = []
        tool_calls = []
        finished = None
        async with self.client.stream('POST', '/api/chat',
                                      json=self._body(messages, with_tools, remote_tools)) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get('error'):
                    raise RuntimeError(event['error'])
                message = event.get('message', {})
                tool_calls.extend(message.get('tool_calls') or [])
                content = message.get('content', '')
                if content:
                    if timing['first'] is None:
                        timing['first'] = time.perf_counter() - timing['started']
                    round_text.append(content)
                    parts.append(content)
                    await emit(dict(type='agent_delta', text=content))
                if event.get('done'):
                    finished = event
                    break
        return ''.join(round_text), tool_calls, finished

    async def reply(self, text, history, emit, remote_tools=None):
        """Envía deltas y un evento final; solo confirma turnos completos.

        history pertenece a una única conexión WebSocket. Cancelar esta corrutina
        cierra el stream HTTP y libera la GPU sin registrar un turno parcial.
        """
        text = text.strip()
        if not text or len(text) > MAX_INPUT_CHARS:
            raise ValueError(f'El mensaje debe contener entre 1 y {MAX_INPUT_CHARS} caracteres.')
        messages = [dict(role='system', content=self._system_prompt(remote_tools))]
        messages.extend(history[-HISTORY_TURNS * 2:])
        messages.append(dict(role='user', content=text))
        timing = dict(started=time.perf_counter(), first=None)
        parts = []
        used_tools = []
        finished = None

        async with self._slot:
            for attempt in range(MAX_TOOL_ROUNDS + 1):
                # En la última vuelta se retiran las herramientas para forzar una
                # respuesta de texto en lugar de encadenar llamadas indefinidamente.
                with_tools = attempt < MAX_TOOL_ROUNDS
                round_text, tool_calls, finished = await self._round(
                    messages, emit, with_tools, parts, timing, remote_tools)
                if not tool_calls:
                    break
                messages.append(dict(role='assistant', content=round_text,
                                     tool_calls=tool_calls))
                for call in tool_calls:
                    function = call.get('function', {})
                    name = function.get('name', '')
                    arguments = function.get('arguments')
                    if remote_tools is not None:
                        result = await remote_tools.call(name, arguments)
                    elif self.mcp is not None and self.mcp.handles(name):
                        result = await self.mcp.call(name, arguments)
                    else:
                        result = await self.tools.run(name, arguments)
                    used_tools.append(name)
                    print(f"[Tool] {name} -> {result}", flush=True)
                    await emit(dict(type='agent_tool', name=name, text=result))
                    messages.append(dict(role='tool', tool_name=name, content=result))

        if finished is None or not parts:
            raise RuntimeError('Ollama no completó una respuesta de texto.')
        answer = ''.join(parts)
        await emit(dict(type='agent_response', text=answer))
        history.extend([dict(role='user', content=text), dict(role='assistant', content=answer)])
        del history[:-HISTORY_TURNS * 2]
        metrics = dict(first_text_s=timing['first'],
                       total_s=time.perf_counter() - timing['started'],
                       tools=used_tools,
                       input_tokens=finished.get('prompt_eval_count'),
                       output_tokens=finished.get('eval_count'))
        print(f"[Ollama] first_text={timing['first']:.3f}s total={metrics['total_s']:.3f}s "
              f"tools={used_tools or '-'} input_tokens={metrics['input_tokens']} "
              f"output_tokens={metrics['output_tokens']}", flush=True)
        return metrics
