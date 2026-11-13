# -*- coding: utf-8 -*-
"""OAS Studio 桥接服务。

职责边界（UI 与引擎解耦的关键层）：
- 对 UI：只暴露领域模型（实例 / 任务 / 计划 / 运行），REST + SSE，不泄露引擎内部结构；
- 对引擎：读写 config/*.json、以子进程方式调用 gui/runner.py、聚合日志与状态。

启动：
    .venv\\Scripts\\python.exe -X utf8 -B gui/bridge.py --port 22390
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
STATIC_DIR = Path(__file__).resolve().parent / "static"
PLAN_FILE = CONFIG_DIR / "plans.json"
FLOW_FILE = CONFIG_DIR / "gui_flows.json"
FLOW_LIBRARY_FILE = CONFIG_DIR / "gui_flow_library.json"
PROFILE_FILE = CONFIG_DIR / "gui_profiles.json"
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

app = FastAPI(title="OAS Studio Bridge", version="1.0.0")

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
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"配置解析失败 {path.name}: {exc}") from exc


def _save(path: Path, data: dict) -> None:
    with _CONFIG_LOCK:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        shutil.copy(path, path.with_suffix(".json.bak")) if path.exists() else None
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
        return {"key": k, "name": name, "category": cat, "desc": desc,
                "team": team, "hidden": cat in catalog.HIDDEN_CATEGORIES}

    return {
        "tasks": [_entry(k, v[0], v[1], v[2], v[3]) for k, v in catalog.TASK_META.items()]
        + [dict(t, pseudo=True, hidden=False,
                category=catalog.CATEGORY_ALIAS.get(t.get("category", ""), t.get("category", "")))
           for t in catalog.PSEUDO_TASKS],
        "categories": [
            {"key": c, **catalog.CATEGORY_META.get(c, {})} for c in catalog.CATEGORY_ORDER
        ],
        "issues": catalog.KNOWN_ISSUES,
        "field_hints": [{"match": m, "hint": h} for m, h in catalog.FIELD_HINTS],
        "flow_templates": catalog.FLOW_TEMPLATES,
        "summary_keys": catalog.SUMMARY_KEYS,
        "team_tasks": sorted(catalog.TEAM_TASKS),
    }


def _device_detail(serials: list[str]) -> list[dict]:
    """把 serial 列表补全为带型号/分辨率、且标注已绑定实例的设备详情。"""
    detail = []
    for serial in serials:
        item = {"serial": serial, "model": None, "resolution": None, "density": None}
        try:
            out = subprocess.run([str(ADB), "-s", serial, "shell", "wm", "size"],
                                 capture_output=True, text=True, timeout=6)
            item["resolution"] = out.stdout.strip().split(":")[-1].strip() or None
            out = subprocess.run([str(ADB), "-s", serial, "shell", "wm", "density"],
                                 capture_output=True, text=True, timeout=6)
            item["density"] = out.stdout.strip().split(":")[-1].strip() or None
            out = subprocess.run([str(ADB), "-s", serial, "shell", "getprop", "ro.product.model"],
                                 capture_output=True, text=True, timeout=6)
            item["model"] = out.stdout.strip() or None
        except Exception:  # noqa: BLE001
            pass
        detail.append(item)
    bound = {}
    for path in _instance_files():
        cfg = _load(path)
        serial = ((cfg.get("script") or {}).get("device") or {}).get("serial")
        if serial:
            bound[serial] = path.stem
    for item in detail:
        item["bound_to"] = bound.get(item["serial"])
    return detail


@app.get("/api/devices")
def list_devices(probe: bool = False):
    """实时扫描 adb 在线设备，供「账号绑定」选择。

    模拟器重启后 adb 连接常常是掉的（devices 为空），此时先按已知
    serial / MuMu 常用端口主动 connect 一次再扫。

    ``probe=1``：不论当前列表是否为空，都先做一轮主动 connect。用户点了
    「刷新设备」就传这个，因为新开的 MuMu 实例不会自动注册到 adb server。
    """
    if probe:
        _adb_reconnect_known(set(_adb_devices()))
    devices = _adb_devices()
    if not devices:
        _adb_reconnect_known()
        devices = _adb_devices()
    detail = _device_detail(devices)
    return {"devices": detail, "count": len(detail)}


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
    for key, value in (payload.get("device") or {}).items():
        device[key] = value
    _save(target, template)
    return {"ok": True, "name": name}


@app.patch("/api/instances/{name}")
def update_instance(name: str, payload: dict = Body(...)):
    path = _instance_path(name)
    cfg = _load(path)
    device = cfg.setdefault("script", {}).setdefault("device", {})
    for key, value in (payload.get("device") or {}).items():
        device[key] = value
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

    # 4. 删除配置
    path.unlink()
    return {"ok": True, "remaining": len(_instance_files())}


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


def _normalize_flow(flow: dict) -> dict:
    steps = [_normalize_step(s, i) for i, s in enumerate(flow.get("steps") or [])]
    for i, step in enumerate(steps):
        step["order"] = i
    return {
        "id": flow.get("id") or f"f{uuid.uuid4().hex[:8]}",
        "name": (flow.get("name") or "未命名编排").strip(),
        "accounts": [a for a in (flow.get("accounts") or []) if a],
        "steps": steps,
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
            merged = {**flow, **{k: payload[k] for k in ("name", "accounts", "steps") if k in payload}}
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
        out.append({"task": task, "enabled": bool(s.get("enabled", True)),
                    "mode": mode, "patch": s.get("patch") or {}, "note": s.get("note") or ""})
    return out


@app.get("/api/flow-library")
def list_flow_library():
    return {"templates": _load_flow_library()}


@app.post("/api/flow-library")
def save_flow_template(payload: dict = Body(...)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "方案名称不能为空")
    steps = payload.get("steps")
    if steps is None:
        src = next((f for f in _load_flows() if f.get("id") == payload.get("flow_id")), None)
        if src is None:
            raise HTTPException(404, "编排表不存在")
        steps = src.get("steps")
    steps = _template_steps(steps)
    if not steps:
        raise HTTPException(400, "没有可保存的任务步骤")
    templates = [t for t in _load_flow_library() if t.get("name") != name]  # 同名覆盖
    tpl = {"id": f"t{uuid.uuid4().hex[:8]}", "name": name, "steps": steps,
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


# ────────────────────────── 编排执行 ──────────────────────────

_JOBS: dict[str, dict] = {}
_JOB_LOCK = threading.RLock()


def _apply_step_config(instance: str, task: str, patch: dict, role: str | None) -> None:
    """把编排步骤上的参数写入实例配置；无配置段的动作任务（如回庭院）直接跳过。"""
    path = _instance_path(instance)
    cfg = _load(path)
    section = cfg.get(task)
    if not isinstance(section, dict):
        if patch:
            raise HTTPException(400, f"{instance} 缺少任务配置: {task}（该任务不支持参数）")
        return
    if patch:
        _deep_merge(section, patch)
    if role:
        status_path = _team_status_path(cfg, task)
        if status_path:
            head, leaf = status_path.split(".", 1)
            section.setdefault(head, {})[leaf] = role
    _save(path, cfg)


@app.post("/api/flows/{flow_id}/run")
def run_flow(flow_id: str):
    flow = next((f for f in _load_flows() if f.get("id") == flow_id), None)
    if flow is None:
        raise HTTPException(404, "编排表不存在")
    flow = _normalize_flow(flow)
    if not flow["accounts"]:
        raise HTTPException(400, "编排表未绑定账号")
    for account in flow["accounts"]:
        _instance_path(account)
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
            "accounts": list(flow["accounts"]),
            "status": "running",
            "started": datetime.now().isoformat(timespec="seconds"),
            "finished": None,
            "index": -1,
            "current": None,
            "steps": [{"task": s["task"], "mode": s["mode"], "enabled": s["enabled"],
                       "status": "pending", "runs": []} for s in flow["steps"]],
            "error": None,
        }
        _JOBS[job["id"]] = job

    def _worker() -> None:
        accounts = flow["accounts"]
        active_team: dict | None = None
        try:
            for idx, step in enumerate(flow["steps"]):
                if job["status"] == "cancelled":
                    break
                if not step["enabled"]:
                    job["steps"][idx]["status"] = "skipped"
                    continue
                if step["task"] == catalog.TEAM_SETUP_KEY:
                    # 组队步骤不启动进程，只登记队伍名单供后续步骤使用
                    team = step.get("team") or {}
                    if not team.get("leader"):
                        job["steps"][idx]["status"] = "fail"
                        job["error"] = f"步骤 {idx + 1}：自定义组队缺少队长"
                        break
                    active_team = team
                    job["team"] = team
                    job["steps"][idx]["status"] = "ok"
                    continue
                job["index"] = idx
                job["current"] = step["task"]
                pairs = _participants(step, accounts, active_team)
                if not pairs:
                    job["steps"][idx]["status"] = "fail"
                    job["error"] = (f"步骤 {idx + 1}：组队步骤至少需要 2 个可用账号"
                                    if step.get("mode") == "team"
                                    else f"步骤 {idx + 1}：没有可执行账号")
                    break
                run_ids: list[str] = []
                for account, role in pairs:
                    try:
                        _apply_step_config(account, step["task"], step["patch"], role)
                    except HTTPException as exc:
                        job["steps"][idx]["status"] = "fail"
                        job["error"] = str(exc.detail)
                        raise
                    run_ids.append(_spawn_run(account, step["task"],
                                              bool(step.get("force_fight")), job["id"]))
                job["steps"][idx]["status"] = "running"
                job["steps"][idx]["runs"] = run_ids
                while True:
                    time.sleep(1.0)
                    if job["status"] == "cancelled":
                        break
                    states = [_RUNS[r]["status"] for r in run_ids if r in _RUNS]
                    if states and all(s != "running" for s in states):
                        break
                if job["status"] == "cancelled":
                    job["steps"][idx]["status"] = "cancelled"
                    break
                ok = all((_RUNS[r].get("result") is True) for r in run_ids if r in _RUNS)
                job["steps"][idx]["status"] = "ok" if ok else "fail"
                if not ok:
                    job["error"] = f"步骤 {idx + 1} 执行失败"
                    break
            if job["status"] != "cancelled":
                job["status"] = "finished" if not job.get("error") else "failed"
        except Exception as exc:  # noqa: BLE001
            job["status"] = "failed"
            job["error"] = f"{type(exc).__name__}: {exc}"
        finally:
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


@app.post("/api/jobs/{job_id}/stop")
def stop_job(job_id: str):
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    job["status"] = "cancelled"
    for step in job["steps"]:
        for run_id in step.get("runs") or []:
            run = _RUNS.get(run_id)
            if run and run["status"] == "running":
                try:
                    run["proc"].terminate()
                except Exception:  # noqa: BLE001
                    pass
    return {"ok": True}



# ────────────────────────── 运行 ──────────────────────────

def _spawn_run(instance: str, task: str, force_fight: bool, batch: str | None = None) -> str:
    _instance_path(instance)
    run_id = uuid.uuid4().hex[:10]
    log_path = ROOT / "log" / "gui" / f"{run_id}_{instance}_{task}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
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

    if mode == "parallel":
        for step in steps:
            account = step.get("account") or (payload.get("instance") or "")
            run_ids.append(_spawn_run(account, step["task"],
                                      bool(step.get("force_fight")), batch))
    else:
        first, rest = steps[0], steps[1:]
        run_ids.append(_spawn_run(first.get("account") or payload.get("instance") or "",
                                  first["task"], bool(first.get("force_fight")), batch))

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
                current = _spawn_run(nxt.get("account") or payload.get("instance") or "",
                                     nxt["task"], bool(nxt.get("force_fight")), batch)
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=22390)
    args = parser.parse_args()
    import uvicorn
    _start_server_daemon()
    print(f"OAS Studio bridge → http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
