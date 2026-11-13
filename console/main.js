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
let adoptedBridgePid = 0; // 复用到的既有桥接（上次崩溃留下的孤儿），退出时也要回收

// 单实例锁：用户重复双击时聚焦已有窗口，而不是起第二个看不见的实例
// （第二个实例会让「关闭程序 → 重装」一直提示程序正在运行）。
// 拿不到锁必须「立刻」结束本进程：app.quit() 是异步的，后面还会继续执行到
// whenReady，极端情况下会留下一个没有窗口的 OAS Studio.exe —— 安装器正是按
// 可执行文件路径判断「程序正在运行」的，于是重装永远提示关不掉。
const singleInstance = app.requestSingleInstanceLock();
if (!singleInstance) {
  app.exit(0);
}

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

// 整包布局：安装目录 resources\engine。
// 顺带兼容「手动解压到主程序同级」的非标准布局，并校验 bridge.py 是否真在。
function bundledEngineDir() {
  if (!app.isPackaged) return null;
  const primary = path.join(process.resourcesPath, 'engine');
  if (fs.existsSync(path.join(primary, 'gui', 'bridge.py'))) return primary;
  const sibling = path.join(path.dirname(process.execPath), 'engine');
  if (fs.existsSync(path.join(sibling, 'gui', 'bridge.py'))) return sibling;
  return primary;
}

// 旧版运行时位置（安装目录 resources\python）。覆盖安装/升级时会被 NSIS 删除，
// 仅用于一次性迁移到用户目录。
function legacyRuntimeDir() {
  if (!app.isPackaged) return path.join(__dirname, '..', 'runtime', 'python');
  return path.join(process.resourcesPath, 'python');
}

// 运行时目录：放在用户本地数据目录，升级/重装主程序都不会被删除，
// 只有首次安装才需要下载解压一次。
//   打包：%LOCALAPPDATA%\OAS Studio\runtime\python
//   开发：<仓库>\runtime\python
function runtimeDir() {
  if (!app.isPackaged) return path.join(__dirname, '..', 'runtime', 'python');
  const base = process.env.LOCALAPPDATA || path.join(app.getPath('home'), 'AppData', 'Local');
  return path.join(base, 'OAS Studio', 'runtime', 'python');
}

