"""Verify authenticated OpenClaw streaming and workspace file reading."""
import argparse
import json
import time
import urllib.request
import uuid
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--remote', action='store_true', help='Usa el dominio privado de esta PC en Tailscale.')
    args = parser.parse_args()
    base_url = 'https://walter-pc.tail8db8b3.ts.net:8443' if args.remote else 'http://127.0.0.1:18790'
    root = Path(__file__).resolve().parent.parent
    state = root / '.local-solobino'
    cfg = json.loads((state / 'openclaw.json').read_text(encoding='utf-8-sig'))
    marker = 'SOLOBINO-' + uuid.uuid4().hex
    (state / 'workspace' / 'benchmark-probe.txt').write_text(marker, encoding='utf-8')
    session = 'probe-' + uuid.uuid4().hex
    body = dict(model='openclaw/default', stream=True, max_tokens=256, user=session,
        messages=[dict(role='user', content='Lee el archivo benchmark-probe.txt usando la herramienta read. Responde únicamente con el contenido exacto del archivo.')])
    req = urllib.request.Request(base_url + '/v1/chat/completions',
        data=json.dumps(body).encode(), headers={
            'Authorization': 'Bearer ' + cfg['gateway']['auth']['token'],
            'Content-Type': 'application/json', 'x-openclaw-session-key': session})
    start = time.perf_counter()
    first = None
    text = ''
    completed = False
    with urllib.request.urlopen(req, timeout=180) as response:
        for line in response:
            if not line.startswith(b'data:'):
                continue
            raw = line[5:].strip()
            if raw == b'[DONE]':
                completed = True
                break
            event = json.loads(raw)
            if event.get('error'):
                raise RuntimeError(event['error'])
            for choice in event.get('choices', []):
                delta = choice.get('delta', {}).get('content', '')
                if delta:
                    if first is None:
                        first = time.perf_counter() - start
                    text += delta
    report = dict(model='qwen3.5:4b', gateway=base_url,
        ttft_s=first, total_s=time.perf_counter() - start,
        completed=completed, file_read_passed=completed and marker in text,
        response=text, session=session,
        scope='OpenClaw + Ollama + lectura de archivo aleatorio. Sin Whisper; petición desde esta PC.')
    dest = root / 'local-model-results' / ('agent-probe-remote.json' if args.remote else 'agent-probe.json')
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report['file_read_passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
