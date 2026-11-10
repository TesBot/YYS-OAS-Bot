// OAS Studio · 控制台主进程（引擎解耦版）
//
// 职责：
//   1. 首次运行向导：用户选择「引擎目录」（引擎独立分发、解压安装），校验后持久化。
//   2. 从引擎目录拉起桥接服务 gui/bridge.py（引擎自带 .venv Python）。
//   3. 界面（renderer/）由控制台自己经 app:// 协议提供，/api/* 代理给桥接服务
//      —— 界面随控制台更新，引擎随引擎包更新，二者互不绑定。
const { app, BrowserWindow, shell, dialog, ipcMain, protocol, net, Menu } = require('electron');
const { spawn, spawnSync } = require('child_process');
const http = require('http');
const https = require('https');
const path = require('path');
const fs = require('fs');

const RENDERER_DIR = path.join(__dirname, 'renderer');
const BRIDGE_PORT = 22390;
const BRIDGE_URL = `http://127.0.0.1:${BRIDGE_PORT}`;
const SETTINGS_FILE = path.join(app.getPath('userData'), 'settings.json');
const MIN_ENGINE_VERSION = '1.0.0';
const RUNTIME_VERSION = '1.0.1';
// 运行时独立分发：首次使用时下载安装（向导里可改用镜像地址）
const DEFAULT_RUNTIME_URL = 'https://github.com/TesBot/YYS-OAS-Bot/releases/download/runtime-v1.0.1/oas-python-runtime-1.0.1.zip';

let mainWindow = null;
let wizardWindow = null;
let bridgeProc = null;
let bridgeOwned = false;

// ────────────────────────── 设置（引擎目录） ──────────────────────────

function loadSettings() {
  try {
    return JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf8'));
  } catch {
    return {};
  }
}

function saveSettings(patch) {
  const data = Object.assign(loadSettings(), patch);
  fs.mkdirSync(path.dirname(SETTINGS_FILE), { recursive: true });
  fs.writeFileSync(SETTINGS_FILE, JSON.stringify(data, null, 2));
  return data;
}

// 整包布局：安装目录 resources\engine；Python 运行时独立分发，位于 resources\python
function bundledEngineDir() {
  if (!app.isPackaged) return null;
  return path.join(process.resourcesPath, 'engine');
}

// 运行时目录：打包后 resources\python；开发环境 <仓库>/runtime/python
function runtimeDir() {
  return app.isPackaged ? path.join(process.resourcesPath, 'python')
    : path.join(__dirname, '..', 'runtime', 'python');
}

function runtimeStatus() {
  const dir = runtimeDir();
  const pythonExe = path.join(dir, 'python.exe');
  let version = null;
  try {
    version = JSON.parse(fs.readFileSync(path.join(dir, 'runtime_manifest.json'), 'utf8')).version || null;
  } catch { /* 无清单 */ }
  return { dir, installed: fs.existsSync(pythonExe), version };
}

// 定位某引擎目录可用的 Python 解释器：
//   打包布局：engine 同级的 python\python.exe（独立运行时安装后）
//   开发布局：仓库 runtime\python，或引擎自带 .venv
function findPython(engineDir) {
  const candidates = [
    path.join(engineDir, '..', 'python', 'python.exe'),
    path.join(runtimeDir(), 'python.exe'),
    path.join(engineDir, '.venv', 'Scripts', 'python.exe'),
  ];
  return candidates.find((p) => fs.existsSync(p)) || null;
}

// 校验引擎目录：返回逐项结果，全部 ok 才能绑定。
function validateEngine(dir) {
  const checks = { dir: false, bridge: false, manifest: false, python: false, version: null, versionOk: false };
  if (!dir || typeof dir !== 'string' || !fs.existsSync(dir)) return checks;
  checks.dir = true;
  checks.bridge = fs.existsSync(path.join(dir, 'gui', 'bridge.py'));
  checks.python = !!findPython(dir);
  try {
    const manifest = JSON.parse(fs.readFileSync(path.join(dir, 'engine_manifest.json'), 'utf8'));
    checks.manifest = true;
    checks.version = String(manifest.version || '');
    checks.versionOk = compareVersion(checks.version, MIN_ENGINE_VERSION) >= 0;
  } catch { /* manifest 缺失视为不匹配 */ }
  return checks;
}

