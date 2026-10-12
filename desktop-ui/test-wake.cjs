const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { WakeAudioBuffer, resampleWake, wakePcmBase64, wakeWavBase64 } = require('./wake-capture.js');

test('audio continuo conserva una palabra que cruza la frontera de ventanas', () => {
  const buffer = new WakeAudioBuffer(16000, 2);
  buffer.append(new Float32Array(12000));
  buffer.append(new Float32Array(12000).fill(0.4));
  const window = buffer.recent(1);
  assert.equal(window.length, 16000);
  assert.equal(window[0], 0);
  assert.ok(window.at(-1) > 0.39);
  buffer.append(new Float32Array(8000).fill(0.8));
  assert.ok(buffer.recent(1).at(-1) > 0.79);
});

test('ventana del modelo y confirmación WAV usan PCM de 16 kHz', () => {
  const pcm = resampleWake(new Float32Array(48000).fill(0.25), 16000);
  assert.equal(Buffer.from(wakePcmBase64(pcm), 'base64').length, 64000);
  const wav = Buffer.from(wakeWavBase64(resampleWake(new Float32Array(72000), 24000)), 'base64');
  assert.equal(wav.toString('ascii', 0, 4), 'RIFF');
  assert.equal(wav.readUInt32LE(24), 16000);
  assert.equal(wav.readUInt32LE(40), 48000);
});

async function wakeRenderer(scoreResult) {
  const sent = [];
  const state = {
    WakeAudioBuffer, resampleWake, wakePcmBase64, wakeWavBase64,
    wakeLocalAvailable: true, wakeCandidate: null, isRecording: false,
    ws: { readyState: 1, send(value) { sent.push(JSON.parse(value)); } },
    WebSocket: { OPEN: 1 }, performance, Date, Math, btoa,
    console: { error() {} }, fallback: 0,
    navigator: { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [{stop() {}}] }) } },
    AudioContext: class {
      sampleRate = 16000;
      audioWorklet = { addModule: async () => {} };
      destination = {};
      createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
      resume() { return Promise.resolve(); }
      close() { return Promise.resolve(); }
    },
    AudioWorkletNode: class {
      constructor() { this.port = {}; state.node = this; }
      connect() {}
      disconnect() {}
    },
    window: { solobino: { scoreWake: async () => scoreResult } },
  };
  vm.createContext(state);
  const source = fs.readFileSync(require('node:path').join(__dirname, 'renderer.js'), 'utf8');
  vm.runInContext(source.slice(source.indexOf('const WAKE_SEGMENT_MS'),
    source.indexOf('//  Interacción: click')), state);
  vm.runInContext('recordWakeSegment = () => { fallback++; }', state);
  await vm.runInContext('startContinuousListening()', state);
  state.node.port.onmessage({ data: new Float32Array(16000).fill(0.2) });
  await new Promise(setImmediate);
  return { state, sent };
}

test('candidato local envía un clip de duración correcta al backend', async () => {
  const { sent } = await wakeRenderer({ available: true, score: 0.9, threshold: 0.7 });
  assert.equal(sent.length, 1);
  assert.equal(sent[0].type, 'wake_word_check');
  const wav = Buffer.from(sent[0].audio, 'base64');
  assert.equal(wav.readUInt32LE(40), 32000);
});

test('confianza intermedia exige dos ventanas solapadas', async () => {
  const { state, sent } = await wakeRenderer({ available: true, score: 0.75, threshold: 0.7 });
  assert.equal(sent.length, 0);
  state.node.port.onmessage({ data: new Float32Array(4000).fill(0.2) });
  await new Promise(setImmediate);
  assert.equal(sent.length, 1);
});

test('si cae el detector local vuelve al detector remoto', async () => {
  const { state, sent } = await wakeRenderer({ available: false });
  assert.equal(sent.length, 0);
  assert.equal(state.fallback, 1);
  assert.equal(state.wakeLocalAvailable, false);
});
