// 预加载：向渲染层暴露最小接口，保持上下文隔离。
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('oasDesktop', {
  isElectron: true,
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
    node: process.versions.node,
  },
  onBridgeDown: (cb) => ipcRenderer.on('bridge-down', (_e, code) => cb(code)),
  // 运行时（Python + 依赖，独立下载安装）
  runtime: {
    status: () => ipcRenderer.invoke('runtime-status'),
    download: (url) => ipcRenderer.invoke('download-runtime', url),
    installFromZip: (zipPath) => ipcRenderer.invoke('install-runtime-zip', zipPath),
    onProgress: (cb) => ipcRenderer.on('runtime-progress', (_e, p) => cb(p)),
  },
  // 引擎固定使用安装包内置目录，无需配置
  wizard: {
    done: () => ipcRenderer.send('wizard-done'),
  },
});
