# -*- coding: utf-8 -*-
"""YYJio（痒痒鸡）桥接服务。

职责边界（UI 与引擎解耦的关键层）：
- 对 UI：只暴露领域模型（实例 / 任务 / 计划 / 运行），REST + SSE，不泄露引擎内部结构；
- 对引擎：读写 config/*.json、以子进程方式调用 gui/runner.py、聚合日志与状态。

启动：
    .venv\\Scripts\\python.exe -X utf8 -B gui/bridge.py --port 22390
"""

from __future__ import annotations

import argparse
import atexit
import base64
import copy
import hashlib
import json
import os
import queue
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

_GUI_DIR = str(Path(__file__).resolve().parent)
if _GUI_DIR not in sys.path:  # 直接跑 gui/bridge.py 时脚本目录不一定在 sys.path
    sys.path.insert(0, _GUI_DIR)
import minitouch_setup  # noqa: E402  （随安装包带的 minitouch 兜底）
ROOT = Path(__file__).resolve().parent.parent

CONFIG_DIR = ROOT / "config"
STATIC_DIR = Path(__file__).resolve().parent / "static"
PLAN_FILE = CONFIG_DIR / "plans.json"
FLOW_FILE = CONFIG_DIR / "gui_flows.json"
FLOW_LIBRARY_FILE = CONFIG_DIR / "gui_flow_library.json"
PROFILE_FILE = CONFIG_DIR / "gui_profiles.json"
# 每台模拟器用过的「操作模拟器方式」：换绑/重建实例时按 serial 还原
DEVICE_MODE_FILE = CONFIG_DIR / "gui_device_mode.json"
# 账号头像：绑定账号时从游戏画面里裁下来的圆形头像，按实例名存一份
AVATAR_DIR = CONFIG_DIR / "gui_avatars"
CUSTOM_CLICK_FILE = CONFIG_DIR / "gui_custom_clicks.json"
# 任务包在线源：GitHub Pages 上的 index.json（内容由 TesBot/YYJio-Tasks 仓库生成）
TASK_SOURCE_URL = "https://tesbot.github.io/YYJio-Tasks/index.json"
TASK_PACKAGE_CATEGORY = "自定义任务"
SCHEMA_CACHE = Path(__file__).resolve().parent / ".cache" / "schema.json"
# 便携整包布局：bridge 由打包内嵌的 Python 直接运行，子进程一律用当前解释器；
# 开发布局：bridge 运行于 .venv，sys.executable 同样指向 venv 的 python.exe。
PYTHON = Path(sys.executable)
# adb.exe 定位：优先当前解释器的 site-packages（便携包/开发 venv 通用），
# 找不到再回退到仓库内 .venv 的旧位置。
import sysconfig as _sysconfig  # noqa: E402
_purelib = Path(_sysconfig.get_paths()["purelib"])
ADB_CANDIDATES = [
    _purelib / "adbutils" / "binaries" / "adb.exe",
    ROOT / ".venv" / "Lib" / "site-packages" / "adbutils" / "binaries" / "adb.exe",
]
ADB = next((p for p in ADB_CANDIDATES if p.exists()), ADB_CANDIDATES[-1])

sys.path.insert(0, str(ROOT))
from gui import catalog  # noqa: E402
from gui import taskpack  # noqa: E402

# ── 品牌与版本 ──
APP_NAME = "YYJio"
APP_VERSION = "1.1.4"
APP_BUILD = "yyjio"
GITHUB_REPO = "TesBot/YYS-OAS-Bot"
RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
# 只看改名之后（1.0.0 起）的发布：更早的 tag 属于旧品牌 OAS Studio，版本号更高但不能比
ASSET_PREFIX = "YYJio-Setup-"

app = FastAPI(title=f"{APP_NAME} Bridge", version=APP_VERSION)

_CONFIG_LOCK = threading.RLock()
_RUNS: dict[str, dict] = {}
_RUN_LOCK = threading.RLock()
_SCHEMA_LOCK = threading.RLock()
_FLOW_LOCKS: dict[str, threading.Lock] = {}

_SERVER_DAEMON_PID = ROOT / "log" / "gui" / "server_daemon.pid"


# ────────────────────────── 服务常驻守护 ──────────────────────────
# 每个编排步骤都是一个新的 runner 子进程；若不在步骤之间保留图像/OCR 服务，
# 每步都要重新预热（OCR 模型加载约 6 秒）。守护进程让两个服务随应用启动
# 常驻、被所有步骤复用，bridge 退出时整体回收。

def _kill_pid_tree(pid: int) -> None:
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, timeout=15)
    except Exception:  # noqa: BLE001 - PID 已不存在等情况直接忽略
        pass


def _start_server_daemon() -> None:
    """拉起（或复用）图像/OCR 服务守护进程；bridge 退出时负责回收。"""
    import atexit

    _SERVER_DAEMON_PID.parent.mkdir(parents=True, exist_ok=True)

    # 清理上次异常退出留下的守护进程
    if _SERVER_DAEMON_PID.exists():
        try:
            _kill_pid_tree(int(_SERVER_DAEMON_PID.read_text(encoding="utf-8").strip()))
        except Exception:  # noqa: BLE001
            pass
        try:
            _SERVER_DAEMON_PID.unlink()
        except OSError:
            pass

    log_path = ROOT / "log" / "gui" / "server_daemon.log"
    creationflags = 0
    if os.name == "nt":
        # CREATE_NO_WINDOW：不弹黑框。子进程默认不随父进程退出，
        # 生命周期由 PID 文件 + atexit taskkill 管理。
        # （不要用 DETACHED_PROCESS——它会新建一个控制台窗口弹出来。）
        creationflags = subprocess.CREATE_NO_WINDOW
    fh = open(log_path, "a", encoding="utf-8", errors="replace")  # noqa: SIM115 - 随守护进程存续
    try:
        proc = subprocess.Popen(
            [str(PYTHON), "-X", "utf8", "-B", str(ROOT / "gui" / "server_daemon.py"),
             "--parent-pid", str(os.getpid())],
            cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, creationflags=creationflags)
    except Exception:  # noqa: BLE001 - 守护进程起不来时回退为旧行为（runner 自起自停）
        fh.close()
        return
    _SERVER_DAEMON_PID.write_text(str(proc.pid), encoding="utf-8")
    print(f"Server daemon started (pid={proc.pid}); image/ocr services will stay warm")

    def _cleanup() -> None:
        if _SERVER_DAEMON_PID.exists():
            try:
                _kill_pid_tree(int(_SERVER_DAEMON_PID.read_text(encoding="utf-8").strip()))
            except Exception:  # noqa: BLE001
                pass
            try:
                _SERVER_DAEMON_PID.unlink()
            except OSError:
                pass

    atexit.register(_cleanup)



# ────────────────────────── 工具函数 ──────────────────────────

def _instance_files() -> list[Path]:
    if not CONFIG_DIR.exists():
        return []
    # 注意：gui_*.json 是控制台自己的状态文件（账号资料/编排表等），
    # 不是引擎实例配置，必须排除，否则会被当成账号列出来。
    return sorted(p for p in CONFIG_DIR.glob("*.json")
                  if p.name not in ("plans.json", "template.json")
                  and not p.name.startswith("gui_")
                  and not p.name.endswith(".bak"))


def _instance_path(name: str) -> Path:
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(400, "非法实例名")
    path = CONFIG_DIR / f"{name}.json"
    if not path.exists():
        raise HTTPException(404, f"实例不存在: {name}")
    return path


def _load(path: Path) -> dict:
    with _CONFIG_LOCK:
        try:
            # utf-8-sig：有的编辑器/脚本会写 BOM，严格 utf-8 会直接报错
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"配置解析失败 {path.name}: {exc}") from exc


def _save(path: Path, data: dict, backup: bool = True) -> None:
    with _CONFIG_LOCK:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        if backup and path.exists():
            shutil.copy(path, path.with_suffix(".json.bak"))
        tmp.replace(path)


def _deep_merge(base: dict, patch: dict) -> dict:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _adb_devices() -> list[str]:
    if not ADB.exists():
        return []
    try:
        out = subprocess.run([str(ADB), "devices"], capture_output=True, text=True, timeout=8)
        lines = [ln.strip() for ln in out.stdout.splitlines()[1:] if ln.strip()]
        return [ln.split("\t")[0] for ln in lines if "\tdevice" in ln]
    except Exception:  # noqa: BLE001
        return []


# MuMu 多开的 adb 端口：实例 0 从 16384 起，每个实例 +32。
# 引擎侧实例编号推算（handle.py）支持到 32 个，这里保守探测前 16 个；
# 并发 connect，不在线的端口不拖慢刷新。
_MUMU_ADB_PORTS = [16384 + 32 * i for i in range(16)]


def _adb_reconnect_known(existing: set[str] | None = None) -> None:
    """主动重连已知的模拟器地址。

    MuMu 重启后 adb 连接会掉（`adb devices` 为空），只列在线设备的
    「刷新」就永远扫不到。这里对已绑定实例的 serial 与 MuMu 常用端口
    做一次 `adb connect`，把掉线的模拟器拉回列表。

    注意两点：
    - MuMu 端口兜底不能只在「没有任何实例」时做——用户常常在已绑定 1 个
      实例之后又新开第 2、3 个实例，那些端口的设备同样需要 connect 才会
      出现在列表里。
    - 连不上的地址 adb 要等约 2s 才返回，8 个端口串行就是十几秒。所以并发
      发起，并且跳过已经在线（``existing``）的地址。
    """
    from concurrent.futures import ThreadPoolExecutor

    serials = set(f"127.0.0.1:{p}" for p in _MUMU_ADB_PORTS)
    for path in _instance_files():
        try:
            serial = (_load(path).get("script") or {}).get("device", {}).get("serial")
            if isinstance(serial, str) and ":" in serial:
                serials.add(serial)
        except Exception:  # noqa: BLE001
            continue
    if existing:
        serials -= set(existing)
    if not serials:
        return

    def _connect_one(serial: str) -> None:
        try:
            subprocess.run([str(ADB), "connect", serial],
                           capture_output=True, timeout=6)
        except Exception:  # noqa: BLE001 - 单个地址连不上不影响其它
            pass

    with ThreadPoolExecutor(max_workers=min(16, len(serials))) as pool:
        list(pool.map(_connect_one, sorted(serials)))


def _task_entries(cfg: dict) -> list[dict]:
    items = []
    for key, value in cfg.items():
        if not isinstance(value, dict) or "scheduler" not in value:
            continue
        sched = value.get("scheduler") or {}
        name, category = catalog.task_display(key)
        items.append({
            "key": key,
            "name": name,
            "category": category,
            "desc": catalog.task_desc(key),
            "team": catalog.task_team(key),
            "enabled": bool(sched.get("enable")),
            "next_run": sched.get("next_run"),
            "priority": sched.get("priority", 5),
            "sections": [k for k in value.keys() if k != "scheduler"],
            "summary": _task_summary(value),
        })
    items.sort(key=lambda x: (catalog.CATEGORY_ORDER.index(x["category"])
                              if x["category"] in catalog.CATEGORY_ORDER else 99, x["name"]))
    return items


def _task_summary(section: dict, limit: int = 3) -> list[str]:
    """从任务配置里挑出对玩家最有意义的几个值，供编排表行内摘要使用。"""
    flat: dict[str, Any] = {}
    for sub_key, sub in section.items():
        if isinstance(sub, dict):
            for k, v in sub.items():
                flat.setdefault(k, v)
    out: list[str] = []
    for key in catalog.SUMMARY_KEYS:
        if key not in flat:
            continue
        value = flat[key]
        if isinstance(value, bool):
            if not value:
                continue
            if key == "preset_enable":
                group = flat.get("preset_group", 1)
                team = flat.get("preset_team", 1)
                out.append(f"预设 {group}-{team}")
                continue
            out.append(key.replace("_", " "))
        elif isinstance(value, (int, float)):
            label = {"limit_count": "次数", "boss_number": "鬼王数", "run_count": "局数",
                     "challenge_count": "次数", "completion_count": "完成数",
                     "preset_group": "组", "preset_team": "队"}.get(key, key)
            out.append(f"{label} {value:g}" if isinstance(value, float) else f"{label} {value}")
        else:
            out.append(str(value))
        if len(out) >= limit:
            break
    return out[:limit]


def _team_status_path(cfg: dict, task: str) -> str | None:
    """返回 `user_status` 在该任务配置中的相对路径（如 evo_zone_config.user_status）。"""
    section = cfg.get(task)
    if not isinstance(section, dict):
        return None
    for sub_key, sub in section.items():
        if isinstance(sub, dict) and "user_status" in sub:
            return f"{sub_key}.user_status"
    return None



# ────────────────────────── 元数据 ──────────────────────────

@app.get("/api/catalog")
def get_catalog():
    def _entry(k: str, name: str, cat: str, desc: str, team: bool):
        cat = catalog.CATEGORY_ALIAS.get(cat, cat)
        return {"key": k, "name": name, "category": cat, "desc": desc, "team": team,
                "hidden": cat in catalog.HIDDEN_CATEGORIES or k in catalog.HIDDEN_TASKS}

    package_tasks = _package_task_entries()
    categories = [{"key": c, **catalog.CATEGORY_META.get(c, {})} for c in catalog.CATEGORY_ORDER]
    # 这个分类一直在（就算还没装任何任务包）：用户要先能找到入口，
    # 才能在里面点「在线刷新 / 从文件导入」。
    categories.append({"key": TASK_PACKAGE_CATEGORY,
                       "cat": "从任务包安装的自定义点击方案，可继续加到任意编排里。"})
    return {
        "tasks": [_entry(k, v[0], v[1], v[2], v[3]) for k, v in catalog.TASK_META.items()]
        + [dict(t, pseudo=True, hidden=False,
                category=catalog.CATEGORY_ALIAS.get(t.get("category", ""), t.get("category", "")))
           for t in catalog.PSEUDO_TASKS]
        + package_tasks,
        "categories": categories,
        "issues": catalog.KNOWN_ISSUES,
        "field_hints": [{"match": m, "hint": h} for m, h in catalog.FIELD_HINTS],
        "summary_keys": catalog.SUMMARY_KEYS,
        "team_tasks": sorted(catalog.TEAM_TASKS),
    }


