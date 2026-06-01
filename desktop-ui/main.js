const { app, BrowserWindow, screen, ipcMain } = require("electron");

let win;

function createWindow() {
  const primaryDisplay = screen.getPrimaryDisplay();
  const { width, height } = primaryDisplay.bounds;

  win = new BrowserWindow({
    width: width,
    height: height,
    x: 0,
    y: 0,
    transparent: true,
    frame: false,
    resizable: false,
    alwaysOnTop: true,
    hasShadow: false,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  });

  win.loadFile("index.html");
  win.setMenuBarVisibility(false);
  win.setAlwaysOnTop(true, "screen-saver");
  
  // By default, let's not block the background
  win.setIgnoreMouseEvents(true, { forward: true });
}

app.whenReady().then(() => {
  createWindow();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

ipcMain.on('set-ignore-mouse-events', (event, ignore, options) => {
  if (win) {
    win.setIgnoreMouseEvents(ignore, options);
  }
});