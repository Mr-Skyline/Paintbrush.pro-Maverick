import { app, BrowserWindow, dialog, ipcMain, screen, shell } from 'electron';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = path.resolve(__dirname, '..');
const isDev = !app.isPackaged;
const FORCE_DIST =
  process.argv.includes('--use-dist') || process.env.ELECTRON_USE_DIST === '1';
const USE_DEV_SERVER = isDev && !FORCE_DIST;
const DEV_RENDERER_URL = process.env.ELECTRON_RENDERER_URL || 'http://127.0.0.1:5173';
const appModeArg = process.argv.find((arg) => arg.startsWith('--app-mode='));
const displayArg = process.argv.find((arg) => arg.startsWith('--display='));
const APP_MODE = appModeArg ? appModeArg.split('=')[1] : 'invoice';
const START_FULLSCREEN =
  APP_MODE === 'battleship' || process.argv.includes('--start-fullscreen');

if (APP_MODE === 'battleship') {
  app.disableHardwareAcceleration();
}

if (isDev) {
  const devUserDataDir = path.join(app.getPath('temp'), 'paintbrush-pro-electron-dev');
  fs.mkdirSync(devUserDataDir, { recursive: true });
  app.setPath('userData', devUserDataDir);
  app.commandLine.appendSwitch('disable-gpu-shader-disk-cache');
}

const WINDOW_PREFS_PATH = path.join(app.getPath('userData'), 'window-preferences.json');
const DEFAULT_MONITOR_PREFERENCE = APP_MODE === 'battleship' ? 'secondary' : 'primary';
let replayWindow = null;

function isValidMonitorPreference(value) {
  if (value === 'primary' || value === 'secondary') return true;
  if (typeof value !== 'string') return false;
  if (/^id:\d+$/.test(value)) return true;
  if (/^index:\d+$/.test(value)) return true;
  return false;
}