# 一次 shell 往返取齐设备身份：同一台安卓实例可能同时以两个传输名出现在
# `adb devices` 里（MuMu 12 实测：`emulator-5554` 走模拟器本地控制台端口、
# `127.0.0.1:16384` 走多开 adb 端口）。只看 serial 会把它们当成两台设备，
# 于是「只开了一个模拟器，却多出一条未绑定的 emulator-XXXX」。
# boot_id 是内核每次启动生成的 UUID，与传输方式无关，是判定「同一台」最可靠的依据；
# 取不到时退到 ro.serialno，再退到 serial 本身（不合并）。
_PROBE_SHELL = (
    "echo _OAS_B; cat /proc/sys/kernel/random/boot_id 2>/dev/null; "
    "echo _OAS_M; getprop ro.product.model; "
    "echo _OAS_S; getprop ro.serialno; "
    "echo _OAS_W; wm size; "
    "echo _OAS_D; wm density"
)


def _probe_device(serial: str) -> dict:
    """读取单台设备的身份与显示参数；任何异常都退化为空，由调用方兜底。"""
    try:
        out = subprocess.run([str(ADB), "-s", serial, "shell", _PROBE_SHELL],
                             capture_output=True, text=True, timeout=8)
    except Exception:  # noqa: BLE001 - 设备掉线/ADB 卡住都不该拖垮整次扫描
        return {}
    # 不看退出码：复合命令的退出码取自最后一条（wm 在某些镜像上不存在），
    # 但前面的 boot_id 依然有效，能读到什么就用什么。
    if not (out.stdout or "").strip():
        return {}
    sections: dict[str, list[str]] = {}
    current = None
    for raw in (out.stdout or "").splitlines():
        line = raw.strip()
        if line.startswith("_OAS_") and len(line) == 6:
            current = line[5:]
            sections[current] = []
            continue
        if current:
            sections[current].append(line)

    def pick(key: str) -> str:
        return next((v for v in sections.get(key, []) if v), "")

    # `wm size` 可能同时给出 Physical/Override 两行，取第一行（物理分辨率）
    size = pick("W")
    density = pick("D")
    return {
        "boot_id": pick("B"),
        "model": pick("M"),
        "serialno": pick("S"),
        "resolution": size.split(":")[-1].strip() or None,
        "density": density.split(":")[-1].strip() or None,
    }


def _probe_identity(serial: str) -> str:
    """只读 boot_id：已绑定设备只需要这个来做别名合并，不必再问型号/分辨率。"""
    try:
        out = subprocess.run([str(ADB), "-s", serial, "shell",
                              "cat /proc/sys/kernel/random/boot_id"],
                             capture_output=True, text=True, timeout=5)
    except Exception:  # noqa: BLE001
        return ""
    return (out.stdout or "").strip()


def _device_detail(serials: list[str], light: set[str] | None = None) -> list[dict]:
    """把 serial 列表补全为带型号/分辨率、且标注已绑定实例的设备详情。

    adb 会把同一台实例以多个传输名重复列出，这里按 boot_id 合并成一行：
    保留已绑定的那一个 serial（否则实例卡片的设备信息会对不上），其次保留
    多开用的 TCP 地址，最后才是 `emulator-*`；被合并掉的写入 ``aliases``。
    """
    bound: dict[str, str] = {}
    for path in _instance_files():
        cfg = _load(path)
        serial = ((cfg.get("script") or {}).get("device") or {}).get("serial")
        if serial:
            bound[serial] = path.stem

    light = light or set()
    groups: dict[str, list[dict]] = {}
    for serial in serials:
        # 已绑定的账号只查身份（boot_id），型号/分辨率卡片上已经有了
        info = {"boot_id": _probe_identity(serial)} if serial in light else _probe_device(serial)
        identity = info.get("boot_id") or info.get("serialno") or serial
        groups.setdefault(identity, []).append({
            "serial": serial,
            "model": info.get("model") or None,
            "resolution": info.get("resolution"),
            "density": info.get("density"),
        })

    def rank(item: dict) -> tuple[int, int]:
        serial = item["serial"]
        # 已绑定优先（卡片按 inst.serial 找设备）；其次 TCP 地址，最后 emulator-*
        transport = 0 if serial.startswith("127.0.0.1:") else (
            2 if serial.startswith("emulator-") else 1)
        return (0 if serial in bound else 1, transport)

    detail = []
    for items in groups.values():
        items.sort(key=rank)
        primary = items[0]
        aliases = [item["serial"] for item in items[1:]]
        primary["bound_to"] = next(
            (bound[s] for s in [primary["serial"], *aliases] if s in bound), None)
        if aliases:
            primary["aliases"] = aliases
        detail.append(primary)
    # 已绑定的排前面，其余按 serial 稳定排序
    detail.sort(key=lambda d: (d["bound_to"] is None, d["serial"]))
    return detail


@app.get("/api/devices")
def list_devices(probe: bool = False, skip: str = ""):
    """实时扫描 adb 在线设备，供「账号绑定」选择。

    模拟器重启后 adb 连接常常是掉的（devices 为空），此时先按已知
    serial / MuMu 常用端口主动 connect 一次再扫。

    ``probe=1``：不论当前列表是否为空，都先做一轮主动 connect。用户点了
    「刷新设备」就传这个，因为新开的 MuMu 实例不会自动注册到 adb server。

    ``skip``：逗号分隔的 serial，这些设备已经绑定好了，只返回名字不再逐台
    probe（型号/分辨率要跑三条 shell，绑着的号没必要每次都问一遍）。账号卡
    各自的「刷新状态」会单独查那一台。
    """
    known = {s.strip() for s in skip.split(",") if s.strip()}
    if probe:
        _adb_reconnect_known(set(_adb_devices()))
    devices = _adb_devices()
    if not devices:
        _adb_reconnect_known()
        devices = _adb_devices()
    detail = _device_detail(devices, light=known)
    # 已绑定的那几台标成 cached：前端据此只统计「新设备」，也不再让它们
    # 在未绑定列表里重复出现（同一台模拟器常有 emulator-xxxx 与 TCP 两个名字，
    # 只有拿到 boot_id 才能合并，所以这里仍然读一次身份）。
    for one in detail:
        names = {one.get("serial"), *(one.get("aliases") or [])}
        if names & known:
            one["cached"] = True
    return {"devices": detail, "count": len(detail), "skipped": sorted(known)}


@app.get("/api/instances/{name}/status")
def instance_status(name: str):
    """只查这一台：连上了没 / 型号 / 分辨率。账号卡上的「刷新状态」用。"""
    path = CONFIG_DIR / f"{name}.json"
    if not path.exists():
        raise HTTPException(404, "没有这个账号")
    serial = ((_load(path).get("script") or {}).get("device") or {}).get("serial")
    if not serial:
        raise HTTPException(400, "这个账号还没有绑定模拟器")
    online = serial in set(_adb_devices())
    info = _probe_device(serial) if online else {}
    return {"ok": True, "online": online, "serial": serial,
            "model": info.get("model") or None, "resolution": info.get("resolution") or "",
            "density": info.get("density")}


@app.post("/api/devices/connect")
def connect_device(payload: dict = Body(...)):
    serial = (payload.get("serial") or "").strip()
    if not serial:
        raise HTTPException(400, "缺少 serial")
    try:
        out = subprocess.run([str(ADB), "connect", serial], capture_output=True, text=True, timeout=12)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"adb connect 失败: {exc}") from exc
    text = (out.stdout or "").strip() or (out.stderr or "").strip()
    ok = "connected to" in text
    return {"ok": ok, "output": text, "devices": _device_detail(_adb_devices())}


# ────────────────────────── 账号档案（GUI 侧元数据） ──────────────────────────

def _load_profiles() -> dict:
    if not PROFILE_FILE.exists():
        return {}
    try:
        data = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save_profiles(data: dict) -> None:
    PROFILE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@app.get("/api/profiles")

def _load_device_modes() -> dict:
    data = _load(DEVICE_MODE_FILE) if DEVICE_MODE_FILE.exists() else {}
    return data if isinstance(data, dict) else {}


def _save_device_modes(data: dict) -> None:
    _save(DEVICE_MODE_FILE, data)


def _remember_device_mode(device: dict) -> None:
    """记住这台模拟器选的方式，解绑后重新绑定同一个 serial 时还原。"""
    serial = str(device.get("serial") or "")
    shot = device.get("screenshot_method")
    ctrl = device.get("control_method")
    if not serial or not shot or not ctrl:
        return
    modes = _load_device_modes()
    modes[serial] = {"screenshot_method": shot, "control_method": ctrl}
    _save_device_modes(modes)

def list_profiles():
    return {"profiles": _load_profiles()}


@app.put("/api/profiles/{name}")
def put_profile(name: str, payload: dict = Body(...)):
    profiles = _load_profiles()
    current = profiles.get(name) or {}
    for key in ("nickname", "server", "role_id", "primary", "note"):
        if key in payload:
            current[key] = payload[key]
    profiles[name] = current
    _save_profiles(profiles)
    return {"ok": True, "profile": current}


@app.delete("/api/profiles/{name}")
def delete_profile(name: str):
    profiles = _load_profiles()
    profiles.pop(name, None)
    _save_profiles(profiles)
    return {"ok": True}



def _avatar_stamp(name: str) -> int:
    """头像文件的修改时间，前端拼在 URL 后面当版本号，避免沿用旧图。"""
    try:
        return int(_avatar_path(name).stat().st_mtime)
    except OSError:
        return 0

def _avatar_path(name: str) -> Path:
    return AVATAR_DIR / f"{name}.png"


# 识别昵称/头像要导入整个引擎并加载 OCR 模型，冷启动 7 秒左右。
# 这里养一个常驻子进程，引擎和模型只加载一次，之后每次识别 1 秒左右。
_SCAN_LOCK = threading.Lock()
_SCAN_WORKER: dict = {"proc": None}


def _scan_worker_stop() -> None:
    proc = _SCAN_WORKER.get("proc")
    _SCAN_WORKER["proc"] = None
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.kill()
    except Exception:  # noqa: BLE001 - 已经退出就算了
        pass


