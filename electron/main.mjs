import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = path.resolve(__dirname, '..');
const isDev = !app.isPackaged;
const DEV_RENDERER_URL = process.env.ELECTRON_RENDERER_URL || 'http://localhost:5173';

if (isDev) {
  const devUserDataDir = path.join(app.getPath('temp'), 'paintbrush-pro-electron-dev');
  fs.mkdirSync(devUserDataDir, { recursive: true });
  app.setPath('userData', devUserDataDir);
  app.commandLine.appendSwitch('disable-gpu-shader-disk-cache');
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1380,
    height: 900,
    minWidth: 1100,
    minHeight: 760,
    backgroundColor: '#070b14',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.mjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  if (isDev) {
    win.loadURL(DEV_RENDERER_URL);
    if (process.env.ELECTRON_OPEN_DEVTOOLS === '1') {
      win.webContents.openDevTools({ mode: 'detach' });
    }
  } else {
    win.loadFile(path.join(ROOT_DIR, 'dist', 'index.html'));
  }
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

app.whenReady().then(() => {
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