// 生效引擎目录：用户覆盖优先，否则内置引擎
function activeEngineDir() {
  return loadSettings().enginePath || bundledEngineDir() || '';
}

function compareVersion(a, b) {
  const pa = String(a).split('.').map(Number);
  const pb = String(b).split('.').map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d) return d;
  }
  return 0;
}

// ────────────────────────── 桥接服务生命周期 ──────────────────────────

function probe(port, timeout = 1200) {
  return new Promise((resolve) => {
    const req = http.get({ host: '127.0.0.1', port, path: '/api/health', timeout }, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
  });
}

async function waitBridge(maxMs = 40000) {
  const deadline = Date.now() + maxMs;
  while (Date.now() < deadline) {
    if (await probe(BRIDGE_PORT)) return true;
    await new Promise((r) => setTimeout(r, 700));
  }
  return false;
}

function startBridge(engineDir) {
  const python = findPython(engineDir);
  const bridge = path.join(engineDir, 'gui', 'bridge.py');
  if (!python) {
    dialog.showErrorBox('引擎未完成安装',
      `未在引擎目录找到可用的 Python：${engineDir}\n\n安装包似乎不完整，请重新下载安装。`);
    return false;
  }
  if (!fs.existsSync(bridge)) {
    dialog.showErrorBox('引擎目录不完整', `未找到：${bridge}\n请确认选择的是引擎解压后的根目录。`);
    return false;
  }
  bridgeProc = spawn(python, ['-X', 'utf8', '-B', bridge, '--port', String(BRIDGE_PORT)], {
    cwd: engineDir,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  bridgeOwned = true;
  bridgeProc.stdout.on('data', (d) => process.stdout.write(`[bridge] ${d}`));
  bridgeProc.stderr.on('data', (d) => process.stderr.write(`[bridge] ${d}`));
  bridgeProc.on('exit', (code) => {
    bridgeProc = null;
    if (bridgeOwned && mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('bridge-down', code);
    }
  });
  return true;
}

async function ensureBridge() {
  if (await probe(BRIDGE_PORT)) return true; // 引擎桥接已在运行（可能由另一实例拉起），复用
  const engineDir = activeEngineDir();
  if (!engineDir || !findPython(engineDir)) return false;
  if (!startBridge(engineDir)) return false;
  return waitBridge();
}

// ────────────────────────── app:// 协议（静态 + /api 代理） ──────────────────────────

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
};

function registerAppProtocol() {
  protocol.handle('app', async (request) => {
    const url = new URL(request.url);

    // /api/* → 桥接服务（引擎）。请求体为小 JSON，这里直接缓冲转发。
    if (url.pathname.startsWith('/api/')) {
      const target = `${BRIDGE_URL}${url.pathname}${url.search}`;
      const init = { method: request.method, headers: {} };
      const contentType = request.headers.get('content-type');
      if (contentType) init.headers['content-type'] = contentType;
      if (!['GET', 'HEAD'].includes(request.method)) {
        init.body = Buffer.from(await new Response(request.body).arrayBuffer());
      }
      try {
        return await net.fetch(target, init);
      } catch (err) {
        return new Response(JSON.stringify({ detail: `桥接服务不可达：${String(err)}` }), {
          status: 502,
          headers: { 'content-type': 'application/json' },
        });
      }
    }

    // 静态资源：index.html 里引用 /static/xxx，对应 renderer/xxx。
    let rel = decodeURIComponent(url.pathname);
    if (rel === '/' || rel === '') rel = '/index.html';
    if (rel.startsWith('/static/')) rel = rel.slice('/static/'.length);
    const file = path.normalize(path.join(RENDERER_DIR, rel));
    if (!file.startsWith(RENDERER_DIR)) {
      return new Response('Forbidden', { status: 403 });
    }
    try {
      const data = await fs.promises.readFile(file);
      return new Response(data, { headers: { 'content-type': MIME[path.extname(file).toLowerCase()] || 'application/octet-stream' } });
    } catch {
      return new Response('Not Found', { status: 404 });
    }
  });
}

// ────────────────────────── 窗口 ──────────────────────────

const PRELOAD = path.join(__dirname, 'preload.js');
const WINDOW_OPTS = {
  width: 1280,
  height: 820,
  minWidth: 1024,
  minHeight: 700,
  backgroundColor: '#f7f5f1',
  show: false,
  titleBarStyle: 'hidden',
  titleBarOverlay: { color: '#ffffff', symbolColor: '#57514a', height: 40 },
  webPreferences: { preload: PRELOAD, contextIsolation: true, nodeIntegration: false, sandbox: true },
};

function attachCommon(win) {
  win.setMenuBarVisibility(false);
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({ ...WINDOW_OPTS });
  attachCommon(mainWindow);
  mainWindow.loadURL('app://oas/index.html');
  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.webContents.on('did-fail-load', (_e, code, desc) => {
    console.error('页面加载失败', code, desc);
  });
  mainWindow.on('closed', () => { mainWindow = null; });
}

function openWizard() {
  if (wizardWindow && !wizardWindow.isDestroyed()) {
    wizardWindow.focus();
    return;
  }
  wizardWindow = new BrowserWindow({
    width: 480,
    height: 430,
    resizable: false,
    maximizable: false,
    backgroundColor: '#f7f5f1',
    show: false,
    autoHideMenuBar: true,
    webPreferences: { preload: PRELOAD, contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  wizardWindow.loadURL('app://oas/wizard.html');
  wizardWindow.once('ready-to-show', () => wizardWindow.show());
  wizardWindow.on('closed', () => { wizardWindow = null; });
}

// ────────────────────────── 运行时下载与安装 ──────────────────────────

// 带重定向跟随的下载器（GitHub Releases 会 302 到 CDN）
function downloadToFile(url, dest, onProgress, redirects = 0) {
  return new Promise((resolve, reject) => {
    if (redirects > 8) return reject(new Error('重定向次数过多'));
    const req = https.get(url, { headers: { 'User-Agent': 'OAS-Studio' } }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        res.resume();
        return resolve(downloadToFile(res.headers.location, dest, onProgress, redirects + 1));
      }
      if (res.statusCode !== 200) {
        res.resume();
        return reject(new Error(`下载失败：HTTP ${res.statusCode}`));
      }
      const total = parseInt(res.headers['content-length'] || '0', 10);
      let received = 0;
      const out = fs.createWriteStream(dest);
      res.on('data', (chunk) => {
        received += chunk.length;
        onProgress(received, total);
      });
      res.on('error', reject);
      out.on('error', reject);
      out.on('finish', () => out.close(() => resolve(dest)));
      res.pipe(out);
    });
    req.on('error', reject);
  });
}

// 解压运行时 zip（顶层为 python/）到 runtimeDir()
// 异步执行（spawn 而非 spawnSync）：635MB 解压期间主进程不阻塞，界面保持响应。
// 用 Win10+ 自带 bsdtar（System32，支持 zip）——PATH 里 GNU tar 不认 zip。
function extractRuntime(zipPath) {
  return new Promise((resolve, reject) => {
    const target = runtimeDir();
    const tmp = path.join(path.dirname(target), '.python-extract-tmp');
    const tarExe = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'tar.exe');
    fs.rmSync(tmp, { recursive: true, force: true });
    // bsdtar 的 -C 要求目标目录已存在（不会自建）
    fs.mkdirSync(tmp, { recursive: true });
    const child = spawn(tarExe, ['-xf', zipPath, '-C', tmp], { windowsHide: true });
    child.on('error', (err) => {
      fs.rmSync(tmp, { recursive: true, force: true });
      reject(err);
    });
    child.on('exit', (code) => {
      if (code !== 0) {
        fs.rmSync(tmp, { recursive: true, force: true });
        return reject(new Error(`解压失败（tar 退出码 ${code}）`));
      }
      const extracted = path.join(tmp, 'python');
      if (!fs.existsSync(path.join(extracted, 'python.exe'))) {
        fs.rmSync(tmp, { recursive: true, force: true });
        return reject(new Error('zip 内容不正确：未找到 python/python.exe'));
      }
      try {
        fs.rmSync(target, { recursive: true, force: true }); // 覆盖残缺旧运行时
        fs.renameSync(extracted, target);
        fs.rmSync(tmp, { recursive: true, force: true });
        resolve();
      } catch (err) { reject(err); }
    });
  });
}

function wizardSend(channel, payload) {
  if (wizardWindow && !wizardWindow.isDestroyed()) {
    wizardWindow.webContents.send(channel, payload);
  }
}

// ────────────────────────── IPC（向导） ──────────────────────────

ipcMain.handle('runtime-status', () => Object.assign(runtimeStatus(), { defaultUrl: DEFAULT_RUNTIME_URL, version: runtimeStatus().version }));

ipcMain.handle('download-runtime', async (_e, url) => {
  const target = url || DEFAULT_RUNTIME_URL;
  const zipPath = path.join(app.getPath('temp'), `oas-python-runtime-${RUNTIME_VERSION}.zip`);
  try {
    wizardSend('runtime-progress', { phase: 'downloading', received: 0, total: 0 });
    await downloadToFile(target, zipPath, (received, total) => {
      wizardSend('runtime-progress', { phase: 'downloading', received, total });
    });
    wizardSend('runtime-progress', { phase: 'extracting' });
    await extractRuntime(zipPath);
    fs.rmSync(zipPath, { force: true });
    const st = runtimeStatus();
    wizardSend('runtime-progress', { phase: 'done' });
    return { ok: true, status: st };
  } catch (err) {
    wizardSend('runtime-progress', { phase: 'error', error: String(err && err.message || err) });
    return { ok: false, error: String(err && err.message || err) };
  }
});

ipcMain.handle('install-runtime-zip', async (_e, zipPathArg) => {
  let zipPath = zipPathArg;
  if (!zipPath || !fs.existsSync(zipPath)) {
    const r = await dialog.showOpenDialog(wizardWindow, {
      filters: [{ name: '运行时 zip', extensions: ['zip'] }],
      properties: ['openFile'],
    });
    if (r.canceled || !r.filePaths.length) return { ok: false, canceled: true };
    zipPath = r.filePaths[0];
  }
  try {
    await extractRuntime(zipPath);
    return { ok: true, status: runtimeStatus() };
  } catch (err) {
    return { ok: false, error: String(err && err.message || err) };
  }
});

ipcMain.handle('open-external', (_e, url) => shell.openExternal(url));

let bridgeStarting = false; // 向导→主窗口过渡期，防止零窗口时误判退出

ipcMain.on('wizard-done', async () => {
  if (wizardWindow && !wizardWindow.isDestroyed()) wizardWindow.close();
  bridgeStarting = true;
  const ok = await ensureBridge();
  if (!ok) {
    dialog.showErrorBox('桥接服务启动失败',
      `无法从引擎目录启动 gui/bridge.py。\n当前引擎目录：${activeEngineDir() || '(未配置)'}`);
  }
  if (!mainWindow) createWindow();
  else mainWindow.focus();
  bridgeStarting = false;
});

// ────────────────────────── 菜单 ──────────────────────────

function buildMenu() {
  const template = [
    {
      label: '文件',
      submenu: [
        { label: '重新配置运行时…', click: () => openWizard() },
        { type: 'separator' },
        { label: '退出', role: 'quit' },
      ],
    },
    {
      label: '视图',
      submenu: [
        { label: '重新加载', role: 'reload' },
        { label: '开发者工具', role: 'toggleDevTools' },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// ────────────────────────── 启动流程 ──────────────────────────

protocol.registerSchemesAsPrivileged([
  { scheme: 'app', privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true } },
]);

app.whenReady().then(async () => {
  registerAppProtocol();
  buildMenu();

  // 生效引擎：用户覆盖 > 内置引擎（安装包自带，无需任何配置）
  const engineDir = activeEngineDir();
  const checks = engineDir ? validateEngine(engineDir) : null;
  const ready = checks && checks.bridge && checks.python;

  if (ready) {
    const ok = await ensureBridge();
    if (!ok) {
      dialog.showErrorBox('桥接服务启动失败',
        `无法从引擎目录启动 gui/bridge.py。\n引擎目录：${engineDir}\n若反复失败，请重新安装 OAS Studio。`);
    }
    createWindow();
  } else {
    // 运行环境未装或内置引擎缺失 → 小窗引导
    openWizard();
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      const dir = activeEngineDir();
      const c = dir ? validateEngine(dir) : null;
      if (c && c.bridge && c.python) createWindow();
      else openWizard();
    }
  });
});

app.on('window-all-closed', () => {
  if (bridgeStarting) return; // 向导已关、主窗口未建：过渡期不退出
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  if (bridgeOwned && bridgeProc) {
    try { bridgeProc.kill(); } catch { /* ignore */ }
    bridgeProc = null;
  }
});