def _scan_worker_start():
    cmd = [str(PYTHON), "-X", "utf8", "-B", str(ROOT / "gui" / "profile_scan.py"), "--serve"]
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.Popen(cmd, cwd=str(ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                            errors="replace", bufsize=1, **kwargs)
    _SCAN_WORKER["proc"] = proc
    return proc


atexit.register(_scan_worker_stop)


def _scan_worker_call(payload: dict, timeout: float = 60.0) -> dict:
    """把一条请求丢给常驻进程，拿回一条结果。进程挂了会抛 RuntimeError 由调用方兜底。"""
    with _SCAN_LOCK:
        proc = _SCAN_WORKER.get("proc")
        if proc is None or proc.poll() is not None:
            proc = _scan_worker_start()
        try:
            proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            proc.stdin.flush()
        except Exception as exc:  # noqa: BLE001
            _scan_worker_stop()
            raise RuntimeError(f"识别进程写入失败：{exc}") from exc

        box: queue.Queue = queue.Queue()

        def _reader() -> None:
            try:
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        box.put(None)
                        return
                    line = line.strip()
                    if not (line.startswith("{") and line.endswith("}")):
                        continue  # 引擎日志混在 stdout 里，跳过
                    try:
                        data = json.loads(line)
                    except Exception:  # noqa: BLE001
                        continue
                    if isinstance(data, dict) and "ok" in data:
                        box.put(data)
                        return
            except Exception:  # noqa: BLE001
                box.put(None)

        threading.Thread(target=_reader, daemon=True).start()
        try:
            data = box.get(timeout=timeout)
        except queue.Empty:
            _scan_worker_stop()
            raise HTTPException(504, "识别超时：模拟器可能没连上，或画面还没加载完")
        if data is None:
            _scan_worker_stop()
            raise RuntimeError("识别进程意外退出")
        return data


def _scan_run_once(name: str, out: Path) -> dict:
    """兜底：起一个新进程跑一次（常驻进程不可用时用）。"""
    cmd = [str(PYTHON), "-X", "utf8", "-B", str(ROOT / "gui" / "profile_scan.py"),
           "--config", name, "--out-avatar", str(out)]
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        res = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60, **kwargs)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "识别超时：模拟器可能没连上，或画面还没加载完")

    for line in reversed((res.stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                data = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            return data
    detail = (res.stderr or res.stdout or "").strip()[-300:]
    raise HTTPException(500, "识别失败：" + (detail or "识别脚本没有输出结果"))


@app.post("/api/instances/{name}/profile-scan")
def scan_profile(name: str):
    """抓一张当前画面，认出游戏昵称并裁下圆形头像，写进账号资料。

    绑定账号时前端自动调用；「编辑资料」里也可以手动重新识别。
    """
    _instance_path(name)
    out = _avatar_path(name)
    # 先删旧的：这次认不出来就回退到首字母，不能继续显示上一次那张脸
    out.unlink(missing_ok=True)
    try:
        data = _scan_worker_call({"config": name, "out_avatar": str(out)})
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 - 常驻进程起不来时退回一次性进程
        data = _scan_run_once(name, out)
    if not data.get("ok"):
        raise HTTPException(500, str(data.get("error") or "识别失败"))

    profiles = _load_profiles()
    current = profiles.get(name) or {}
    nickname = str(data.get("nickname") or "").strip()
    if nickname:
        current["nickname"] = nickname
    current["avatar"] = str(data.get("avatar") or "")
    profiles[name] = current
    _save_profiles(profiles)
    return {"ok": True, "profile": current, "shot": data.get("shot") or {},
            "texts": data.get("texts") or []}


@app.get("/api/instances/{name}/avatar")
def instance_avatar(name: str):
    """账号头像（PNG，圆外透明）。没有就 404，前端回退到首字母。"""
    path = _avatar_path(name)
    if not path.exists():
        raise HTTPException(404, "还没有头像")
    try:
        stamp = str(int(path.stat().st_mtime))
    except OSError:
        stamp = "0"
    return FileResponse(path, media_type="image/png",
                        headers={"Cache-Control": "no-store, max-age=0",
                                 "ETag": f'"{stamp}"'})


# ────────────────────────── 任务表单 schema ──────────────────────────

def _load_schema_cache() -> dict:
    if not SCHEMA_CACHE.exists():
        return {}
    try:
        return json.loads(SCHEMA_CACHE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


_PROBE = r"""
import json, sys, importlib, pydantic
sys.path.insert(0, r"%ROOT%")
key, folder = sys.argv[1], sys.argv[2]
try:
    m = importlib.import_module("tasks.%s.config" % folder)
    cls = getattr(m, folder, None)
    if cls is None:
        cands = [o for n, o in vars(m).items()
                 if isinstance(o, type) and issubclass(o, pydantic.BaseModel)]
        cls = cands[-1] if cands else None
    if cls is None:
        raise RuntimeError("no config model")
    print("@@SCHEMA@@" + json.dumps(cls.model_json_schema(), ensure_ascii=False))
except Exception as exc:
    print("@@SCHEMA@@" + json.dumps({"error": "%s: %s" % (type(exc).__name__, exc)},
                                    ensure_ascii=False))
"""


def _folder_for(key: str) -> str:
    target = key.replace("_", "").lower()
    for path in (ROOT / "tasks").iterdir():
        if path.is_dir() and path.name.replace("_", "").lower() == target:
            return path.name
    return "".join(part.capitalize() for part in key.split("_"))


def _task_schema(key: str) -> dict:
    with _SCHEMA_LOCK:
        cache = _load_schema_cache()
        if key in cache:
            return cache[key]
        code = _PROBE.replace("%ROOT%", str(ROOT))
        try:
            out = subprocess.run([str(PYTHON), "-X", "utf8", "-B", "-c", code, key, _folder_for(key)],
                                 cwd=str(ROOT), capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=60)
            payload = {"error": "no schema output"}
            for line in out.stdout.splitlines():
                if line.startswith("@@SCHEMA@@"):
                    payload = json.loads(line[len("@@SCHEMA@@"):])
                    break
        except Exception as exc:  # noqa: BLE001
            payload = {"error": f"{type(exc).__name__}: {exc}"}
        cache[key] = payload
        try:
            SCHEMA_CACHE.parent.mkdir(parents=True, exist_ok=True)
            SCHEMA_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return payload


def _i18n() -> dict:
    if _I18N:
        return _I18N
    path = ROOT / "assets" / "i18n" / "zh-CN.json"
    try:
        _I18N.update(json.loads(path.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        pass
    return _I18N


_I18N: dict = {}


@app.get("/api/tasks/{task}/schema")
def task_schema(task: str):
    """返回任务的配置表单描述（字段/类型/枚举/中文说明）。"""
    raw = _task_schema(task)
    if "error" in raw:
        return {"task": task, "error": raw["error"], "sections": []}
    i18n = _i18n()
    defs = raw.get("$defs") or {}
    sections = []
    for name, prop in (raw.get("properties") or {}).items():
        ref = prop.get("$ref")
        if not ref:
            continue
        model = defs.get(ref.split("/")[-1]) or {}
        fields = []
        for fname, fprop in (model.get("properties") or {}).items():
            fields.append(_describe_field(fname, fprop, defs, i18n))
        base = name[:-7] if name.endswith("_config") else name
        section_label = i18n.get(name) or i18n.get(base) or catalog.section_label(name)
        if not any("\u4e00" <= ch <= "\u9fff" for ch in section_label):
            if name == f"{task}_config":
                section_label = catalog.task_display(task)[0] + "设置"
            else:
                section_label = catalog.section_label(name)
        sections.append({
            "key": name,
            "label": section_label,
            "fields": fields,
        })
    return {"task": task, "sections": sections}


def _describe_field(name: str, prop: dict, defs: dict, i18n: dict) -> dict:
    ref = prop.get("$ref")
    enum = prop.get("enum")
    ftype = prop.get("type")
    if ref:
        model = defs.get(ref.split("/")[-1]) or {}
        enum = model.get("enum") or enum
        ftype = model.get("type") or ftype
    if enum and not ftype:
        ftype = "string"

    def has_cjk(text: str) -> bool:
        return any("\u4e00" <= ch <= "\u9fff" for ch in text or "")

    desc = prop.get("description") or ""
    if desc.endswith("_help") and desc not in i18n:
        desc = ""
    title = prop.get("title") or ""
    label = i18n.get(name) or catalog.field_label(name)
    if not has_cjk(label) and has_cjk(title):
        label = title
    hint = (i18n.get(f"{name}_help") or (desc if has_cjk(desc) else "")
            or catalog.field_note(name))
    return {
        "key": name,
        "label": label,
        "type": ftype or ("string" if enum else "object"),
        "enum": enum,
        "enum_map": {str(v): catalog.enum_label(v) for v in (enum or [])},
        "default": prop.get("default"),
        "hint": hint,
        "min": prop.get("minimum"),
        "max": prop.get("maximum"),
    }



@app.get("/api/version")
def version():
    """安装包版本。升级后用来确认用户实际跑的是哪一份 bridge，而不是旧包。"""
    # 与控制台版本对齐：这个端点就是用来确认用户实际跑的是哪一份 bridge 的
    return {"version": APP_VERSION, "build": APP_BUILD}


def _version_tuple(text: str) -> tuple:
    parts = []
    for piece in str(text).strip().lstrip("vV").split("."):
        digits = re.sub(r"\D", "", piece)
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


@app.get("/api/check-update")
def check_update():
    """查 GitHub Releases 有没有比当前更新的版本（只认同品牌安装包）。"""
    current = APP_VERSION
    result = {
        "ok": True,
        "current": current,
        "latest": current,
        "has_update": False,
        "url": RELEASES_URL,
        "name": "",
        "notes": "",
        "published": "",
        "source": f"https://api.github.com/repos/{GITHUB_REPO}/releases",
    }
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=20"
    headers = {
        "User-Agent": f"{APP_NAME}/{APP_VERSION}",
        "Accept": "application/vnd.github+json",
    }
    # 优先用 requests：它走系统代理且带连接复用，实测 0.6s；
    # 而 urllib 在这台机器上要 20s（读响应被拖慢），只在没有 requests 时兜底。
    try:
        try:
            import requests as _requests
        except Exception:  # noqa: BLE001
            _requests = None
        if _requests is not None:
            resp = _requests.get(url, headers=headers, timeout=8)
            resp.raise_for_status()
            releases = resp.json()
        else:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=12) as response:
                releases = json.loads(response.read().decode("utf-8"))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - 网络问题一律回给前端提示
        raise HTTPException(502, f"连不上 GitHub（{exc.__class__.__name__}）：{exc}")

    best = None
    best_key = _version_tuple(current)
    for release in releases or []:
        if release.get("draft"):
            continue
        names = " ".join(str(a.get("name") or "") for a in (release.get("assets") or []))
        if ASSET_PREFIX not in names:
            continue  # 旧品牌（OAS Studio）的发布不参与比较
        tag = str(release.get("tag_name") or "")
        key = _version_tuple(tag)
        if key > best_key:
            best_key = key
            best = release

    if best is not None:
        result.update({
            "has_update": True,
            "latest": ".".join(str(x) for x in best_key),
            "url": best.get("html_url") or RELEASES_URL,
            "name": best.get("name") or best.get("tag_name") or "",
            "notes": (best.get("body") or "")[:800],
            "published": best.get("published_at") or "",
        })
    return result


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "pid": os.getpid(),
        "root": str(ROOT),
        "python": PYTHON.exists(),
        "adb": ADB.exists(),
        "configs": [p.stem for p in _instance_files()],
        "devices": _adb_devices(),
        "time": datetime.now().isoformat(timespec="seconds"),
    }


# ────────────────────────── 实例 ──────────────────────────

@app.get("/api/instances")
def list_instances():
    devices = set(_adb_devices())
    profiles = _load_profiles()
    flows = _load_flows()
    out = []
    for path in _instance_files():
        cfg = _load(path)
        device = (cfg.get("script") or {}).get("device") or {}
        serial = device.get("serial", "")
        gg = cfg.get("global_game") or {}
        costume = ((gg.get("costume_config") or {}).get("costume_main_type")) or ""
        if isinstance(costume, list):  # 兼容历史版本写入的候选列表，取首个
            costume = costume[0] if costume else ""
        serial_online = serial in devices
        profile = profiles.get(path.stem) or {}
        out.append({
            "name": path.stem,
            "nickname": profile.get("nickname") or path.stem,
            "server": profile.get("server") or "",
            "role_id": profile.get("role_id") or "",
            "avatar": profile.get("avatar") or "",
            "avatar_at": _avatar_stamp(path.stem),
            "primary": bool(profile.get("primary")),
            "note": profile.get("note") or "",
            "serial": serial,
            "online": serial_online,
            "screenshot_method": device.get("screenshot_method"),
            "control_method": device.get("control_method"),
            "package_name": device.get("package_name"),
            "emulatorinfo_name": device.get("emulatorinfo_name"),
            "costume_main_type": costume,
            "running_task": cfg.get("running_task"),
            "flows": [f["name"] for f in flows if path.stem in (f.get("accounts") or [])],
            "enabled_tasks": sum(1 for v in cfg.values()
                                 if isinstance(v, dict) and (v.get("scheduler") or {}).get("enable")),
        })
    return {"devices": sorted(devices), "instances": out}


@app.post("/api/instances")
def create_instance(payload: dict = Body(...)):
    name = (payload.get("name") or "").strip()
    serial = (payload.get("serial") or "").strip()
    if not name or not serial:
        raise HTTPException(400, "实例名与 adb 地址必填")
    target = CONFIG_DIR / f"{name}.json"
    if target.exists():
        raise HTTPException(409, f"实例已存在: {name}")

    sources = _instance_files()
    if not sources:
        # 全新引擎还没有任何实例：回退到随引擎分发的空白模板
        fallback = CONFIG_DIR / "template.json"
        if not fallback.exists():
            raise HTTPException(400, "没有可用模板配置，请先运行一次引擎生成 config/oas1.json")
        sources = [fallback]
    template = _load(sources[0])
    template["config_name"] = name
    device = template.setdefault("script", {}).setdefault("device", {})
    device["serial"] = serial
    # 截图与操作方式默认跟着引擎走（auto 测速 + minitouch）。
    # 这台模拟器以前改过（例如改成 ADB），重新绑定时按 serial 还原，不会被重置回默认。
    # 个别电脑上默认方案会抓错画面或起不来，那时在总览里把「操作模拟器方式」改成 ADB。
    saved_mode = _load_device_modes().get(str(serial)) or {}
    # 引擎默认先跑一次「截图测速」，把最快的方式写死进实例配置：个别电脑上会选中
    # 窗口/IPC 抓屏，抓到的却是模拟器桌面。默认 ADB 截图 + ADB 操作，最稳。
    device.setdefault("screenshot_method", "auto")
    device["control_method"] = "minitouch"
    if saved_mode.get("screenshot_method"):
        device["screenshot_method"] = saved_mode["screenshot_method"]
    if saved_mode.get("control_method"):
        device["control_method"] = saved_mode["control_method"]
    for key, value in (payload.get("device") or {}).items():
        device[key] = value
    _save(target, template)
    return {"ok": True, "name": name}


@app.patch("/api/instances/{name}")
def update_instance(name: str, payload: dict = Body(...)):
    path = _instance_path(name)
    cfg = _load(path)
    device = cfg.setdefault("script", {}).setdefault("device", {})
    changed = payload.get("device") or {}
    for key, value in changed.items():
        device[key] = value
    if "screenshot_method" in changed or "control_method" in changed:
        _remember_device_mode(device)
    costume = payload.get("costume_main_type")
    if isinstance(costume, list):  # 兼容旧前端传来的候选列表，取首个
        costume = costume[0] if costume else None
    if isinstance(costume, str) and costume:
        gg = cfg.setdefault("global_game", {}).setdefault("costume_config", {})
        gg["costume_main_type"] = costume
    _save(path, cfg)
    return {"ok": True}


@app.delete("/api/instances/{name}")
def delete_instance(name: str):
    """解绑账号。允许删掉最后一个账号（删空后总览显示空态，可重新绑定）。"""
    path = _instance_path(name)

    # 1. 先停掉该实例正在跑的任务，避免删了配置子进程还在操作模拟器
    for run in list(_RUNS.values()):
        if run.get("instance") != name or run.get("status") not in ("running", "pending"):
            continue
        proc = run.get("proc")
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
        run["status"] = "stopped"
        run["finished"] = datetime.now().isoformat(timespec="seconds")

    # 2. 从账号资料里移除
    profiles = _load_profiles()
    if profiles.pop(name, None) is not None:
        _save_profiles(profiles)

    # 3. 从编排表里摘掉引用（编排表本身保留，用户可再绑定新账号）
    flows = _load_flows()
    touched = False
    for flow in flows:
        accounts = flow.get("accounts") or []
        if name in accounts:
            flow["accounts"] = [a for a in accounts if a != name]
            touched = True
    if touched:
        _save_flows(flows)

    # 4. 删除配置（解绑不保留备份，顺带清掉历史 .bak / .tmp 与头像）
    path.unlink(missing_ok=True)
    for suffix in (".json.bak", ".json.tmp"):
        try:
            (CONFIG_DIR / f"{name}{suffix}").unlink(missing_ok=True)
        except OSError:
            pass
    try:
        _avatar_path(name).unlink(missing_ok=True)
    except OSError:
        pass
    return {"ok": True, "remaining": len(_instance_files())}


@app.post("/api/instances/unbind-all")
def unbind_all():
    """清空全部实例绑定与运行状态；任务编排 / 方案库 / 账号资料保持不变。"""
    # 先停循环作业，否则 worker 会在下一轮重新对已删除的实例写配置、拉进程
    for job_id, job in list(_JOBS.items()):
        if job["status"] == "running":
            stop_job(job_id)
    removed = []
    for path in _instance_files():
        name = path.stem
        for run in list(_RUNS.values()):
            if run.get("instance") != name or run.get("status") not in ("running", "pending"):
                continue
            proc = run.get("proc")
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            run["status"] = "stopped"
            run["finished"] = datetime.now().isoformat(timespec="seconds")
        path.unlink(missing_ok=True)
        for suffix in (".json.bak", ".json.tmp"):
            try:
                (CONFIG_DIR / f"{name}{suffix}").unlink(missing_ok=True)
            except OSError:
                pass
        removed.append(name)
        try:
            _avatar_path(name).unlink(missing_ok=True)
        except OSError:
            pass

    # 编排表与自定义方案库保留（任务是通用模板），但必须把这些账号从编排的绑定里摘掉：
    # 否则重新绑定同名实例（实例名会从 oas1 开始复用）时，旧编排会被当成绑在新设备上。
    if removed:
        flows = _load_flows()
        touched = False
        for flow in flows:
            accounts = flow.get("accounts") or []
            kept = [a for a in accounts if a not in removed]
            if len(kept) != len(accounts):
                flow["accounts"] = kept
                touched = True
        if touched:
            _save_flows(flows)
        profiles = _load_profiles()
        dropped = False
        for one in removed:
            if profiles.pop(one, None) is not None:
                dropped = True
        if dropped:
            _save_profiles(profiles)
    return {"ok": True, "removed": removed,
            "kept": ["gui_flows.json", "gui_flow_library.json"]}


@app.post("/api/instances/{name}/test")
def test_instance(name: str):
    path = _instance_path(name)
    cfg = _load(path)
    serial = ((cfg.get("script") or {}).get("device") or {}).get("serial", "")
    devices = _adb_devices()
    if serial not in devices:
        try:
            if ADB.exists():
                subprocess.run([str(ADB), "connect", serial], capture_output=True, timeout=10)
        except Exception:  # noqa: BLE001
            pass
        devices = _adb_devices()
    online = serial in devices
    resolution = None
    if online and ADB.exists():
        try:
            out = subprocess.run([str(ADB), "-s", serial, "shell", "wm", "size"],
                                 capture_output=True, text=True, timeout=8)
            resolution = out.stdout.strip().split(":")[-1].strip() or None
        except Exception:  # noqa: BLE001
            pass
    return {"ok": online, "serial": serial, "online": online, "resolution": resolution,
            "devices": devices}


# ────────────────────────── 任务 ──────────────────────────

@app.get("/api/instances/{name}/tasks")
def list_tasks(name: str):
    cfg = _load(_instance_path(name))
    return {"tasks": _task_entries(cfg)}


@app.get("/api/instances/{name}/tasks/{task}")
def get_task(name: str, task: str):
    cfg = _load(_instance_path(name))
    if task not in cfg or not isinstance(cfg[task], dict):
        raise HTTPException(404, f"任务不存在: {task}")
    return {"task": task, "config": cfg[task]}


@app.put("/api/instances/{name}/tasks/{task}")
def put_task(name: str, task: str, payload: dict = Body(...)):
    path = _instance_path(name)
    cfg = _load(path)
    if task not in cfg or not isinstance(cfg[task], dict):
        raise HTTPException(404, f"任务不存在: {task}")
    _deep_merge(cfg[task], payload.get("config") or {})
    _save(path, cfg)
    return {"ok": True, "config": cfg[task]}


@app.post("/api/instances/{name}/tasks/{task}/enabled")
def set_task_enabled(name: str, task: str, payload: dict = Body(...)):
    path = _instance_path(name)
    cfg = _load(path)
    if task not in cfg or not isinstance(cfg[task], dict):
        raise HTTPException(404, f"任务不存在: {task}")
    enabled = bool(payload.get("enabled"))
    sched = cfg[task].setdefault("scheduler", {})
    sched["enable"] = enabled
    if enabled and not sched.get("next_run"):
        sched["next_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save(path, cfg)
    return {"ok": True, "enabled": enabled}


@app.get("/api/instances/{name}/raw")
def get_raw(name: str):
    return {"config": _load(_instance_path(name))}


@app.put("/api/instances/{name}/raw")
def put_raw(name: str, payload: dict = Body(...)):
    path = _instance_path(name)
    data = payload.get("config")
    if not isinstance(data, dict):
        raise HTTPException(400, "config 必须是对象")
    data["config_name"] = name
    _save(path, data)
    return {"ok": True}


# ────────────────────────── 编排表 ──────────────────────────

def _load_flows() -> list[dict]:
    if not FLOW_FILE.exists():
        return []
    try:
        data = json.loads(FLOW_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("flows") or []
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []


def _save_flows(flows: list[dict]) -> None:
    FLOW_FILE.write_text(json.dumps({"flows": flows}, ensure_ascii=False, indent=2),
                         encoding="utf-8")


def _normalize_wait(value) -> dict:
    """挂机等待：duration 等 seconds 秒；clock 等到 at（HH:MM，已过则顺延到第二天）。"""
    raw = value if isinstance(value, dict) else {}
    mode = raw.get("mode") if raw.get("mode") in ("duration", "clock") else "duration"
    try:
        seconds = max(1, min(int(round(float(raw.get("seconds") or 300))), 12 * 3600))
    except (TypeError, ValueError):
        seconds = 300
    at = str(raw.get("at") or "").strip()
    if not re.fullmatch(r"\d{1,2}:\d{2}", at):
        at = "08:00"
    return {"mode": mode, "seconds": seconds, "at": at}


def _normalize_step(step: dict, index: int) -> dict:
    task = step.get("task")
    mode = step.get("mode") or "solo"
    if task == catalog.TEAM_SETUP_KEY:
        mode = "team"
    elif mode in ("duo", "team"):
        mode = "team"
    if mode == "team" and task != catalog.TEAM_SETUP_KEY and not catalog.task_team(task or ""):
        mode = "solo"  # 引擎没有组队状态字段的玩法只能单人
    return {
        "id": step.get("id") or f"s{uuid.uuid4().hex[:6]}",
        "task": task,
        "enabled": bool(step.get("enabled", True)),
        "mode": mode,
        "account": step.get("account"),
        "participants": step.get("participants") or [],
        "team": step.get("team") or {},
        "patch": step.get("patch") or {},
        "note": step.get("note") or "",
        # 自定义点击是控制台伪任务：引用方案库里的一份方案，不写实例配置
        "plan_id": step.get("plan_id"),
        "plan_name": step.get("plan_name") or "",
        "wait": _normalize_wait(step.get("wait")),
        "order": index,
    }


def _participants(step: dict, accounts: list[str],
                  roster: dict | None = None) -> list[tuple[str, str | None]]:
    """解析一个步骤的参与账号与角色。

    组队步骤的队员来源优先级：前置「自定义组队」步骤 > 步骤自带的 participants
    > 编排表绑定的全部账号。队长由前者显式指定，不再依赖账号顺序。
    """
    if step.get("mode") != "team":
        single = step.get("account") or (accounts[0] if accounts else "")
        return [(single, None)] if single else []

    order: list[str] = []
    if roster and roster.get("leader"):
        order.append(roster["leader"])
        order.extend(roster.get("members") or [])
    elif step.get("participants"):
        order.extend(p.get("account") for p in step["participants"] if p.get("account"))
    else:
        order.extend(accounts)

    seen: set[str] = set()
    roster_accounts = [a for a in order if a and a in accounts and not (a in seen or seen.add(a))]
    if len(roster_accounts) < 2:
        return []  # 组队步骤必须至少 2 个可用账号，交由编排层报错
    return [(acct, "leader" if i == 0 else "member") for i, acct in enumerate(roster_accounts)]


def _loop_interval(value: Any) -> int:
    """两轮之间的缓冲秒数，给模拟器留出回庭院 / 结算的时间。"""
    try:
        return max(0, min(int(value if value is not None else 3), 300))
    except (TypeError, ValueError):
        return 3


def _normalize_loop(raw: Any) -> dict:
    """编排循环设置。

    once    : 只跑一遍（默认）
    count   : 整份编排重复 N 轮，2 <= N <= 999
    forever : 一直循环，直到用户点「停止」
    on_error: stop（某轮失败即结束）/ continue（跳过失败，继续下一轮）
    """
    data = raw if isinstance(raw, dict) else {}
    mode = data.get("mode")
    if mode not in ("once", "count", "forever"):
        mode = "once"
    count: int | None = None
    if mode == "once":
        count = 1
    elif mode == "count":
        try:
            count = max(2, min(int(data.get("count") or 2), 999))
        except (TypeError, ValueError):
            count = 2
    return {
        "mode": mode,
        "count": count,
        "on_error": "continue" if data.get("on_error") == "continue" else "stop",
        "interval": _loop_interval(data.get("interval")),
    }


def _idle_seconds(value: Any, default: float) -> float:
    try:
        return round(max(0.0, min(float(default if value is None else value), 600.0)), 2)
    except (TypeError, ValueError):
        return default


def _normalize_idle(raw: Any) -> dict:
    """编排级「随机发呆」：任务执行前后、自定义点击每层循环前后按概率静止不操作。

    enable       默认关闭，不改变既有编排的执行节奏
    min/max      随机发呆秒数区间（0–600s）
    probability  每个判定点独立触发的概率（0–1）
    """
    data = raw if isinstance(raw, dict) else {}
    lo = _idle_seconds(data.get("min"), 2.0)
    hi = _idle_seconds(data.get("max"), 6.0)
    if hi < lo:
        lo, hi = hi, lo
    try:
        prob = max(0.0, min(float(data.get("probability", 0.15)), 1.0))
    except (TypeError, ValueError):
        prob = 0.15
    return {
        "enable": data.get("enable") is True,
        "min": lo,
        "max": hi,
        "probability": round(prob, 3),
    }


def _normalize_flow(flow: dict) -> dict:
    steps = [_normalize_step(s, i) for i, s in enumerate(flow.get("steps") or [])]
    for i, step in enumerate(steps):
        step["order"] = i
    return {
        "id": flow.get("id") or f"f{uuid.uuid4().hex[:8]}",
        "name": (flow.get("name") or "未命名编排").strip(),
        "accounts": [a for a in (flow.get("accounts") or []) if a],
        "steps": steps,
        "loop": _normalize_loop(flow.get("loop")),
        "idle": _normalize_idle(flow.get("idle")),
        "updated": flow.get("updated") or datetime.now().isoformat(timespec="seconds"),
    }


@app.get("/api/flows")
def list_flows():
    return {"flows": [_normalize_flow(f) for f in _load_flows()]}


@app.post("/api/flows")
def create_flow(payload: dict = Body(...)):
    flows = _load_flows()
    flow = _normalize_flow(payload)
    if not flow["accounts"]:
        raise HTTPException(400, "编排表至少要绑定一个账号")
    flows.append(flow)
    _save_flows(flows)
    return {"ok": True, "flow": flow}


@app.put("/api/flows/{flow_id}")
def update_flow(flow_id: str, payload: dict = Body(...)):
    flows = _load_flows()
    for i, flow in enumerate(flows):
        if flow.get("id") == flow_id:
            merged = {**flow, **{k: payload[k] for k in ("name", "accounts", "steps", "loop", "idle") if k in payload}}
            merged["updated"] = datetime.now().isoformat(timespec="seconds")
            flows[i] = _normalize_flow(merged)
            _save_flows(flows)
            return {"ok": True, "flow": flows[i]}
    raise HTTPException(404, "编排表不存在")


@app.delete("/api/flows/{flow_id}")
def delete_flow(flow_id: str):
    flows = _load_flows()
    remain = [f for f in flows if f.get("id") != flow_id]
    if len(remain) == len(flows):
        raise HTTPException(404, "编排表不存在")
    _save_flows(remain)
    return {"ok": True}


@app.post("/api/flows/{flow_id}/duplicate")
def duplicate_flow(flow_id: str):
    flows = _load_flows()
    src = next((f for f in flows if f.get("id") == flow_id), None)
    if src is None:
        raise HTTPException(404, "编排表不存在")
    copy = _normalize_flow({**src, "id": None, "name": f"{src.get('name')} 副本"})
    for step in copy["steps"]:
        step["id"] = f"s{uuid.uuid4().hex[:6]}"
    flows.append(copy)
    _save_flows(flows)
    return {"ok": True, "flow": copy}


# ────────────────────────── 模板库 ──────────────────────────

def _load_flow_library() -> list[dict]:
    if not FLOW_LIBRARY_FILE.exists():
        return []
    try:
        data = json.loads(FLOW_LIBRARY_FILE.read_text(encoding="utf-8"))
        data = data.get("templates") if isinstance(data, dict) else data
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []


def _save_flow_library(templates: list[dict]) -> None:
    FLOW_LIBRARY_FILE.write_text(json.dumps({"templates": templates}, ensure_ascii=False, indent=2),
                                 encoding="utf-8")


def _template_steps(steps: list[dict]) -> list[dict]:
    """模板与账号/模拟器无关：只留任务、参数与顺序。"""
    out = []
    for s in steps or []:
        task = s.get("task")
        if not task or task == catalog.TEAM_SETUP_KEY:
            continue
        mode = s.get("mode") if s.get("mode") in ("solo", "team") else "solo"
        if mode == "team" and not catalog.task_team(task):
            mode = "solo"
        entry = {"task": task, "enabled": bool(s.get("enabled", True)),
                 "mode": mode, "patch": s.get("patch") or {}, "note": s.get("note") or ""}
        if task == catalog.CUSTOM_CLICK_KEY and s.get("plan_id"):
            entry["plan_id"] = s["plan_id"]
            entry["plan_name"] = s.get("plan_name") or ""
        if task == catalog.WAIT_KEY:
            entry["wait"] = _normalize_wait(s.get("wait"))
        out.append(entry)
    return out


@app.get("/api/flow-library")
def list_flow_library():
    return {"templates": _load_flow_library()}


@app.post("/api/flow-library")
def save_flow_template(payload: dict = Body(...)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "方案名称不能为空")
    src = next((f for f in _load_flows() if f.get("id") == payload.get("flow_id")), None)
    steps = payload.get("steps")
    if steps is None:
        if src is None:
            raise HTTPException(404, "编排表不存在")
        steps = src.get("steps")
    steps = _template_steps(steps)
    if not steps:
        raise HTTPException(400, "没有可保存的任务步骤")
    # 循环设置与随机发呆也算方案的一部分：不存的话，建编排时这两项就丢了
    loop = payload.get("loop") if payload.get("loop") is not None else (src or {}).get("loop")
    idle = payload.get("idle") if payload.get("idle") is not None else (src or {}).get("idle")
    templates = [t for t in _load_flow_library() if t.get("name") != name]  # 同名覆盖
    tpl = {"id": f"t{uuid.uuid4().hex[:8]}", "name": name, "steps": steps,
           "loop": _normalize_loop(loop), "idle": _normalize_idle(idle),
           "saved": datetime.now().isoformat(timespec="seconds")}
    templates.append(tpl)
    _save_flow_library(templates)
    return {"ok": True, "template": tpl}


@app.delete("/api/flow-library/{tpl_id}")
def delete_flow_template(tpl_id: str):
    templates = _load_flow_library()
    remain = [t for t in templates if t.get("id") != tpl_id]
    if len(remain) == len(templates):
        raise HTTPException(404, "方案不存在")
    _save_flow_library(remain)
    return {"ok": True}


# ────────────────────────── 自定义点击方案库 ──────────────────────────
# 与实例配置分开：方案是通用模板，账号解绑/干净会话都保留。
# 编排步骤只存 plan_id，执行时由 _custom_plan_for_step 解析成完整方案。

_CC_FULL_RECT = [0, 0, 1280, 720]  # 引擎强制 1280x720


def _cc_rect(value) -> list[int]:
    try:
        x1, y1, x2, y2 = (int(round(float(v))) for v in (value or _CC_FULL_RECT)[:4])
    except (TypeError, ValueError):
        return list(_CC_FULL_RECT)
    x1, x2 = sorted((max(0, min(x1, 1280)), max(0, min(x2, 1280))))
    y1, y2 = sorted((max(0, min(y1, 720)), max(0, min(y2, 720))))
    if x2 - x1 < 2:
        x2, x1 = min(1280, x1 + 2), max(0, x2 - 2)
    if y2 - y1 < 2:
        y2, y1 = min(720, y1 + 2), max(0, y2 - 2)
    return [x1, y1, x2, y2]


def _cc_range(value, default: tuple[float, float]) -> list[float]:
    try:
        a, b = (float(v) for v in (value or default)[:2])
    except (TypeError, ValueError):
        return list(default)
    a, b = max(0.0, min(a, 300.0)), max(0.0, min(b, 300.0))
    return [a, b] if a <= b else [b, a]


def _cc_lines(value) -> list[str]:
    """texts / forbid 既接受数组，也接受一行一条的多行文本。"""
    if isinstance(value, str):
        value = value.splitlines()
    return [str(v).strip() for v in (value or []) if str(v).strip()]


def _normalize_cc_repeat(raw) -> dict:
    """层级内循环：once / count / forever；gap 秒为轮间隔，recheck 控制每轮是否重新 OCR。"""
    raw = raw if isinstance(raw, dict) else {}
    mode = raw.get("mode")
    if mode not in ("once", "count", "forever"):
        mode = "once"
    try:
        count = max(1, min(int(raw.get("count") or 2), 999))
    except (TypeError, ValueError):
        count = 2
    try:
        gap = max(0.0, min(float(raw.get("gap") or 0), 300.0))
    except (TypeError, ValueError):
        gap = 0.0
    return {
        "mode": mode,
        "count": count,
        "gap": round(gap, 2),
        "recheck": raw.get("recheck") is not False,
    }


def _cc_jump(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _cc_point(value, default: tuple[int, int] = (640, 400)) -> list[int]:
    """滚动层的鼠标停留点，clamp 进 1280x720。"""
    try:
        x, y = (int(round(float(v))) for v in (value or default)[:2])
    except (TypeError, ValueError):
        return list(default)
    return [max(0, min(x, 1279)), max(0, min(y, 719))]


_CC_TEMPLATE_LIMIT = 4_000_000  # base64 字符上限，约 3MB PNG，够放大半个屏幕
_CC_PREVIEW_LIMIT = 2_000_000  # 编辑期参考画面（1280x720 JPEG）字符上限


def _cc_anchor_rect(value, point: list[int]) -> list[int]:
    """鼠标停留区域：用户框出来的矩形；没框过就按停留点展开成小方块。"""
    try:
        x1, y1, x2, y2 = (int(round(float(v))) for v in list(value)[:4])
    except (TypeError, ValueError):
        return _cc_box_around(point)
    x1, x2 = sorted((max(0, min(x1, 1279)), max(0, min(x2, 1279))))
    y1, y2 = sorted((max(0, min(y1, 719)), max(0, min(y2, 719))))
    if x2 - x1 < 8 or y2 - y1 < 8:
        return _cc_box_around(point)
    return [x1, y1, x2, y2]


def _cc_box_around(point: list[int], half: int = 12) -> list[int]:
    x, y = point
    return [max(0, x - half), max(0, y - half), min(1279, x + half), min(719, y + half)]


def _normalize_cc_miss(raw) -> dict | None:
    """直接点击的「未命中」分支：另一块点击区域，可再跳转或结束本方案。"""
    raw = raw if isinstance(raw, dict) else None
    if not raw:
        return None
    return {
        "enable": bool(raw.get("enable")),
        "rect": _cc_rect(raw.get("rect")),
        "delay_after": _cc_range(raw.get("delay_after"), (0.4, 1.2)),
        "jump": _cc_jump(raw.get("jump")),
        "end": bool(raw.get("end")),
    }


def _normalize_cc_scroll_miss(raw) -> dict:
    """滚动层没找到目标时：none / click（点一块区域）/ jump / end。"""
    raw = raw if isinstance(raw, dict) else {}
    mode = raw.get("mode")
    if mode not in ("none", "click", "jump", "end"):
        mode = "none"
    return {
        "mode": mode,
        "rect": _cc_rect(raw.get("rect")),
        "jump": _cc_jump(raw.get("jump")),
    }


def _normalize_cc_scroll(raw) -> dict:
    """滚动寻找并点击的参数；字段全部有默认值，旧方案读出来也能直接用。"""
    raw = raw if isinstance(raw, dict) else {}

    def num(key, default: float, low: float, high: float) -> float:
        try:
            n = float(raw.get(key, default))
        except (TypeError, ValueError):
            n = float(default)
        return round(max(low, min(n, high)), 2 if isinstance(default, float) else 0)

    template = raw.get("template")
    template = template if isinstance(template, str) and len(template) <= _CC_TEMPLATE_LIMIT else ""
    rect = raw.get("template_rect")
    anchor = _cc_point(raw.get("anchor"))
    area = _cc_anchor_rect(raw.get("anchor_rect"), anchor)
    return {
        "anchor": [(area[0] + area[2]) // 2, (area[1] + area[3]) // 2],
        "anchor_rect": area,
        "direction": "up" if raw.get("direction") == "up" else "down",
        "wheel": int(num("wheel", 5, 1, 30)),
        "interval": num("interval", 0.8, 0.2, 5.0),
        "timeout": num("timeout", 15, 1, 120),
        "threshold": num("threshold", 0.8, 0.5, 0.99),
        "method": raw.get("method") if raw.get("method") in ("auto", "wheel", "drag") else "auto",
        "template": template,
        "template_rect": _cc_rect(rect) if rect else [],
        "miss": _normalize_cc_scroll_miss(raw.get("miss")),
    }


def _normalize_cc_step(raw, index: int) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    preview = raw.get("preview")  # 编辑期参考画面：留着才能重新打开方案改框选
    preview = preview if isinstance(preview, str) and len(preview) <= _CC_PREVIEW_LIMIT else ""
    return {
        "id": raw.get("id") or f"cs{uuid.uuid4().hex[:6]}",
        "name": (raw.get("name") or f"第 {index + 1} 层").strip(),
        "mode": "scroll" if raw.get("mode") == "scroll" else "direct",
        "scroll": _normalize_cc_scroll(raw.get("scroll")),
        "preview": preview,
        "texts": _cc_lines(raw.get("texts")),
        "forbid": _cc_lines(raw.get("forbid")),
        "match": "any" if raw.get("match") == "any" else "all",
        "ocr_roi": _cc_rect(raw.get("ocr_roi")),
        "rect": _cc_rect(raw.get("rect")),
        "score": round(max(0.1, min(float(raw.get("score") or 0.6), 1.0)), 2),
        "delay_before": _cc_range(raw.get("delay_before"), (0.2, 0.8)),
        "delay_after": _cc_range(raw.get("delay_after"), (0.4, 1.2)),
        "repeat": _normalize_cc_repeat(raw.get("repeat")),
        "jump": _cc_jump(raw.get("jump")),
        "hit_enable": raw.get("hit_enable") is not False,
        "miss": _normalize_cc_miss(raw.get("miss")),
    }


def _normalize_pkg_meta(raw) -> dict | None:
    """方案里附带的「任务包」来源信息；不是从包安装的方案返回 None。"""
    raw = raw if isinstance(raw, dict) else None
    if not raw:
        return None
    out = {
        "id": str(raw.get("id") or "")[:64],
        "name": str(raw.get("name") or "")[:60],
        "author": str(raw.get("author") or "")[:40],
        "version": str(raw.get("version") or "")[:24],
        "date": str(raw.get("date") or "")[:32],
        "description": str(raw.get("description") or "")[:600],
        "source": "online" if raw.get("source") == "online" else "file",
        "sha256": str(raw.get("sha256") or "").lower()[:64],
        "installed_at": str(raw.get("installed_at") or "")[:32],
    }
    if not out["id"] or not out["version"]:
        return None
    return out


def _normalize_cc_plan(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    steps = [_normalize_cc_step(s, i) for i, s in enumerate(raw.get("steps") or [])]
    for st in steps:  # 删层后目标层号可能越界，统一归零（不跳转）
        if not 1 <= st["jump"] <= len(steps):
            st["jump"] = 0
        miss = st.get("miss")
        if miss and not 1 <= miss["jump"] <= len(steps):
            miss["jump"] = 0
        smiss = (st.get("scroll") or {}).get("miss")
        if smiss and smiss.get("mode") == "jump" and not 1 <= smiss["jump"] <= len(steps):
            smiss["mode"] = "none"
            smiss["jump"] = 0
    return {
        "id": raw.get("id") or f"cc{uuid.uuid4().hex[:8]}",
        "name": (raw.get("name") or "未命名方案").strip(),
        "timeout": max(1, min(int(raw.get("timeout") or 30), 3600)),
        "poll": _cc_range(raw.get("poll"), (0.3, 0.8)),
        "battle": raw.get("battle") is not False,  # 全局自动接管引擎战斗，可整份方案关闭
        "steps": steps,
        "pkg": _normalize_pkg_meta(raw.get("pkg")),
        "updated": raw.get("updated") or datetime.now().isoformat(timespec="seconds"),
    }


def _load_custom_plans() -> list[dict]:
    if not CUSTOM_CLICK_FILE.exists():
        return []
    try:
        data = json.loads(CUSTOM_CLICK_FILE.read_text(encoding="utf-8"))
        data = data.get("plans") if isinstance(data, dict) else data
        return [_normalize_cc_plan(p) for p in data if isinstance(p, dict)] \
            if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []


def _save_custom_plans(plans: list[dict]) -> None:
    _save(CUSTOM_CLICK_FILE, {"plans": plans}, backup=False)


def _custom_plan_for_step(step: dict) -> dict:
    plan_id = step.get("plan_id")
    plan = next((p for p in _load_custom_plans() if p["id"] == plan_id), None)
    if plan is None:
        raise HTTPException(400, f"自定义点击方案不存在或已删除：{plan_id or '（未选择方案）'}")
    if not plan["steps"]:
        raise HTTPException(400, f"自定义点击方案「{plan['name']}」没有配置任何层级")
    return plan


@app.get("/api/custom-clicks")
def list_custom_clicks():
    return {"plans": _load_custom_plans()}


@app.post("/api/custom-clicks")
def create_custom_click(payload: dict = Body(...)):
    plan = _normalize_cc_plan(payload)
    if not plan["steps"]:
        raise HTTPException(400, "方案至少需要一层「检查 → 点击」")
    plans = _load_custom_plans()
    plans.append(plan)
    _save_custom_plans(plans)
    return {"ok": True, "plan": plan}


@app.put("/api/custom-clicks/{plan_id}")
def update_custom_click(plan_id: str, payload: dict = Body(...)):
    plans = _load_custom_plans()
    for i, old in enumerate(plans):
        if old["id"] == plan_id:
            plan = _normalize_cc_plan({**old, **payload, "id": plan_id})
            if not plan["steps"]:
                raise HTTPException(400, "方案至少需要一层「检查 → 点击」")
            plan["updated"] = datetime.now().isoformat(timespec="seconds")
            plans[i] = plan
            _save_custom_plans(plans)
            return {"ok": True, "plan": plan}
    raise HTTPException(404, "方案不存在")


@app.post("/api/custom-clicks/{plan_id}/duplicate")
def duplicate_custom_click(plan_id: str):
    plans = _load_custom_plans()
    src = next((p for p in plans if p["id"] == plan_id), None)
    if src is None:
        raise HTTPException(404, "方案不存在")
    copy_plan = _normalize_cc_plan({**src, "id": None, "name": f"{src['name']} 副本"})
    for step in copy_plan["steps"]:
        step["id"] = f"cs{uuid.uuid4().hex[:6]}"
    plans.append(copy_plan)
    _save_custom_plans(plans)
    return {"ok": True, "plan": copy_plan}


@app.delete("/api/custom-clicks/{plan_id}")
def delete_custom_click(plan_id: str):
    plans = _load_custom_plans()
    used = [
        f.get("name") or f.get("id") for f in _load_flows()
        if any(s.get("task") == catalog.CUSTOM_CLICK_KEY and s.get("plan_id") == plan_id
               for s in (f.get("steps") or []))
    ]
    if used:
        raise HTTPException(409, f"方案正被编排使用（{', '.join(used)}），请先删除对应步骤")
    remain = [p for p in plans if p["id"] != plan_id]
    if len(remain) == len(plans):
        raise HTTPException(404, "方案不存在")
    _save_custom_plans(remain)
    return {"ok": True}


# ────────────────────────── 任务包（.yyjio-task） ──────────────────────────

def _package_plans() -> list[dict]:
    return [p for p in _load_custom_plans() if p.get("pkg")]


def _package_task_entries() -> list[dict]:
    out = []
    for plan in _package_plans():
        pkg = plan["pkg"]
        out.append({
            "key": f"pkg:{pkg['id']}@{pkg['version']}",
            "name": pkg.get("name") or plan["name"],
            "category": TASK_PACKAGE_CATEGORY,
            "desc": pkg.get("description") or "来自任务包的自定义点击方案",
            "team": False,
            "hidden": False,
            "pseudo": True,
            "plan_id": plan["id"],
            "package": {"id": pkg["id"], "author": pkg.get("author") or "",
                        "version": pkg["version"], "source": pkg.get("source") or "file"},
        })
    return out


def _decode_upload(payload: dict) -> bytes:
    data = payload.get("data")
    if not isinstance(data, str) or not data:
        raise HTTPException(400, "没有收到任务包内容")
    if data.startswith("data:"):
        data = data.split(",", 1)[-1]
    try:
        raw = base64.b64decode(data, validate=False)
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "任务包内容不是有效的 base64")
    return raw


def _install_manifest(manifest: dict, source: str, overwrite: bool) -> dict:
    pkg_id = manifest["id"]
    version = manifest["version"]
    plan_id = f"{pkg_id}@{version}"
    plans = _load_custom_plans()
    existing = next((p for p in plans if p["id"] == plan_id), None)
    if existing is not None and not overwrite:
        raise HTTPException(409, f"已安装同版本（{version}）；如需覆盖请勾选覆盖")
    plan = _normalize_cc_plan({
        **manifest["plan"],
        "id": plan_id,
        "name": manifest["name"],
        "pkg": {
            "id": pkg_id, "name": manifest["name"], "author": manifest.get("author") or "",
            "version": version, "date": manifest.get("date") or "",
            "description": manifest.get("description") or "",
            "source": source, "sha256": manifest.get("sha256") or "",
            "installed_at": datetime.now().isoformat(timespec="seconds"),
        },
    })
    if not plan["steps"]:
        raise HTTPException(400, "任务包里没有可用的层级")
    if existing is not None:
        plans = [plan if p["id"] == plan_id else p for p in plans]
    else:
        plans.append(plan)
    _save_custom_plans(plans)
    return {"ok": True, "plan_id": plan_id, "plan": plan,
            "package": taskpack.summary({**manifest, "steps": len(plan["steps"])})}


@app.get("/api/task-packages")
def list_task_packages():
    items = []
    for plan in _package_plans():
        pkg = dict(plan["pkg"])
        pkg.update({"plan_id": plan["id"], "plan_name": plan["name"],
                    "steps": len(plan["steps"]), "updated": plan.get("updated") or ""})
        items.append(pkg)
    items.sort(key=lambda x: ((x.get("name") or ""), (x.get("version") or "")))
    return {"packages": items, "category": TASK_PACKAGE_CATEGORY, "source": TASK_SOURCE_URL}


@app.post("/api/task-packages/export")
def export_task_package(payload: dict = Body(...)):
    from datetime import date as _date
    plan_id = (payload.get("plan_id") or "").strip()
    plan = next((p for p in _load_custom_plans() if p["id"] == plan_id), None)
    if plan is None:
        raise HTTPException(404, "方案不存在")
    pkg = plan.get("pkg") or {}
    author = (payload.get("author") or pkg.get("author") or "").strip()
    name = (payload.get("name") or pkg.get("name") or plan["name"]).strip()
    pkg_id = (payload.get("id") or pkg.get("id") or taskpack.default_id(author, name)).strip().lower()
    info = {
        "id": pkg_id,
        "name": name,
        "author": author,
        "version": (payload.get("version") or pkg.get("version") or "1.0.0").strip(),
        "description": payload.get("description") if payload.get("description") is not None
        else (pkg.get("description") or ""),
        "date": payload.get("date") or _date.today().isoformat(),
    }
    try:
        taskpack.validate_plan(plan)
        data, entry = taskpack.build_package(plan, info)
    except taskpack.PackError as exc:
        raise HTTPException(400, f"这个方案还不能导出：{exc}")
    return {"ok": True, "filename": entry["file"].split("/")[-1], "size": len(data),
            "index_entry": entry, "info": info,
            "data": base64.b64encode(data).decode("ascii")}


@app.post("/api/task-packages/inspect")
def inspect_task_package(payload: dict = Body(...)):
    data = _decode_upload(payload)
    try:
        manifest = taskpack.read_package(data)
    except taskpack.PackError as exc:
        raise HTTPException(400, str(exc))
    installed = next((p["pkg"].get("version") for p in _package_plans()
                      if p["pkg"].get("id") == manifest["id"]), None)
    steps = (manifest.get("plan") or {}).get("steps") or []
    return {"ok": True, "package": taskpack.summary(manifest),
            "installed_version": installed,
            "same_version": installed == manifest["version"],
            "layers": [{"index": i, "name": s.get("name") or f"第 {i} 层", "mode": s.get("mode")}
                       for i, s in enumerate(steps, 1)]}


@app.post("/api/task-packages/install")
def install_task_package(payload: dict = Body(...)):
    data = _decode_upload(payload)
    try:
        manifest = taskpack.read_package(data)
    except taskpack.PackError as exc:
        raise HTTPException(400, str(exc))
    result = _install_manifest(manifest, "file", bool(payload.get("overwrite")))
    result["installed_version"] = manifest["version"]
    return result


@app.delete("/api/task-packages/{pkg_id}")
def delete_task_package(pkg_id: str, version: str | None = None):
    plans = _load_custom_plans()
    targets = [p for p in plans
               if (p.get("pkg") or {}).get("id") == pkg_id
               and (not version or p["pkg"]["version"] == version)]
    if not targets:
        raise HTTPException(404, "没有安装这个任务包")
    ids = {p["id"] for p in targets}
    used = [f.get("name") or f.get("id") for f in _load_flows()
            if any(s.get("task") == catalog.CUSTOM_CLICK_KEY and s.get("plan_id") in ids
                   for s in (f.get("steps") or []))]
    if used:
        raise HTTPException(409, f"任务包正被编排使用（{', '.join(used)}），请先删除对应步骤")
    remain = [p for p in plans if p["id"] not in ids]
    _save_custom_plans(remain)
    return {"ok": True, "removed": len(targets)}


def _fetch_task_source(url: str, timeout: int = 12) -> bytes:
    headers = {"User-Agent": f"{APP_NAME}/{APP_VERSION}", "Cache-Control": "no-cache"}
    try:
        import requests as _requests
        resp = _requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.content
    except ImportError:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as fp:
            return fp.read()


@app.get("/api/task-source")
def task_source_refresh(url: str | None = None):
    target = (url or TASK_SOURCE_URL).strip()
    if target != TASK_SOURCE_URL:
        raise HTTPException(400, "暂不支持第三方任务源")
    try:
        raw = _fetch_task_source(target)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"连不上任务源（{exc.__class__.__name__}）：{exc}")
    try:
        items = taskpack.parse_index(raw.decode("utf-8", "replace"))
    except taskpack.PackError as exc:
        raise HTTPException(502, str(exc))
    installed = {p["pkg"]["id"]: p["pkg"]["version"] for p in _package_plans()}
    base = target.rsplit("/", 1)[0] + "/"
    for it in items:
        cur = installed.get(it["id"])
        it["installed_version"] = cur
        it["update"] = bool(cur and cur != it["version"])
        it["url"] = base + it["file"]
    return {"ok": True, "source": target, "packages": items,
            "fetched_at": datetime.now().isoformat(timespec="seconds")}


@app.post("/api/task-source/install")
def task_source_install(payload: dict = Body(...)):
    url = (payload.get("url") or "").strip()
    if not url.startswith(TASK_SOURCE_URL.rsplit("/", 1)[0].rsplit("/", 1)[0] + "/"):
        raise HTTPException(400, "任务包地址不合法")
    try:
        data = _fetch_task_source(url, timeout=25)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"下载任务包失败（{exc.__class__.__name__}）：{exc}")
    expect = (payload.get("sha256") or "").lower()
    if expect:
        got = hashlib.sha256(data).hexdigest()
        if got != expect:
            raise HTTPException(400, "文件校验失败（sha256 不一致），可能是源里更新了清单，请刷新后再试")
    try:
        manifest = taskpack.read_package(data)
    except taskpack.PackError as exc:
        raise HTTPException(400, str(exc))
    if payload.get("id") and payload["id"] != manifest["id"]:
        raise HTTPException(400, "下载到的是另一个任务包")
    result = _install_manifest(manifest, "online", bool(payload.get("overwrite")))
    result["installed_version"] = manifest["version"]
    return result


@app.post("/api/instances/{name}/screenshot")
def instance_screenshot(name: str):
    """抓一张当前模拟器画面（1280x720），供自定义点击编辑器拖框选区。"""
    _instance_path(name)
    out = ROOT / "log" / "gui" / f"capture_{uuid.uuid4().hex[:8]}.png"
    cmd = [str(PYTHON), "-X", "utf8", "-B", str(ROOT / "gui" / "custom_click_runner.py"),
           "--config", name, "--capture", str(out)]
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        res = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=45, **kwargs)
        if not out.exists():
            detail = (res.stderr or res.stdout or "").strip()[-600:]
            raise HTTPException(500, f"截图失败：{detail or '未生成图片'}")
        payload = base64.b64encode(out.read_bytes()).decode("ascii")
        return {"ok": True, "image": "data:image/png;base64," + payload,
                "width": 1280, "height": 720}
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "截图超时：模拟器可能未连接，或分辨率不是 1280x720")
    finally:
        out.unlink(missing_ok=True)


# ────────────────────────── 编排执行 ──────────────────────────

_JOBS: dict[str, dict] = {}
_JOB_LOCK = threading.RLock()


def _apply_step_config(instance: str, task: str, patch: dict, role: str | None,
                       roster: list[str] | None = None) -> None:
    """把编排步骤上的参数写入实例配置；无配置段的动作任务（如回庭院）直接跳过。"""
    path = _instance_path(instance)
    cfg = _load(path)
    section = cfg.get(task)
    if not isinstance(section, dict):
        if role:
            raise HTTPException(400, f"{instance} 缺少任务配置段 {task}，无法参与组队")
        if patch:
            raise HTTPException(400, f"{instance} 缺少任务配置: {task}（该任务不支持参数）")
        return
    if patch:
        patch = dict(patch)
        if (task or "").lower() == "hyakkiyakou" and isinstance(patch.get("debug_config"), dict):
            # 高频截图/点击通道由 _align_hyakkiyakou_device 在启动时按设备动态决定；
            # 编排里保存的旧值（通常是 window_*）不能回写，否则会把可用配置改坏。
            patch["debug_config"] = {
                k: v for k, v in patch["debug_config"].items()
                if k not in ("hya_screenshot_method", "hya_control_method")
            }
        # 旧版本控制台把「检查契忆数量」写成了独立的 bondling_check 段，
        # 而引擎只读 bondling_fairyland.bondling_config.check_enable / limit_num。
        # 老编排里的这段是死字段，这里就地迁移，不再往实例配置里写无效段。
        legacy = patch.pop("bondling_check", None)
        if isinstance(legacy, dict) and legacy:
            cfg_patch = dict(patch.get("bondling_config") or {})
            for key in ("check_enable", "limit_num"):
                if key in legacy and key not in cfg_patch:
                    cfg_patch[key] = legacy[key]
            if cfg_patch:
                patch["bondling_config"] = cfg_patch
        _deep_merge(section, patch)
        if task == "bondling_fairyland":
            section.pop("bondling_check", None)  # 清掉旧控制台写入的无效段
    if role:
        status_path = _team_status_path(cfg, task)
        if not status_path:
            # 以前这里静默跳过，队员会以默认 leader/alone 运行并永远不接受邀请
            raise HTTPException(400, f"{instance} 的任务 {task} 缺少 user_status 字段，无法参与组队")
        head, leaf = status_path.split(".", 1)
        section.setdefault(head, {})[leaf] = role
    # 队长端按「游戏内昵称」在好友列表里 OCR 精确匹配邀请；昵称没回填时
    # 引擎会打印 Invite friend 却一个人都选不上，然后空转 120s 超时。
    if role == "leader" and roster:
        profiles = _load_profiles()
        names = []
        for member in roster[:2]:
            nick = (profiles.get(member) or {}).get("nickname") or ""
            if not nick or nick == member:
                raise HTTPException(
                    400,
                    f"队员 {member} 未填写游戏内昵称：请在「编辑资料」里填与游戏内完全一致的全称，"
                    "队长端靠 OCR 精确匹配好友列表发出邀请")
            names.append(nick)
        invite = section.setdefault("invite_config", {})
        invite["friend_1"] = names[0]
        if len(names) > 1:
            invite["friend_2"] = names[1]
        invite["invite_number"] = "two" if len(names) > 1 else "one"
    _save(path, cfg)


@app.post("/api/flows/{flow_id}/run")
def run_flow(flow_id: str, payload: dict | None = Body(None)):
    flow = next((f for f in _load_flows() if f.get("id") == flow_id), None)
    if flow is None:
        raise HTTPException(404, "编排表不存在")
    flow = _normalize_flow(flow)
    if not flow["accounts"]:
        raise HTTPException(400, "编排表未绑定账号")
    for account in flow["accounts"]:
        _instance_path(account)
    # 本次运行可以临时覆盖循环/发呆设置；不传就用编排表保存的默认值。
    loop = _normalize_loop((payload or {}).get("loop", flow["loop"]))
    idle = _normalize_idle((payload or {}).get("idle", flow.get("idle")))
    total = loop["count"] if loop["mode"] != "forever" else None
    # 运行期间编排表可能被编辑，这里固定一份快照，避免半路换步骤。
    snapshot = copy.deepcopy(flow["steps"])
    accounts = list(flow["accounts"])

    with _JOB_LOCK:
        running = [j for j in _JOBS.values()
                   if j["flow_id"] == flow_id and j["status"] == "running"]
        if running:
            raise HTTPException(409, "该编排正在执行中")
        # 一个账号同一时间只能跑一份编排，否则两个进程会抢同一台模拟器的输入。
        occupied = sorted({
            account
            for job in _JOBS.values()
            if job["status"] == "running"
            for account in (job.get("accounts") or [])
            if account in flow["accounts"]
        })
        if occupied:
            raise HTTPException(409, f"账号 {', '.join(occupied)} 正在执行其它编排")
        job = {
            "id": f"j{uuid.uuid4().hex[:8]}",
            "flow_id": flow_id,
            "flow_name": flow["name"],
            "accounts": accounts,
            "paused": False,
            "status": "running",
            "started": datetime.now().isoformat(timespec="seconds"),
            "finished": None,
            "index": -1,
            "current": None,
            "loop": loop,
            "idle": idle,
            "note": None,
            "round": 0,
            "total_rounds": total,
            "infinite": loop["mode"] == "forever",
            "rounds": [],
            "steps": [],
            "error": None,
            "last_error": None,
        }
        _JOBS[job["id"]] = job

    def _blank_steps() -> list[dict]:
        return [{"task": s["task"], "mode": s["mode"], "enabled": s["enabled"],
                 "status": "pending", "runs": []} for s in snapshot]

    def _wait_pause() -> bool:
        """暂停时在原地等；返回 False 表示等待期间被「停止执行」了。

        暂停只在步骤之间生效：当前这一步会先跑完，避免把引擎的点击流程切半。
        """
        if not job.get("paused"):
            return job["status"] != "cancelled"
        note_backup = job.get("note")
        job["note"] = "已暂停"
        while job.get("paused") and job["status"] != "cancelled":
            time.sleep(0.2)
        job["note"] = note_backup if job["status"] != "cancelled" else None
        return job["status"] != "cancelled"

    def _maybe_idle() -> None:
        """按概率静止一段时间；分片 sleep，点「停止」时能立刻退出。"""
        if not idle["enable"] or idle["probability"] <= 0 or idle["max"] <= 0:
            return
        if random.random() >= idle["probability"]:
            return
        seconds = round(random.uniform(idle["min"], idle["max"]), 2)
        if seconds <= 0:
            return
        job["note"] = f"随机发呆 {seconds:g}s"
        try:
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                if job["status"] == "cancelled":
                    return
                time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
        finally:
            job["note"] = None

    def _run_once(round_no: int) -> tuple[bool, str | None]:
        """把整份编排从头到尾跑一轮；返回 (是否成功, 错误信息)。"""
        active_team: dict | None = None
        job["steps"] = _blank_steps()
        job["index"] = -1
        job["current"] = None
        job["error"] = None
        for idx, step in enumerate(snapshot):
            if not _wait_pause():
                return False, None
            if job["status"] == "cancelled":
                return False, None
            if not step["enabled"]:
                job["steps"][idx]["status"] = "skipped"
                continue
            if step["task"] == catalog.WAIT_KEY:
                # 等待步骤：不启动子进程，按设置睡够再往下走（暂停/停止都能立刻响应）
                job["index"] = idx
                job["current"] = step["task"]
                job["steps"][idx]["status"] = "running"
                if not _wait_step(step.get("wait") or {}):
                    job["steps"][idx]["status"] = "cancelled"
                    return False, None
                job["steps"][idx]["status"] = "ok"
                continue
            if step["task"] == catalog.TEAM_SETUP_KEY:
                # 组队步骤不启动进程，只登记队伍名单供后续步骤使用
                team = step.get("team") or {}
                if not team.get("leader"):
                    job["steps"][idx]["status"] = "fail"
                    return False, f"第 {round_no} 轮 · 步骤 {idx + 1}：自定义组队缺少队长"
                active_team = team
                job["team"] = team
                job["steps"][idx]["status"] = "ok"
                continue
            job["index"] = idx
            job["current"] = step["task"]
            is_custom = step["task"] == catalog.CUSTOM_CLICK_KEY
            plan = None
            if is_custom:
                # 控制台伪任务：方案独立存放，不写实例 config；多开时每个绑定账号各跑一份
                try:
                    # 发呆是编排级配置，运行时注入，不落到方案库里
                    plan = {**_custom_plan_for_step(step), "idle": idle}
                except HTTPException as exc:
                    job["steps"][idx]["status"] = "fail"
                    return False, f"第 {round_no} 轮 · 步骤 {idx + 1}：{exc.detail}"
                targets = [step["account"]] if step.get("account") else list(accounts)
                pairs = [(a, None) for a in targets if a]
            else:
                pairs = _participants(step, accounts, active_team)
            if not pairs:
                job["steps"][idx]["status"] = "fail"
                return False, (f"第 {round_no} 轮 · 步骤 {idx + 1}：组队步骤至少需要 2 个可用账号"
                               if step.get("mode") == "team"
                               else f"第 {round_no} 轮 · 步骤 {idx + 1}：没有可执行账号")
            _maybe_idle()  # 任务执行前
            if job["status"] == "cancelled":
                job["steps"][idx]["status"] = "cancelled"
                return False, None
            run_ids: list[str] = []
            roster = [a for a, r in pairs if r == "member"]
            for account, role in pairs:
                if not is_custom:
                    try:
                        _apply_step_config(account, step["task"], step["patch"], role,
                                           roster if role == "leader" else None)
                    except HTTPException as exc:
                        job["steps"][idx]["status"] = "fail"
                        return False, f"第 {round_no} 轮 · 步骤 {idx + 1}：{exc.detail}"
                run_ids.append(_spawn_run(account, step["task"],
                                          bool(step.get("force_fight")), job["id"],
                                          plan if is_custom else None))
            job["steps"][idx]["status"] = "running"
            job["steps"][idx]["runs"] = run_ids
            while True:
                if job["status"] == "cancelled":
                    break
                time.sleep(1.0)
                if job["status"] == "cancelled":
                    break
                states = [_RUNS[r]["status"] for r in run_ids if r in _RUNS]
                if states and all(s != "running" for s in states):
                    break
            if job["status"] == "cancelled":
                job["steps"][idx]["status"] = "cancelled"
                return False, None
            ok = all((_RUNS[r].get("result") is True) for r in run_ids if r in _RUNS)
            job["steps"][idx]["status"] = "ok" if ok else "fail"
            _maybe_idle()  # 任务执行后
            if job["status"] == "cancelled":
                return False, None
            if not ok:
                return False, f"第 {round_no} 轮 · 步骤 {idx + 1} 执行失败"
        return True, None

    def _wait_step(wait: dict) -> bool:
        """按挂机等待设置睡够；暂停时停表，停止时立刻返回 False。"""
        mode = wait.get("mode")
        if mode == "clock":
            at = str(wait.get("at") or "08:00")
            try:
                hour, minute = (int(x) for x in at.split(":", 1))
                target = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
            except (TypeError, ValueError):
                target = datetime.now()
            if target <= datetime.now():
                target = target + timedelta(days=1)
            remaining = max(1.0, (target - datetime.now()).total_seconds())
            label = f"等到 {at}"
        else:
            remaining = float(wait.get("seconds") or 300)
            label = "等待中"
        total = remaining
        while remaining > 0:
            if job["status"] == "cancelled":
                return False
            if job.get("paused"):
                job["note"] = "已暂停"
                time.sleep(0.2)
                continue
            job["note"] = f"{label} · 还剩 {int(remaining / 60)} 分" if remaining >= 60 else f"{label} · 还剩 {int(remaining)} 秒"
            chunk = min(1.0, remaining)
            time.sleep(chunk)
            remaining -= chunk
        job["note"] = None
        return job["status"] != "cancelled"

    def _wait_interval(seconds: int) -> None:
        # 半秒一跳，用户点停止时能立刻退出等待
        for _ in range(max(0, seconds) * 2):
            if job["status"] == "cancelled":
                return
            time.sleep(0.5)

    def _worker() -> None:
        job["steps"] = _blank_steps()
        try:
            round_no = 0
            while True:
                if job["status"] == "cancelled":
                    break
                if total is not None and round_no >= total:
                    break
                round_no += 1
                job["round"] = round_no
                started = datetime.now().isoformat(timespec="seconds")
                ok, error = _run_once(round_no)
                job["rounds"].append({
                    "round": round_no,
                    "status": ("cancelled" if job["status"] == "cancelled"
                               else ("ok" if ok else "fail")),
                    "started": started,
                    "finished": datetime.now().isoformat(timespec="seconds"),
                    "error": error,
                    "runs": [rid for st in job["steps"] for rid in (st.get("runs") or [])],
                })
                if len(job["rounds"]) > 50:  # 无限循环时不让内存无限增长
                    job["rounds"] = job["rounds"][-50:]
                if job["status"] == "cancelled":
                    break
                if not ok:
                    job["last_error"] = error
                    if loop["on_error"] == "stop":
                        job["error"] = error
                        job["status"] = "failed"
                        break
                if total is not None and round_no >= total:
                    break
                _wait_interval(loop["interval"])
            if job["status"] == "cancelled":
                job["error"] = job.get("error") or f"已手动停止（完成 {round_no} 轮）"
            elif job["status"] != "failed":
                job["status"] = "finished"
        except Exception as exc:  # noqa: BLE001
            job["status"] = "failed"
            job["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            if job.get("note") == "已暂停":
                job["note"] = None  # 已经结束了就别再挂个「已暂停」
            job["finished"] = datetime.now().isoformat(timespec="seconds")
            job["current"] = None

    threading.Thread(target=_worker, daemon=True).start()
    return {"ok": True, "job": job}


@app.get("/api/jobs")
def list_jobs(limit: int = Query(30, ge=1, le=200)):
    with _JOB_LOCK:
        jobs = sorted(_JOBS.values(), key=lambda j: j["started"] or "", reverse=True)
        return {"jobs": jobs[:limit]}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    return job


def _proc_suspend(pid: int) -> bool:
    """把子进程冻住（Windows）。psutil 不在时退回 ntdll 的 NtSuspendProcess。"""
    try:
        import psutil
        psutil.Process(pid).suspend()
        return True
    except Exception:  # noqa: BLE001
        pass
    if os.name != "nt":
        return False
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ntdll = ctypes.WinDLL("ntdll")
        handle = kernel32.OpenProcess(0x0800, False, int(pid))  # PROCESS_SUSPEND_RESUME
        if not handle:
            return False
        try:
            return ntdll.NtSuspendProcess(handle) == 0
        finally:
            kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001
        return False


def _proc_resume(pid: int) -> bool:
    try:
        import psutil
        psutil.Process(pid).resume()
        return True
    except Exception:  # noqa: BLE001
        pass
    if os.name != "nt":
        return False
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ntdll = ctypes.WinDLL("ntdll")
        handle = kernel32.OpenProcess(0x0800, False, int(pid))
        if not handle:
            return False
        try:
            return ntdll.NtResumeProcess(handle) == 0
        finally:
            kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001
        return False


def _job_run_procs(job) -> list:
    """当前这条编排所有还在跑的子进程（含已冻住的）。"""
    procs = []
    for step in job.get("steps") or []:
        for rid in step.get("runs") or []:
            run = _RUNS.get(rid)
            proc = run.get("proc") if run else None
            if proc is not None and proc.poll() is None:
                procs.append(proc)
    return procs


def _set_procs_paused(job, paused: bool) -> int:
    """暂停/恢复时把正在跑的子进程一起冻住/放开，改一行都不必等这一步跑完。"""
    count = 0
    for proc in _job_run_procs(job):
        ok = _proc_suspend(proc.pid) if paused else _proc_resume(proc.pid)
        if ok:
            count += 1
    return count


@app.post("/api/jobs/{job_id}/pause")
def pause_job(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "没有这条执行记录")
    if job["status"] != "running":
        raise HTTPException(409, "这条编排已经不在运行了")
    job["paused"] = True
    job["note"] = "已暂停"
    # 当前步骤如果还在跑，把子进程一并冻住；
    # 不冻的话只能等这一步跑完才生效（长任务看不出来暂停了）。
    frozen = _set_procs_paused(job, True)
    return {"ok": True, "paused": True, "frozen": frozen}


@app.post("/api/jobs/{job_id}/resume")
def resume_job(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "没有这条执行记录")
    if job["status"] != "running":
        raise HTTPException(409, "这条编排已经不在运行了")
    job["paused"] = False
    if job.get("note") == "已暂停":
        job["note"] = None
    thawed = _set_procs_paused(job, False)
    return {"ok": True, "paused": False, "thawed": thawed}


@app.delete("/api/jobs")
def clear_jobs():
    """清空执行记录：只清已结束的，还在跑的留着。"""
    with _JOB_LOCK:
        keep = {k: v for k, v in _JOBS.items() if v["status"] == "running"}
        removed = len(_JOBS) - len(keep)
        _JOBS.clear()
        _JOBS.update(keep)
    return {"ok": True, "removed": removed, "left": len(keep)}


@app.post("/api/jobs/{job_id}/stop")
def stop_job(job_id: str):
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    if job["status"] != "running":
        return {"ok": True, "status": job["status"]}
    job["status"] = "cancelled"
    job["paused"] = False
    job["note"] = None
    # 循环作业：本轮步骤 + 历史轮次 + 所有 batch 归属该作业的进程都要停，
    # 否则无限循环会在下一轮重新拉起 runner。
    run_ids: set[str] = set()
    for snap in [job, *(job.get("rounds") or [])]:
        for step in snap.get("steps") or []:
            run_ids.update(step.get("runs") or [])
        run_ids.update(snap.get("runs") or [])
    with _RUN_LOCK:
        run_ids.update(rid for rid, run in _RUNS.items()
                       if run.get("batch") == job_id and run.get("status") == "running")
        for run_id in run_ids:
            run = _RUNS.get(run_id)
            if run and run.get("status") == "running":
                try:
                    run["proc"].terminate()
                except Exception:  # noqa: BLE001
                    pass
    return {"ok": True}



# ────────────────────────── 运行 ──────────────────────────

# 百鬼夜行有独立的高频截图/点击通道（tasks/Hyakkiyakou/slave/hya_device.py）：
# fast_screenshot 只有 window_background / nemu_ipc 两条分支，fast_click 只有
# window_message / minitouch 两条分支。window_* 依赖窗口句柄树，句柄为空时必然
# 抛 'Device' object has no attribute 'root_node'。启动时按实例全局方式对齐。
# 注意全局截图常为 auto（引擎跑完基准测试才回写成具体值），auto 在 MuMu 上
# 解析为 nemu_ipc，因此必须一并处理，不能等到引擎回写后再对齐。
_HYA_SCREENSHOT = {
    "nemu_ipc": "nemu_ipc",
    "window_background": "window_background",
    "auto": "nemu_ipc",
}
_HYA_CONTROL = {
    "minitouch": "minitouch",
    "window_message": "window_message",
    "auto": "minitouch",
}


def _align_hyakkiyakou_device(instance: str) -> None:
    path = _instance_path(instance)
    cfg = _load(path)
    device = (cfg.get("script") or {}).get("device") or {}
    hya = cfg.get("hyakkiyakou")
    if not isinstance(hya, dict):
        return
    debug = hya.get("debug_config")
    if not isinstance(debug, dict):
        debug = {}
        hya["debug_config"] = debug
    shot = _HYA_SCREENSHOT.get(device.get("screenshot_method"))
    ctrl = _HYA_CONTROL.get(device.get("control_method"))
    if not device.get("handle"):
        # 没有窗口句柄树：window_* 一定崩，直接走另一条不依赖句柄的通路
        shot, ctrl = "nemu_ipc", "minitouch"
    changed = False
    if shot and debug.get("hya_screenshot_method") != shot:
        debug["hya_screenshot_method"] = shot
        changed = True
    if ctrl and debug.get("hya_control_method") != ctrl:
        debug["hya_control_method"] = ctrl
        changed = True
    if changed:
        _save(path, cfg)


def _repair_device_enums() -> None:
    """老版本把 control_method 写成 "ADB"，pydantic 会拒绝整个实例配置。

    启动时扫一遍 config/*.json，把这两个字段折回引擎认的写法。
    """
    shot_ok = {"auto", "ADB", "ADB_nc", "uiautomator2", "DroidCast", "DroidCast_raw",
               "scrcpy", "window_background", "nemu_ipc"}
    ctrl_ok = {"adb", "uiautomator2", "minitouch", "window_message"}
    shot_map = {s.lower(): s for s in shot_ok}
    ctrl_map = {c.lower(): c for c in ctrl_ok}
    for path in CONFIG_DIR.glob("*.json"):
        if path.name.startswith("gui_") or path.name in ("template.json", "plans.json"):
            continue
        try:
            cfg = _load(path)
            device = ((cfg or {}).get("script") or {}).get("device")
            if not isinstance(device, dict):
                continue
            changed = False
            for key, allowed, mapping in (("screenshot_method", shot_ok, shot_map),
                                          ("control_method", ctrl_ok, ctrl_map)):
                cur = device.get(key)
                if not isinstance(cur, str) or cur in allowed:
                    continue
                fixed = mapping.get(cur.lower())
                if fixed and fixed != cur:
                    device[key] = fixed
                    changed = True
            if device.get("control_method") != "minitouch":
                # 操作方式固定 minitouch；上一版改成 adb 的实例这里改回来
                device["control_method"] = "minitouch"
                changed = True
            if changed:
                _save(path, cfg)
        except Exception:  # noqa: BLE001 - 坏文件留给引擎自己报
            continue


def _ensure_minitouch(instance: str) -> None:
    """操作方式固定用 minitouch：起任务前确保设备上有二进制、进程在跑。"""
    try:
        path = _instance_path(instance)
        cfg = json.loads(path.read_text(encoding="utf-8-sig"))
        device = (cfg.get("script") or {}).get("device") or {}
        serial = str(device.get("serial") or "")
        if not serial:
            return
        state = minitouch_setup.ensure(serial)
        if not state.get("running"):
            print(f"[minitouch] {instance} ({serial}) 未能启动：{state}", flush=True)
    except Exception as exc:  # noqa: BLE001 - 兜底失败不该拦住任务
        print(f"[minitouch] 准备失败：{exc}", flush=True)


def _spawn_run(instance: str, task: str, force_fight: bool, batch: str | None = None,
               plan: dict | None = None) -> str:
    _instance_path(instance)
    _ensure_minitouch(instance)
    if (task or "").lower() == "hyakkiyakou":
        _align_hyakkiyakou_device(instance)
    run_id = uuid.uuid4().hex[:10]
    log_path = ROOT / "log" / "gui" / f"{run_id}_{instance}_{task}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    plan_file = None
    if plan is not None:
        # 方案可能很长，命令行装不下：落一份临时 JSON，子进程读文件，跑完清掉
        plan_file = ROOT / "log" / "gui" / f"{run_id}_{instance}_plan.json"
        plan_file.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        cmd = [str(PYTHON), "-X", "utf8", "-B", str(ROOT / "gui" / "custom_click_runner.py"),
               "--config", instance, "--plan-file", str(plan_file),
               "--parent-pid", str(os.getpid())]
    else:
        cmd = [str(PYTHON), "-X", "utf8", "-B", str(ROOT / "gui" / "runner.py"),
               "--config", instance, "--task", task,
               "--parent-pid", str(os.getpid())]
        if force_fight:
            cmd.append("--force-fight")
    popen_kwargs = {}
    if os.name == "nt":
        # 无窗口运行：bridge 本身由 Electron 以 windowsHide 拉起（无控制台），
        # 不加此标志每个 runner 子进程都会弹一个黑色控制台窗口。
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", bufsize=1,
                            **popen_kwargs)
    run = {
        "id": run_id,
        "instance": instance,
        "task": task,
        "batch": batch,
        "status": "running",
        "started": datetime.now().isoformat(timespec="seconds"),
        "finished": None,
        "result": None,
        "log_path": str(log_path),
        "proc": proc,
        "lines": deque(maxlen=4000),
    }
    with _RUN_LOCK:
        _RUNS[run_id] = run

    def _pump() -> None:
        with open(log_path, "w", encoding="utf-8", errors="replace") as fh:
            for line in proc.stdout:  # type: ignore[union-attr]
                line = line.rstrip("\n")
                run["lines"].append(line)
                fh.write(line + "\n")
                fh.flush()
                if "=== RESULT:" in line:
                    run["result"] = "True" in line
        code = proc.wait()
        run["status"] = "finished"
        run["finished"] = datetime.now().isoformat(timespec="seconds")
        if run["result"] is None:
            run["result"] = code == 0
        if plan_file is not None:
            try:
                plan_file.unlink(missing_ok=True)
            except OSError:  # Windows 上偶尔被短暂占用，留着也无副作用
                pass

    threading.Thread(target=_pump, daemon=True).start()
    return run_id


@app.post("/api/runs")
def start_run(payload: dict = Body(...)):
    """单步/批量直跑（任务库的「立即验证」用）。"""
    steps = payload.get("steps")
    mode = payload.get("mode", "sequence")
    if not steps and payload.get("flow_id"):
        flow = next((f for f in _load_flows() if f.get("id") == payload["flow_id"]), None)
        if flow is None:
            raise HTTPException(404, "编排表不存在")
        steps = flow["steps"]
    if not steps:
        raise HTTPException(400, "没有可执行的步骤")
    batch = uuid.uuid4().hex[:8]
    run_ids: list[str] = []

    def _spawn_step(step: dict, account: str) -> str:
        plan = (_custom_plan_for_step(step) if step.get("task") == catalog.CUSTOM_CLICK_KEY
                else None)
        return _spawn_run(account, step["task"], bool(step.get("force_fight")), batch, plan)

    if mode == "parallel":
        for step in steps:
            account = step.get("account") or (payload.get("instance") or "")
            run_ids.append(_spawn_step(step, account))
    else:
        first, rest = steps[0], steps[1:]
        run_ids.append(_spawn_step(first, first.get("account") or payload.get("instance") or ""))

        def _chain() -> None:
            current = run_ids[0]
            queue = list(rest)
            while True:
                while True:
                    time.sleep(1.0)
                    run = _RUNS.get(current)
                    if run and run["status"] != "running":
                        break
                if not queue:
                    return
                nxt = queue.pop(0)
                current = _spawn_step(nxt, nxt.get("account") or payload.get("instance") or "")
                run_ids.append(current)

        threading.Thread(target=_chain, daemon=True).start()

    return {"ok": True, "batch": batch, "mode": mode, "run_ids": run_ids}


@app.get("/api/runs")
def list_runs():
    with _RUN_LOCK:
        items = []
        for run in _RUNS.values():
            items.append({k: run[k] for k in
                          ("id", "instance", "task", "batch", "status", "started",
                           "finished", "result", "log_path")})
        items.sort(key=lambda r: r["started"] or "", reverse=True)
        return {"runs": items}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, offset: int = Query(0, ge=0)):
    run = _RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, "运行不存在")
    lines = list(run["lines"])
    return {
        "id": run_id, "instance": run["instance"], "task": run["task"],
        "status": run["status"], "result": run["result"], "started": run["started"],
        "finished": run["finished"], "lines": lines[offset:], "total": len(lines),
        "log_path": run["log_path"],
    }


@app.post("/api/runs/{run_id}/stop")
def stop_run(run_id: str):
    run = _RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, "运行不存在")
    proc = run["proc"]
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
    run["status"] = "stopped"
    run["finished"] = datetime.now().isoformat(timespec="seconds")
    return {"ok": True}


