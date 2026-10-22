const { app, BrowserWindow, Menu, ipcMain, screen, safeStorage, session, systemPreferences } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');

let win;
let settingsWindow;
let helper;
let helperTools = [];
let helperPaths = [];
let wakeAvailable = false;
let helperReady;
let resolveHelper;
const pending = new Map();
const configPath = () => path.join(app.getPath('userData'), 'connection.json');

function readConfig() {
  try {
    const data = JSON.parse(fs.readFileSync(configPath(), 'utf8'));
    const token = data.encryptedToken && safeStorage.isEncryptionAvailable()
      ? safeStorage.decryptString(Buffer.from(data.encryptedToken, 'base64')) : (data.token || '');
    return { backendUrl: data.backendUrl || '', token };
  } catch { return { backendUrl: '', token: '' }; }
}

function saveConfig(config) {
  const url = new URL(config.backendUrl);
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  if ((url.protocol !== 'wss:' && !(local && url.protocol === 'ws:')) || !url.pathname.endsWith('/ws')) {
    throw new Error('Usa una URL wss://.../ws; ws:// solo se admite en este equipo.');
  }
  if (typeof config.token !== 'string' || !config.token.trim()) throw new Error('Falta el token del servicio.');
  if (!safeStorage.isEncryptionAvailable()) throw new Error('El sistema no permite guardar el token de forma segura.');
  fs.mkdirSync(app.getPath('userData'), { recursive: true });
  fs.writeFileSync(configPath(), JSON.stringify({ backendUrl: url.href,
    encryptedToken: safeStorage.encryptString(config.token.trim()).toString('base64') }), { mode: 0o600 });
}

