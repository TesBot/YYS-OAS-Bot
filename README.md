# YYJio（痒痒鸡）

阴阳师自动化控制台：多账号管理、任务编排、可视化执行日志。引擎基于 [runhey/OAS](https://github.com/runhey/onmyoji_auto_script)（GPL-3.0），界面与引擎解耦。

**官网（功能演示 + 使用说明）：<https://tesbot.github.io/YYS-OAS-Bot/>**
**下载：<https://github.com/TesBot/YYS-OAS-Bot/releases/latest>**

## 功能

- **多开与账号绑定**：一台模拟器一个账号；绑定后自动从游戏画面识别昵称、截取圆形头像。
- **任务编排**：探索、御魂、觉醒、活动等玩法排成流水线，支持循环、随机发呆、多账号联动。
- **自定义点击**：`直接识别并点击`（OCR 判定文字）与 `滚动寻找并点击`（边滚动边模板匹配），同方案可混用。
- **自定义组队**：指定队长与队员，后续玩法自动沿用该队伍。
- **执行记录**：每步开始 / 结束 / 耗时，日志坞实时输出引擎日志。
- **检查更新**：侧栏版本号旁一键查询 GitHub Releases。

## 组成（三部分分别分发）

| 部分 | 内容 | 产物 / 位置 |
|---|---|---|
| **控制台 APP** | Electron 界面 + 任务编排（`console/`） | `YYJio-Setup-x.x.x.exe` |
| **引擎** | 任务执行、图像 / OCR 识别（`engine/`，随安装包内置） | 内置 |
| **Python 运行时** | 嵌入式 Python 3.10 + 全部依赖（`runtime/`） | `oas-python-runtime-x.x.x.zip`，首次使用时下载 |

拆分原因：运行时（约 350 MB）更新频率最低，独立分发后日常版本更新只需下载约 110 MB 的安装包。

## 安装

1. 安装 `YYJio-Setup-x.x.x.exe`（自带引擎）。安装包请放在桌面、下载目录等普通位置再运行。
2. 首次启动按向导准备 Python 运行时（或手动选择本地 zip / 换镜像地址）。
3. 启动模拟器（分辨率必须是 **1280×720**）→ 打开游戏 → 在控制台「刷新设备」→「绑定新账号」。

## 构建

```bash
# 前置：Node 18+，Python 3.10（打包脚本用）
cd console
npm install
npm run dist          # 产出 dist/YYJio-Setup-x.x.x.exe

# Windows 上也可以直接双击仓库根目录的「打包安装包.bat」
```

运行时包与引擎包（仅在需要更新时重做）：

```bash
python tools/pack_runtime.py   # → dist/oas-python-runtime-1.0.0.zip
python tools/pack_engine.py    # → dist/oas-engine-1.0.0.zip
```

## 开发调试

```bash
cd console && npm start    # 开发模式：读 ../engine 与 ../runtime/python
```

- 控制台改动：`console/` 下改完重启即可。**注意 `console/renderer/{app.js,app.css}` 与 `engine/gui/static/` 是两份相同文件，改完要同步。**
- 引擎改动：同步到 `engine/`。
- 桥接服务：`engine/gui/bridge.py`，端口 22390；控制台经 `app://` 协议代理 `/api/*`。

## 目录

```
console/   Electron 应用（main.js / preload.js / renderer/）
engine/    引擎源码（module/ tasks/ gui/ deploy/ …）
html/      官网静态页（GitHub Pages，从本目录发布）
runtime/   Python 运行时（不入库，由 pack_runtime.py 生成 zip 分发）
tools/     打包脚本（pack_engine.py / pack_runtime.py）
dist/      构建产物（不入库）
```

## 许可

GPL-3.0（见 [LICENSE](LICENSE)），基于 runhey/onmyoji_auto_script 衍生。
