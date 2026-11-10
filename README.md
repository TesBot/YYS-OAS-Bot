# OAS Studio

阴阳师自动化控制台：多实例管理、任务编排、运行日志。基于 [runhey/OAS](https://github.com/runhey/onmyoji_auto_script) 引擎（GPL-3.0）。

## 组成（三部分分别分发）

| 部分 | 内容 | 产物 / 位置 |
|---|---|---|
| **控制台 APP** | Electron 界面 + 任务编排（本目录 `console/`） | `OAS-Studio-Setup-x.x.x.exe` |
| **引擎** | 任务执行、图像/OCR 识别（`engine/`，随安装包内置） | 内置于安装包 |
| **Python 运行时** | 嵌入式 Python 3.10 + 全部依赖（`runtime/`） | `oas-python-runtime-x.x.x.zip`，首次使用时下载安装 |

拆分原因：运行时（约 350 MB）更新频率最低，独立分发后日常版本更新只需下载约 120 MB 的安装包。

## 用户安装流程

1. 安装 `OAS-Studio-Setup-x.x.x.exe`（自带引擎）。
2. 首次启动，按引导下载 Python 运行时（或手动下载 zip 后选择安装；也可换镜像地址）。
3. 启动模拟器 → 打开 OAS Studio 开始使用。

## 构建

```bash
# 前置：Node 18+，Python 3.10（用于打包脚本）
cd console
npm install
npm run dist          # 产出 dist/OAS-Studio-Setup-x.x.x.exe

# 运行时包（仅运行时变更时需要重做）
python tools/pack_runtime.py          # → dist/oas-python-runtime-1.0.0.zip

# 引擎源码 zip（可选，供外部引擎使用者）
python tools/pack_engine.py           # → dist/oas-engine-1.0.0.zip
```

发布时把安装包与运行时 zip 一起传到 GitHub Releases（运行时打 tag `runtime-v1.0.0`，
`console/main.js` 里的 `DEFAULT_RUNTIME_URL` 指向该地址）。

## 开发调试

```bash
cd console && npm start    # 开发模式：读 ../engine 与 ../runtime/python
```

- 控制台改动（界面/编排）：`console/` 下改完重启即可。
- 引擎改动：同步到 `engine/`（与 OAS-Bot 主仓同源）。
- 桥接服务：`engine/gui/bridge.py`，端口 22390；控制台经 `app://` 协议代理 `/api/*`。

## 目录

```
console/   Electron 应用（main.js / preload.js / renderer/）
engine/    引擎源码（module/ tasks/ gui/ deploy/ …，与主开发仓同步）
runtime/   Python 运行时（不入库，由 pack_runtime.py 生成 zip 分发）
tools/     打包脚本（pack_engine.py / pack_runtime.py）
dist/      构建产物（不入库）
```

## 许可

GPL-3.0（见 [LICENSE](LICENSE)），基于 runhey/onmyoji_auto_script 衍生。
