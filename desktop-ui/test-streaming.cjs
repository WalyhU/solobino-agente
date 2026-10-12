const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const src = fs.readFileSync(require('node:path').join(__dirname, 'renderer.js'), 'utf8');

async function renderer() {
  const timers = new Map();
  let id = 0;
  const state = {
    ws: null, pendingCommandBlob: null, streamingBuf: '', currentState: 'think',
    console: {log() {}}, setWakePill() {}, startContinuousListening() {}, stopContinuousListening() {},
    setState(value) { state.currentState = value; },
    setBubbleText(value) { state.text = value; },
    restAfterTalk() { state.currentState = 'resting'; },
    setTimeout(fn) { timers.set(++id, fn); return id; },
    clearTimeout(key) { timers.delete(key); },
    activate() {},
    window: { solobino: {
      getClientInfo: async () => ({ backendUrl: 'ws://127.0.0.1:8000/ws', token: 'test', tools: [], paths: [] }),
      runTool: async () => 'Hecho.',
    } },
    WebSocket: class { static OPEN = 1; readyState = 1; sent = []; send(data) { this.sent.push(JSON.parse(data)); } },
  };
  vm.createContext(state);
  vm.runInContext(src.slice(src.indexOf('async function connectWebSocket()'), src.indexOf('//  Activación')), state);
  vm.runInContext(src.slice(src.indexOf('let responseWatchdog ='), src.indexOf('function activate()')), state);
  await vm.runInContext('connectWebSocket()', state);
  state.ws.onopen();
  return {state, timers, event: data => state.ws.onmessage({data: JSON.stringify(data)})};
}

test('render deltas immediately, then use the authoritative final text', async () => {
  const {state, event} = await renderer();
  event({type:'agent_delta', text:'Texto provisional'});
  assert.equal(state.text, 'Texto provisional');
  assert.equal(state.currentState, 'talk');
  event({type:'agent_response', text:'Sí'});
  assert.equal(state.text, 'Sí');
  assert.equal(state.currentState, 'resting');
});

test('refresh watchdog during streaming and cancel a stalled request', async () => {
  const {state, event, timers} = await renderer();
  event({type:'agent_delta', text:'Hola'});
  event({type:'agent_delta', text:' mundo'});
  assert.equal(timers.size, 1);
  [...timers.values()][0]();
  assert.equal(state.ws.sent[0].type, 'client_hello');
  assert.equal(state.ws.sent[1].type, 'cancel');
  assert.equal(state.currentState, 'resting');
});

test('errors and disconnects release the talking state', async () => {
  const {state, event, timers} = await renderer();
  event({type:'agent_delta', text:'Parcial'});
  event({type:'agent_error', text:'Error local'});
  assert.equal(state.currentState, 'resting');
  assert.equal(state.streamingBuf, '');
  assert.equal(timers.size, 0);
  event({type:'agent_delta', text:'Otro turno'});
  state.ws.readyState = 3;
  state.ws.onclose();
  assert.equal(state.currentState, 'resting');
});

test('execute a requested tool on this client and return its result', async () => {
  const {state, event} = await renderer();
  event({type:'tool_request', id:'one', name:'open_application', arguments:{app_name:'Calculadora'}});
  await Promise.resolve();
  assert.equal(state.ws.sent.at(-1).type, 'tool_result');
  assert.equal(state.ws.sent.at(-1).id, 'one');
});