function readWindowPrefs() {
  try {
    if (!fs.existsSync(WINDOW_PREFS_PATH)) return {};
    const raw = fs.readFileSync(WINDOW_PREFS_PATH, 'utf8');
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function writeWindowPrefs(prefs) {
  try {
    fs.mkdirSync(path.dirname(WINDOW_PREFS_PATH), { recursive: true });
    fs.writeFileSync(WINDOW_PREFS_PATH, JSON.stringify(prefs, null, 2));
  } catch {
    // Best-effort persistence.
  }
}

function getMonitorPreference() {
  const argValue = displayArg ? displayArg.split('=')[1] : null;
  if (isValidMonitorPreference(argValue)) return argValue;
  const persisted = readWindowPrefs().monitorPreference;
  if (isValidMonitorPreference(persisted)) return persisted;
  return DEFAULT_MONITOR_PREFERENCE;
}

function displayLabel(display, index, primaryId) {
  const role = display.id === primaryId ? 'Primary' : 'Secondary';
  return `${role} (#${index + 1}) ${display.bounds.width}x${display.bounds.height}`;
}

function listDisplays() {
  const allDisplays = screen.getAllDisplays();
  const primary = screen.getPrimaryDisplay();
  return allDisplays.map((display, index) => ({
    id: display.id,
    isPrimary: display.id === primary.id,
    label: displayLabel(display, index, primary.id),
    bounds: {
      x: display.bounds.x,
      y: display.bounds.y,
      width: display.bounds.width,
      height: display.bounds.height,
    },
  }));
}

function resolveTargetDisplay(preference) {
  const allDisplays = screen.getAllDisplays();
  const primaryDisplay = screen.getPrimaryDisplay();
  if (allDisplays.length <= 1) return primaryDisplay;

  if (preference === 'primary') return primaryDisplay;
  if (preference === 'secondary') {
    return allDisplays.find((d) => d.id !== primaryDisplay.id) ?? primaryDisplay;
  }
  if (typeof preference === 'string' && preference.startsWith('id:')) {
    const id = Number(preference.slice(3));
    return allDisplays.find((d) => d.id === id) ?? primaryDisplay;
  }
  if (typeof preference === 'string' && preference.startsWith('index:')) {
    const oneBasedIndex = Number(preference.slice(6));
    const idx = Math.max(0, oneBasedIndex - 1);
    return allDisplays[idx] ?? primaryDisplay;
  }
  return allDisplays.find((d) => d.id !== primaryDisplay.id) ?? primaryDisplay;
}

function applyWindowToMonitorPreference(win, preference) {
  const display = resolveTargetDisplay(preference);
  const targetBounds = display.workArea ?? display.bounds;
  const wasFullscreen = win.isFullScreen();
  const wasMaximized = win.isMaximized();

  if (wasFullscreen) {
    win.setFullScreen(false);
  }
  win.setBounds({
    x: targetBounds.x,
    y: targetBounds.y,
    width: targetBounds.width,
    height: targetBounds.height,
  });
  if (wasFullscreen || START_FULLSCREEN) {
    win.setFullScreen(true);
  } else if (wasMaximized) {
    win.maximize();
  }
  return {
    id: display.id,
    bounds: targetBounds,
  };
}

function createWindow() {
  const monitorPreference = getMonitorPreference();
  const targetDisplay = resolveTargetDisplay(monitorPreference);
  const targetBounds = targetDisplay?.workArea ?? targetDisplay?.bounds;

  const win = new BrowserWindow({
    width: 1380,
    height: 900,
    minWidth: 1100,
    minHeight: 760,
    ...(targetBounds ? { x: targetBounds.x, y: targetBounds.y } : {}),
    show: false,
    backgroundColor: '#070b14',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.mjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  replayWindow = win;

  if (USE_DEV_SERVER) {
    win.loadURL(`${DEV_RENDERER_URL}?appMode=${encodeURIComponent(APP_MODE)}`);
    if (process.env.ELECTRON_OPEN_DEVTOOLS === '1') {
      win.webContents.openDevTools({ mode: 'detach' });
    }
  } else {
    win.loadFile(path.join(ROOT_DIR, 'dist', 'index.html'), {
      query: { appMode: APP_MODE },
    });
  }

  win.webContents.on('did-fail-load', (_event, code, description, validatedURL) => {
    console.error('[electron] did-fail-load', { code, description, validatedURL });
  });
  win.webContents.on('render-process-gone', (_event, details) => {
    console.error('[electron] render-process-gone', details);
  });
  win.webContents.on('console-message', (_event, level, message, line, sourceId) => {
    if (level >= 2) {
      console.error('[renderer]', { level, message, line, sourceId });
    }
  });
  win.webContents.on('did-finish-load', () => {
    console.log('[electron] did-finish-load', win.webContents.getURL());
  });

  win.once('ready-to-show', () => {
    win.show();
    if (START_FULLSCREEN) {
      win.maximize();
      win.setFullScreen(true);
    }
  });
  win.on('closed', () => {
    if (replayWindow === win) {
      replayWindow = null;
    }
  });
}

async function pickFiles() {
  const result = await dialog.showOpenDialog({
    title: 'Select Invoice Files',
    properties: ['openFile', 'multiSelections'],
    filters: [
      {
        name: 'Invoices',
        extensions: ['pdf', 'jpg', 'jpeg', 'png', 'webp', 'tif', 'tiff'],
      },
    ],
  });
  if (result.canceled) return [];
  return result.filePaths;
}

async function pickDbFile() {
  const result = await dialog.showOpenDialog({
    title: 'Select Product Price Database',
    properties: ['openFile'],
    filters: [{ name: 'JSON', extensions: ['json'] }],
  });
  if (result.canceled) return null;
  return result.filePaths[0] || null;
}

async function pickDbCreatePath() {
  const result = await dialog.showSaveDialog({
    title: 'Create Product Price Database',
    defaultPath: path.join(ROOT_DIR, 'data', 'product-prices.json'),
    filters: [{ name: 'JSON', extensions: ['json'] }],
  });
  if (result.canceled) return null;
  return result.filePath || null;
}

async function pickOutputDir() {
  const result = await dialog.showOpenDialog({
    title: 'Select Output Folder',
    properties: ['openDirectory', 'createDirectory'],
  });
  if (result.canceled) return null;
  return result.filePaths[0] || null;
}

function runInvoiceReview(options) {
  const scriptPath = path.join(ROOT_DIR, 'scripts', 'review-invoices.mjs');
  const args = [scriptPath];

  const files = Array.isArray(options?.files) ? options.files : [];
  const outDir = String(options?.outDir || '').trim();
  const dbPath = String(options?.dbPath || '').trim();
  const toleranceValue = Number(options?.tolerance);
  const extractOnly = Boolean(options?.extractOnly);

  for (const filePath of files) {
    if (String(filePath).trim()) {
      args.push('--files', String(filePath));
    }
  }
  if (outDir) args.push('--out', outDir);
  if (dbPath) args.push('--db', dbPath);
  if (Number.isFinite(toleranceValue)) {
    args.push('--tolerance', String(toleranceValue));
  }
  if (extractOnly) args.push('--extract-only');

  return new Promise((resolve) => {
    const child = spawn(process.execPath, args, {
      cwd: ROOT_DIR,
      windowsHide: true,
      env: {
        ...process.env,
        // In Electron, process.execPath points to electron.exe.
        // This flag makes spawned Electron behave like Node for CLI scripts.
        ELECTRON_RUN_AS_NODE: '1',
      },
    });

    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
    });
    child.on('close', (code) => {
      resolve({
        ok: code === 0,
        exitCode: code ?? 1,
        stdout,
        stderr,
      });
    });
    child.on('error', (error) => {
      resolve({
        ok: false,
        exitCode: 1,
        stdout,
        stderr: `${stderr}\nSpawn error: ${error?.message || String(error)}`,
      });
    });
  });
}

function readJsonIfExists(filePath) {
  if (!filePath) return null;
  if (!fs.existsSync(filePath)) return null;
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function normalizeProductsInput(products) {
  if (!Array.isArray(products)) return [];
  return products.map((item) => ({
    sku: String(item?.sku || '').trim(),
    name: String(item?.name || '').trim(),
    unitPrice: Number(item?.unitPrice),
    aliases: Array.isArray(item?.aliases)
      ? item.aliases.map((alias) => String(alias).trim()).filter(Boolean)
      : [],
  }));
}

function readDbFile(dbPath) {
  const resolvedPath = String(dbPath || '').trim();
  if (!resolvedPath) return { ok: false, error: 'Missing database path.' };
  if (!fs.existsSync(resolvedPath)) {
    return { ok: false, error: `Database file not found: ${resolvedPath}` };
  }
  try {
    const raw = fs.readFileSync(resolvedPath, 'utf8');
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return { ok: false, error: 'Database JSON must be an array.' };
    }
    return { ok: true, products: normalizeProductsInput(parsed) };
  } catch (error) {
    return {
      ok: false,
      error: `Could not read database file: ${error?.message || String(error)}`,
    };
  }
}

async function writeDbFile(dbPath, products) {
  const resolvedPath = String(dbPath || '').trim();
  if (!resolvedPath) return { ok: false, error: 'Missing database path.' };
  const payload = normalizeProductsInput(products);
  const parent = BrowserWindow.getFocusedWindow() || null;
  const confirm = await dialog.showMessageBox(parent, {
    type: 'question',
    buttons: ['Cancel', 'Save Changes'],
    defaultId: 1,
    cancelId: 0,
    title: 'Approve Database Update',
    message: 'Save changes to product database?',
    detail: `${resolvedPath}\n\nRows: ${payload.length}\n\nThis will update the JSON file on disk.`,
  });
  if (confirm.response !== 1) {
    return { ok: false, cancelled: true, error: 'Save cancelled by user.' };
  }

  try {
    fs.writeFileSync(resolvedPath, JSON.stringify(payload, null, 2));
    return { ok: true, products: payload };
  } catch (error) {
    return {
      ok: false,
      error: `Could not write database file: ${error?.message || String(error)}`,
    };
  }
}

async function writeDbFileAuto(dbPath, products) {
  const resolvedPath = String(dbPath || '').trim();
  if (!resolvedPath) return { ok: false, error: 'Missing database path.' };
  const payload = normalizeProductsInput(products);
  try {
    fs.mkdirSync(path.dirname(resolvedPath), { recursive: true });
    fs.writeFileSync(resolvedPath, JSON.stringify(payload, null, 2));
    return { ok: true, products: payload };
  } catch (error) {
    return {
      ok: false,
      error: `Could not write database file: ${error?.message || String(error)}`,
    };
  }
}

async function createDbFile(dbPath, initialProducts = []) {
  const resolvedPath = String(dbPath || '').trim();
  if (!resolvedPath) return { ok: false, error: 'Missing database path.' };
  const payload = normalizeProductsInput(initialProducts);
  try {
    fs.mkdirSync(path.dirname(resolvedPath), { recursive: true });
    if (!resolvedPath.toLowerCase().endsWith('.json')) {
      return { ok: false, error: 'Database file must use .json extension.' };
    }
    fs.writeFileSync(resolvedPath, JSON.stringify(payload, null, 2));
    return { ok: true, dbPath: resolvedPath, products: payload };
  } catch (error) {
    return {
      ok: false,
      error: `Could not create database file: ${error?.message || String(error)}`,
    };
  }
}

ipcMain.handle('invoice:pickFiles', pickFiles);
ipcMain.handle('invoice:pickDb', pickDbFile);
ipcMain.handle('invoice:pickDbCreatePath', pickDbCreatePath);
ipcMain.handle('invoice:pickOutput', pickOutputDir);
ipcMain.handle('invoice:run', (_event, options) => runInvoiceReview(options));
ipcMain.handle('invoice:readDb', (_event, dbPath) => readDbFile(dbPath));
ipcMain.handle('invoice:writeDb', (_event, dbPath, products) =>
  writeDbFile(dbPath, products)
);
ipcMain.handle('invoice:writeDbAuto', (_event, dbPath, products) =>
  writeDbFileAuto(dbPath, products)
);
ipcMain.handle('invoice:createDb', (_event, dbPath, initialProducts) =>
  createDbFile(dbPath, initialProducts)
);
ipcMain.handle('invoice:getResults', (_event, outDir) => {
  const baseDir = String(outDir || '');
  return {
    raw: readJsonIfExists(path.join(baseDir, 'invoice-review-results.json')),
    grouped: readJsonIfExists(path.join(baseDir, 'flagged-by-project-or-po.json')),
    candidateDb: readJsonIfExists(path.join(baseDir, 'candidate-product-prices.json')),
    files: {
      raw: path.join(baseDir, 'invoice-review-results.json'),
      grouped: path.join(baseDir, 'flagged-by-project-or-po.json'),
      candidateDb: path.join(baseDir, 'candidate-product-prices.json'),
      pdf: path.join(baseDir, 'flagged-items-by-project-or-po.pdf'),
      xlsx: path.join(baseDir, 'flagged-items-by-project-or-po.xlsx'),
    },
  };
});
ipcMain.handle('invoice:openPath', async (_event, targetPath) => {
  const target = String(targetPath || '').trim();
  if (!target) return false;
  const error = await shell.openPath(target);
  return !error;
});
ipcMain.handle('window:listDisplays', () => listDisplays());
ipcMain.handle('window:getMonitorPreference', () => getMonitorPreference());
ipcMain.handle('window:setMonitorPreference', (_event, preference) => {
  const next = String(preference || '').trim();
  if (!isValidMonitorPreference(next)) {
    return { ok: false, error: 'Invalid monitor preference.' };
  }
  const prefs = readWindowPrefs();
  writeWindowPrefs({
    ...prefs,
    monitorPreference: next,
  });
  const win = BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0] ?? null;
  const appliedDisplay = win ? applyWindowToMonitorPreference(win, next) : null;
  return { ok: true, monitorPreference: next, appliedDisplay };
});
ipcMain.handle('wall:control', (_event, message) => {
  if (!replayWindow || replayWindow.isDestroyed()) {
    return { ok: false, error: 'Replay window unavailable.' };
  }
  replayWindow.webContents.send('wall:control', message);
  return { ok: true };
});

app.whenReady().then(() => {
  app.on('web-contents-created', (_event, contents) => {
    contents.on('console-message', (_e, level, message, line, sourceId) => {
      if (level >= 1) {
        console.log('[web-contents]', {
          level,
          message,
          line,
          sourceId,
          url: contents.getURL(),
        });
      }
    });
  });
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
