const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const src = fs.readFileSync(require('node:path').join(__dirname, 'renderer.js'), 'utf8');

function renderer() {
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
    WebSocket: class { static OPEN = 1; readyState = 1; sent = []; send(data) { this.sent.push(JSON.parse(data)); } },
  };
  vm.createContext(state);
  vm.runInContext(src.slice(src.indexOf('function connectWebSocket()'), src.indexOf('//  Activación')), state);
  vm.runInContext(src.slice(src.indexOf('let responseWatchdog ='), src.indexOf('function activate()')), state);
  vm.runInContext('connectWebSocket()', state);
  return {state, timers, event: data => state.ws.onmessage({data: JSON.stringify(data)})};
}

test('render deltas immediately, then use the authoritative final text', () => {
  const {state, event} = renderer();
  event({type:'agent_delta', text:'Texto provisional'});
  assert.equal(state.text, 'Texto provisional');
  assert.equal(state.currentState, 'talk');
  event({type:'agent_response', text:'Sí'});
  assert.equal(state.text, 'Sí');
  assert.equal(state.currentState, 'resting');
});

test('refresh watchdog during streaming and cancel a stalled request', () => {
  const {state, event, timers} = renderer();
  event({type:'agent_delta', text:'Hola'});
  event({type:'agent_delta', text:' mundo'});
  assert.equal(timers.size, 1);
  [...timers.values()][0]();
  assert.equal(state.ws.sent[0].type, 'cancel');
  assert.equal(state.currentState, 'resting');
});

test('errors and disconnects release the talking state', () => {
  const {state, event, timers} = renderer();
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
