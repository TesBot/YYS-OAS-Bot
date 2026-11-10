# OAS Engine · 阴阳师自动化引擎

这是 **OAS Studio** 的后台引擎。控制台 APP（界面、编排、设备管理）与引擎（任务执行、图像/OCR 识别、模拟器控制）分开分发：

- **OAS Studio 控制台**：安装版 APP，负责界面与编排。去 [Releases](../../releases) 下载 `OAS-Studio-Setup-x.x.x.exe`。
- **本引擎包**：解压即用，负责执行任务。下载 `oas-engine-x.x.x.zip` 解压到任意目录（建议如 `D:\OAS-Engine`，路径中避免中文与空格）。

## 首次安装

1. 安装 [Python 3.10](https://www.python.org/downloads/release/python-31011/)（勾选 Add to PATH）。
2. 解压本引擎包，进入解压后的目录。
3. 双击运行 `setup_engine.bat`——它会自动创建 `.venv` 虚拟环境并安装全部依赖（几分钟）。
4. 打开 OAS Studio，在首次向导中选择刚才的引擎目录，完成绑定。

## 日常使用

- 启动模拟器 → 打开 OAS Studio，控制台会自动拉起引擎桥接服务（`gui/bridge.py`，端口 22390）。
- 引擎配置、账号实例、编排数据都保存在本目录的 `config/` 下；日志在 `log/`。
- 卸载控制台 APP 不影响引擎；反之亦然。

## 更新引擎

下载新版 `oas-engine-x.x.x.zip`，解压覆盖旧目录（`config/` 与 `log/` 会保留），
若有新增依赖重新运行一次 `setup_engine.bat` 即可。控制台下次启动自动使用新引擎。

## 目录说明

```
engine/
├── engine_manifest.json   引擎版本清单（控制台校验用）
├── setup_engine.bat       首次安装脚本（创建 .venv + 装依赖）
├── requirements.txt       Python 依赖清单
├── gui/                   桥接服务 bridge.py / runner.py / server_daemon.py
├── module/                框架层（设备控制、配置、图像、OCR）
├── tasks/                 各自动化任务实现
├── deploy/                部署与配置工具
├── assets/ bin/           资源与工具
└── config/                配置（首次使用后生成）
```

## 许可

本项目基于 [runhey/OAS](https://github.com/runhey/onmyoji_auto_script) 衍生，遵循 GPL-3.0 许可（见 `LICENSE`）。
