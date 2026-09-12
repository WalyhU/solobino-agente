"""Measure local Ollama streaming and a real, read-only tool round trip.

Only synthetic prompts leave this script. No files, microphone or PC tools are exposed.
Uses the Python standard library; execute after start-local-model.ps1.
"""
import argparse
import json
import statistics
import time
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='qwen3.5:4b')
    parser.add_argument('--context', type=int, default=8192)
    parser.add_argument('--runs', type=int, default=3)
    args = parser.parse_args()
    if args.runs < 1 or args.context < 512:
        parser.error('runs >= 1 y context >= 512')
    endpoint = 'http://127.0.0.1:11434'

    def chat(messages, tools=None):
        payload = dict(model=args.model, messages=messages, stream=True, think=False,
                       keep_alive='15m', options=dict(num_ctx=args.context,
                       num_predict=160, temperature=0, seed=42))
        if tools:
            payload['tools'] = tools
        req = urllib.request.Request(endpoint + '/api/chat',
            data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
        start = time.perf_counter()
        first_text = first_tool = None
        content, calls = '', []
        done = None
        with urllib.request.urlopen(req, timeout=180) as response:
            for line in response:
                event = json.loads(line)
                if event.get('error'):
                    raise RuntimeError(event['error'])
                msg = event.get('message', {})
                if msg.get('content'):
                    if first_text is None:
                        first_text = time.perf_counter() - start
                    content += msg['content']
                if msg.get('tool_calls'):
                    if first_tool is None:
                        first_tool = time.perf_counter() - start
                    calls.extend(msg['tool_calls'])
                if event.get('done'):
                    done = event
        if done is None:
            raise RuntimeError('Stream incompleto: no llego done=true')
        duration = done.get('eval_duration', 0) / 1e9
        metrics = dict(ttft_s=first_text, first_tool_s=first_tool,
            total_s=time.perf_counter() - start,
            load_s=done.get('load_duration', 0) / 1e9,
            prompt_tokens=done.get('prompt_eval_count'),
            output_tokens=done.get('eval_count'),
            tokens_per_s=done.get('eval_count', 0) / duration if duration else None,
            done_reason=done.get('done_reason'), text=content)
        return metrics, dict(role='assistant', content=content, tool_calls=calls)

    messages = [dict(role='system', content='Responde en español en una frase breve.'),
                dict(role='user', content='¿Para qué sirve un asistente de escritorio?')]
    cold, _ = chat(messages)
    print('Primera solicitud:', json.dumps(cold, ensure_ascii=False), flush=True)
    warm = []
    # Different prompts avoid measuring only identical prompt-cache hits.
    prompts = ['¿Qué es una carpeta?', '¿Para qué sirve el micrófono?',
               '¿Qué es una aplicación de escritorio?']
    for i in range(args.runs):
        metric, _ = chat([messages[0], dict(role='user', content=prompts[i % len(prompts)])])
        warm.append(metric)
        print('Solicitud caliente:', json.dumps(metric, ensure_ascii=False), flush=True)

    tool_schema = [dict(type='function', function=dict(name='sumar',
        description='Suma exactamente dos números enteros.', parameters=dict(type='object',
        properties=dict(a=dict(type='integer'), b=dict(type='integer')), required=['a', 'b'])))]
    tool_messages = [dict(role='system', content='Usa la herramienta sumar para las sumas. Tras recibir su resultado responde solo el número.'),
                     dict(role='user', content='Usa sumar para calcular 173 + 289.')]
    first, assistant = chat(tool_messages, tool_schema)
    tool_messages.append(assistant)
    tool_ok = False
    final = None
    calls = assistant['tool_calls']
    if len(calls) == 1:
        function = calls[0].get('function', {})
        values = function.get('arguments', {})
        if (function.get('name') == 'sumar' and isinstance(values, dict)
                and set(values) == {'a', 'b'} and type(values['a']) is int
                and type(values['b']) is int and sorted(values.values()) == [173, 289]):
            result = values['a'] + values['b']
            tool_messages.append(dict(role='tool', tool_name='sumar', content=str(result)))
            final, _ = chat(tool_messages)
            tool_ok = final['text'].strip().rstrip('.') == '462'
    report = dict(model=args.model, context=args.context, think=False, first_request=cold,
        warm_runs=warm, median_ttft_s=statistics.median(m['ttft_s'] for m in warm if m['ttft_s'] is not None),
        tool_roundtrip=dict(passed=tool_ok, first=first, calls=calls, final=final),
        scope='Ollama directo. No incluye Whisper, OpenClaw, MCP ni latencia de internet.')
    out = Path(__file__).resolve().parent.parent / 'local-model-results'
    out.mkdir(exist_ok=True)
    dest = out / 'benchmark.json'
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Resultado: {dest}; tool_roundtrip={tool_ok}', flush=True)
    if not tool_ok:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