@app.get("/api/runs/{run_id}/stream")
def stream_run(run_id: str):
    run = _RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, "运行不存在")

    def _gen():
        cursor = 0
        while True:
            lines = list(run["lines"])
            if cursor < len(lines):
                chunk = lines[cursor:]
                cursor = len(lines)
                yield "data: " + json.dumps(
                    {"lines": chunk, "status": run["status"], "result": run["result"]},
                    ensure_ascii=False) + "\n\n"
            elif run["status"] != "running":
                yield "data: " + json.dumps(
                    {"lines": [], "status": run["status"], "result": run["result"]},
                    ensure_ascii=False) + "\n\n"
                return
            time.sleep(0.6)

    return StreamingResponse(_gen(), media_type="text/event-stream")


# ────────────────────────── 静态托管 ──────────────────────────

@app.get("/")
def index():
    # 注入资源版本号（按 mtime）并禁缓存：浏览器缓存旧 index.html / app.js
    # 会出现「新 JS 引用不存在的 DOM」的混搭，导致点执行后前端抛错。
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    for asset in ("app.css", "app.js"):
        mtime = int((STATIC_DIR / asset).stat().st_mtime)
        html = html.replace(f"/static/{asset}", f"/static/{asset}?v={mtime}")
    return Response(content=html, media_type="text/html",
                    headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _warm_scan_worker() -> None:
    """后台先把识别进程拉起来（导入引擎 + 载 OCR 模型约 5 秒），
    再给已有账号把 Device 也建好（每台约 3 秒），
    这样用户点绑定时第一次识别也是秒开，不用再等冷启动。"""
    try:
        with _SCAN_LOCK:
            if _SCAN_WORKER.get("proc") is None:
                _scan_worker_start()
    except Exception:  # noqa: BLE001 - 预热失败不影响功能，识别时还会再拉一次
        return
    devices = set(_adb_devices())
    for path in _instance_files():
        try:
            cfg = _load(path)
            serial = str(((cfg.get("script") or {}).get("device") or {}).get("serial") or "")
        except Exception:  # noqa: BLE001 - 读不到配置就跳过这一台
            continue
        # 模拟器没开时不要去建 Device：引擎的 Device() 发现 serial 不在线会自动
        # 调 emulator_start() 把模拟器拉起来，用户只是打开 YYJio 就会多开一个模拟器。
        if serial and devices and serial not in devices:
            continue
        try:
            _scan_worker_call({"cmd": "warm", "config": path.stem}, timeout=40)
        except Exception:  # noqa: BLE001 - 单台预热失败忽略
            break


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=22390)
    args = parser.parse_args()
    import uvicorn
    _start_server_daemon()
    # 先把老版本写坏的控制方式/截图方式折回引擎认的写法，再预热
    _repair_device_enums()
    minitouch_setup.seed_cache()
    threading.Thread(target=_warm_scan_worker, name="warm-profile-scan", daemon=True).start()
    print(f"{APP_NAME} bridge → http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
