const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('solobino', {
  getConfig: () => ipcRenderer.invoke('solobino:config'),
  getClientInfo: () => ipcRenderer.invoke('solobino:client-info'),
  saveConfig: (config) => ipcRenderer.invoke('solobino:save-config', config),
  runTool: (request) => ipcRenderer.invoke('solobino:run-tool', request),
  scoreWake: (pcm) => ipcRenderer.invoke('solobino:score-wake', pcm),
  setIgnoreMouseEvents: (ignore, options) => ipcRenderer.send('set-ignore-mouse-events', ignore, options),
});