function startHelper() {
  helperReady = new Promise((resolve) => { resolveHelper = resolve; });
  const packaged = path.join(process.resourcesPath, 'bin', 'solobino-tools',
    process.platform === 'win32' ? 'solobino-tools.exe' : 'solobino-tools');
  const devPython = process.platform === 'win32'
    ? path.join(__dirname, '..', 'voice-backend', 'venv', 'Scripts', 'python.exe')
    : path.join(__dirname, '..', 'voice-backend', 'venv', 'bin', 'python');
  const command = app.isPackaged ? packaged : devPython;
  const args = app.isPackaged ? [] : [path.join(__dirname, '..', 'voice-backend', 'client_tools.py')];
  helper = spawn(command, args, { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
  helper.on('error', (error) => { console.error('[Tools]', error); resolveHelper([]); });
  helper.on('exit', () => {
    wakeAvailable = false;
    resolveHelper([]);
    for (const callback of pending.values()) callback({ text: 'Error: las herramientas locales se detuvieron.' });
    pending.clear();
  });
  helper.stderr.on('data', (chunk) => console.error('[Tools]', chunk.toString()));
  readline.createInterface({ input: helper.stdout }).on('line', (line) => {
    try {
      const message = JSON.parse(line);
      if (message.type === 'ready' && Array.isArray(message.tools)) {
        helperTools = message.tools;
        helperPaths = Array.isArray(message.paths) ? message.paths : [];
        wakeAvailable = message.wake_available === true;
        resolveHelper(helperTools);
      } else if (pending.has(message.id)) {
        pending.get(message.id)(message);
        pending.delete(message.id);
      }
    } catch (error) { console.error('[Tools] Respuesta inválida:', error); }
  });
}

async function runTool(request) {
  await helperReady;
  if (!helper || !helper.stdin.writable || !helperTools.some(t => t.function?.name === request.name)) {
    return 'Error: herramienta local no disponible.';
  }
  return new Promise((resolve) => {
    const id = String(request.id);
    const timeout = setTimeout(() => {
      pending.delete(id);
      resolve('Error: la herramienta local tardó demasiado.');
    }, 60000);
    pending.set(id, (result) => { clearTimeout(timeout); resolve(String(result.text || 'Hecho.')); });
    helper.stdin.write(JSON.stringify({ id, name: request.name, arguments: request.arguments }) + '\n');
  });
}

async function scoreWake(pcm) {
  await helperReady;
  if (!wakeAvailable || !helper?.stdin.writable || typeof pcm !== 'string' || pcm.length > 90000) {
    return { available: false };
  }
  return new Promise((resolve) => {
    const id = `wake-${Date.now()}-${Math.random()}`;
    const timeout = setTimeout(() => {
      pending.delete(id);
      resolve({ available: false });
    }, 1500);
    pending.set(id, (result) => {
      clearTimeout(timeout);
      resolve(typeof result.score === 'number'
        ? { available: true, score: result.score, threshold: Number(result.threshold) || 1 }
        : { available: false });
    });
    helper.stdin.write(JSON.stringify({ id, type: 'wake_score', pcm }) + '\n');
  });
}

function createWindow() {
  if (win && !win.isDestroyed()) return;
  const { width, height } = screen.getPrimaryDisplay().bounds;
  win = new BrowserWindow({ width, height, x: 0, y: 0, transparent: true, frame: false,
    resizable: false, alwaysOnTop: true, hasShadow: false,
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true,
      nodeIntegration: false, sandbox: true } });
  win.loadFile('index.html');
  win.webContents.on('will-navigate', (event) => event.preventDefault());
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('context-menu', openSettings);
  win.setMenuBarVisibility(false);
  win.setAlwaysOnTop(true, 'screen-saver');
  win.setIgnoreMouseEvents(true, { forward: true });
  win.on('closed', () => { win = null; });
}

function openSettings() {
  if (settingsWindow && !settingsWindow.isDestroyed()) { settingsWindow.focus(); return; }
  settingsWindow = new BrowserWindow({ width: 470, height: 340, resizable: false,
    title: 'Conectar Solobino', webPreferences: { preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true, nodeIntegration: false, sandbox: true } });
  settingsWindow.loadFile('settings.html');
  settingsWindow.webContents.on('will-navigate', (event) => event.preventDefault());
  settingsWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  settingsWindow.on('closed', () => { settingsWindow = null; });
}

app.whenReady().then(() => {
  session.defaultSession.setPermissionCheckHandler((webContents, permission) => {
    return permission === 'media' && webContents === win?.webContents;
  });
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback, details) => {
    callback(permission === 'media' && webContents === win?.webContents &&
      details.mediaTypes?.includes('audio') === true);
  });
  startHelper();
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: 'Solobino', submenu: [
      { label: 'Configurar servidor', click: openSettings },
      { role: 'quit', label: 'Salir' },
    ] },
  ]));
  if (readConfig().backendUrl) createWindow(); else openSettings();
});

app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('before-quit', () => { if (helper && !helper.killed) helper.kill(); });
app.on('activate', () => { if (!win) { if (readConfig().backendUrl) createWindow(); else openSettings(); } });

ipcMain.handle('solobino:config', () => readConfig());
ipcMain.handle('solobino:client-info', async () => ({ ...readConfig(), tools: await helperReady,
  paths: helperPaths, wakeAvailable }));
ipcMain.handle('solobino:mic-access', async (event) => {
  if (event.sender !== win?.webContents) return false;
  if (process.platform !== 'darwin') return true;
  return systemPreferences.askForMediaAccess('microphone');
});
ipcMain.handle('solobino:save-config', (_event, config) => {
  saveConfig(config);
  if (win) win.reload(); else createWindow();
  if (settingsWindow) settingsWindow.close();
  return true;
});
ipcMain.handle('solobino:run-tool', (_event, request) => runTool(request));
ipcMain.handle('solobino:score-wake', (_event, pcm) => scoreWake(pcm));
ipcMain.on('set-ignore-mouse-events', (_event, ignore, options) => {
  if (win) win.setIgnoreMouseEvents(Boolean(ignore), options);
});