// 老版本把运行时解压到安装目录里，升级时搬一次，避免让用户重新下载 220MB。
function migrateLegacyRuntime() {
  try {
    const target = runtimeDir();
    if (fs.existsSync(path.join(target, 'python.exe'))) return false;
    const legacy = legacyRuntimeDir();
    if (legacy === target || !fs.existsSync(path.join(legacy, 'python.exe'))) return false;
    fs.mkdirSync(path.dirname(target), { recursive: true });
    try {
      fs.renameSync(legacy, target); // 同盘瞬间完成
    } catch {
      fs.cpSync(legacy, target, { recursive: true });
      fs.rmSync(legacy, { recursive: true, force: true });
    }
    return true;
  } catch {
    return false;
  }
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
    path.join(runtimeDir(), 'python.exe'),        // 用户目录（默认，跨版本保留）
    path.join(legacyRuntimeDir(), 'python.exe'),  // 旧版安装目录布局（迁移前）
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

// 生效引擎目录：内置引擎可用时优先，忽略旧版向导残留的失效外部路径并顺手清掉。
// 旧版（1.1.0 前）向导可写 settings.json 的 enginePath，新版已无该入口，
// 但残留值会盖掉安装包内置引擎，导致新机器上报「引擎目录不完整」。
function activeEngineDir() {
  const settings = loadSettings();
  const override = typeof settings.enginePath === 'string' ? settings.enginePath : '';
  const bundled = bundledEngineDir();
  const usable = (dir) => !!dir && fs.existsSync(path.join(dir, 'gui', 'bridge.py'));
  if (usable(bundled)) {
    if (override && path.resolve(override) !== path.resolve(bundled)) {
      try { saveSettings({ enginePath: '' }); } catch { /* 用户目录不可写时忽略 */ }
    }
    return bundled;
  }
  if (usable(override)) return override;
  return override || bundled || '';
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

// 读取已存在桥接服务的身份（pid + 引擎目录），用于判断「这是自己上次崩溃留下的孤儿」。
function probeHealth(port, timeout = 1500) {
  return new Promise((resolve) => {
    const req = http.get({ host: '127.0.0.1', port, path: '/api/health', timeout }, (res) => {
      let body = '';
      res.setEncoding('utf8');
      res.on('data', (chunk) => { body += chunk; });
      res.on('end', () => {
        try { resolve(JSON.parse(body)); } catch { resolve(null); }
      });
    });
    req.on('error', () => resolve(null));
    req.on('timeout', () => { req.destroy(); resolve(null); });
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
    dialog.showErrorBox('引擎目录不完整',
      `未找到：${bridge}\n内置引擎应在：${bundledEngineDir() || '(未打包)'}\n请重新安装 OAS Studio。`);
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
  const engineDir = activeEngineDir();
  const info = await probeHealth(BRIDGE_PORT);
  if (info && info.ok) {
    // 端口上已有桥接：若它跑的就是当前引擎目录，说明是上次异常退出留下的孤儿，
    // 记下 pid，本次退出时一并回收，否则它会一直占着引擎目录导致无法重装。
    const sameEngine = engineDir && info.root &&
      path.resolve(info.root).toLowerCase() === path.resolve(engineDir).toLowerCase();
    if (sameEngine && info.pid) {
      adoptedBridgePid = Number(info.pid);
      console.log(`[bridge] 复用已有服务 pid=${info.pid}（退出时回收）`);
    }
    return true;
  }
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

function protoLog(msg) {
  try {
    fs.appendFileSync(path.join(app.getPath('temp'), 'oas-proto.log'), `${new Date().toISOString()} ${msg}\n`);
  } catch { /* ignore */ }
}

function registerAppProtocol() {
  protoLog('registerAppProtocol: app 协议已注册');
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
    } catch (err) {
      protoLog(`STATIC-ERR ${file} :: ${err && err.message}`);
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

// 只放行 http/https 给系统外壳。
// shell.openExternal 会把任意字符串丢给 ShellExecute：空串、相对路径、未知协议
// 在 Win11 上可能被解析成「找一个应用来打开」→ 直接弹出 Microsoft Store。
// 这里统一收口，非 http(s) 一律忽略。
function openExternalSafe(url) {
  try {
    const u = new URL(String(url));
    if (u.protocol === 'http:' || u.protocol === 'https:') {
      shell.openExternal(u.toString());
    }
  } catch { /* 非法 URL 直接忽略 */ }
}

function attachCommon(win) {
  win.setMenuBarVisibility(false);
  win.webContents.setWindowOpenHandler(({ url }) => {
    openExternalSafe(url);
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
// bsdtar 不吐进度，这里用「已用时间」做诚实的进度提示（只报耗时，不编百分比）。
function extractRuntime(zipPath, onTick) {
  return new Promise((resolve, reject) => {
    const target = runtimeDir();
    const tmp = path.join(path.dirname(target), '.python-extract-tmp');
    const tarExe = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'tar.exe');
    fs.rmSync(tmp, { recursive: true, force: true });
    // bsdtar 的 -C 要求目标目录已存在（不会自建）
    fs.mkdirSync(tmp, { recursive: true });
    const startedAt = Date.now();
    const timer = onTick
      ? setInterval(() => onTick(Math.round((Date.now() - startedAt) / 1000)), 500)
      : null;
    const stop = () => { if (timer) clearInterval(timer); };
    const child = spawn(tarExe, ['-xf', zipPath, '-C', tmp], { windowsHide: true });
    child.on('error', (err) => {
      stop();
      fs.rmSync(tmp, { recursive: true, force: true });
      reject(err);
    });
    child.on('exit', (code) => {
      stop();
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
    wizardSend('runtime-progress', { phase: 'extracting', elapsed: 0 });
    await extractRuntime(zipPath, (elapsed) => {
      wizardSend('runtime-progress', { phase: 'extracting', elapsed });
    });
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

ipcMain.handle('open-external', (_e, url) => openExternalSafe(url));

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
  if (!singleInstance) return; // 已有实例在跑，本进程立刻退出
  registerAppProtocol();
  buildMenu();

  // 老版本运行时在安装目录内，升级后先搬到用户目录再判断
  migrateLegacyRuntime();

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

// 结束一棵进程树。只 kill 直连子进程（TerminateProcess）不会触发 Python 的
// atexit，OCR 守护进程会变成孤儿，表现为「关了控制台但进程还在」。
// 注意：必须用异步 spawn。spawnSync 会阻塞主线程，用户点 X 之后窗口消失、
// 进程却要等 taskkill 跑完才退出（几秒），这期间启动安装器就会被判成
// 「程序仍在运行」——正是「关不干净」的体感来源。
function killTree(pid) {
  try {
    if (!pid) return;
    if (process.platform === 'win32') {
      const child = spawn('taskkill', ['/PID', String(pid), '/T', '/F'], {
        windowsHide: true,
        detached: true,
        stdio: 'ignore',
      });
      child.unref(); // 我们自己退出后，taskkill 继续把树收完
    } else {
      process.kill(pid, 'SIGKILL');
    }
  } catch { /* 进程已退出 */ }
}

function stopBridge() {
  const ownPid = bridgeOwned && bridgeProc ? bridgeProc.pid : 0;
  bridgeProc = null;
  bridgeOwned = false;
  killTree(ownPid);
  if (adoptedBridgePid && adoptedBridgePid !== ownPid) killTree(adoptedBridgePid);
  adoptedBridgePid = 0;
}

// 单实例锁：允许用户重复双击时聚焦已有窗口，而不是起第二个看不见的实例
// （第二个实例会让「关闭程序→重装」一直提示程序正在运行）。
if (singleInstance) {
  app.on('second-instance', () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    } else if (!wizardWindow || wizardWindow.isDestroyed()) {
      createWindow();
    }
  });
}

// 退出：先回收桥接，再让 Electron 正常退出。
//
// 但「正常退出」经常不够干净：Electron 的 GPU / 渲染 / Utility 进程也全是
// OAS Studio.exe，主进程退出时它们可能卡在 D3D 收尾上十几秒；安装器是按
// 「exe 路径以安装目录开头」判断程序是否在运行的，于是重装就弹「无法关闭」。
// 所以这里用**和安装器完全相同的判据**做一次清扫：凡是 exe 路径位于安装目录
// 之下、又不是自己的进程，全部结束掉。两边判据一致，安装器就不会再看到残留。
function sweepInstallDir() {
  if (process.platform !== 'win32') return;
  try {
    const dir = path.dirname(process.execPath).replace(/'/g, "''");
    const script =
      `Get-CimInstance Win32_Process | Where-Object { $_.Path -and ` +
      `$_.Path.StartsWith('${dir}', 'CurrentCultureIgnoreCase') ` +
      `-and $_.ProcessId -ne ${process.pid} } | ` +
      'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }';
    // 必须用绝对路径调用，避免命中 PATH 里的 App Execution Alias（可能弹出商店）
    const ps = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
    const child = spawn(ps, ['-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-Command', script], {
      windowsHide: true,
      detached: true,
      stdio: 'ignore',
    });
    child.unref();
  } catch { /* 尽力而为 */ }
}

let quitting = false;
function beginQuit() {
  if (quitting) return;
  quitting = true;
  stopBridge();
  const sweep = setTimeout(sweepInstallDir, 1200);
  const hard = setTimeout(() => {
    try { app.exit(0); } catch { process.exit(0); }
  }, 2200);
  sweep.unref?.();
  hard.unref?.();
  app.quit();
}

app.on('window-all-closed', () => {
  if (bridgeStarting) return; // 向导已关、主窗口未建：过渡期不退出
  if (process.platform !== 'darwin') beginQuit();
});

app.on('before-quit', (e) => {
  if (quitting) return;
  e.preventDefault();
  beginQuit();
});
app.on('will-quit', stopBridge);

// 兜底：进程无论如何要退出时，最后再踢一次（此时只能用同步方式）
process.on('exit', () => {
  try {
    const pid = bridgeProc && bridgeProc.pid;
    if (pid && process.platform === 'win32') {
      spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { windowsHide: true, timeout: 3000 });
    }
  } catch { /* ignore */ }
});
