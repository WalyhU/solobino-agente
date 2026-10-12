const test = require('node:test');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const path = require('node:path');
const readline = require('node:readline');

test('the packaged local tool process speaks UTF-8 JSON Lines', async () => {
  const executable = path.join(__dirname, 'bin', 'solobino-tools',
    process.platform === 'win32' ? 'solobino-tools.exe' : 'solobino-tools');
  const child = spawn(executable, [], { stdio: ['pipe', 'pipe', 'pipe'] });
  const messages = [];
  const lines = readline.createInterface({ input: child.stdout });
  const done = new Promise((resolve, reject) => {
    child.on('error', reject);
    child.on('exit', code => code === 0 ? resolve() : reject(new Error(`helper exit ${code}`)));
  });
  lines.on('line', line => {
    const message = JSON.parse(line);
    messages.push(message);
    if (message.type === 'ready') {
      child.stdin.write(JSON.stringify({ id: 'wake', type: 'wake_score',
        pcm: Buffer.alloc(64000).toString('base64') }) + '\n');
      child.stdin.end(JSON.stringify({ id: 'one', name: 'invalid', arguments: {} }) + '\n');
    }
  });
  await done;
  assert.equal(messages[0].type, 'ready');
  assert.ok(messages[0].tools.some(tool => tool.function.name === 'open_application'));
  assert.equal(messages[0].wake_available, true);
  assert.match(messages[0].tools[0].function.description, /aplicación/);
  assert.equal(messages[1].id, 'wake');
  assert.equal(typeof messages[1].score, 'number');
  assert.ok(messages[1].threshold >= 0.70);
  assert.deepEqual(messages[2], { id: 'one', text: 'Error: Herramienta desconocida: invalid.' });
});
