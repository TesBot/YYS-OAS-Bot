"""让设备上的 minitouch 可用：随包自带的二进制 + 预置 uiautomator2 缓存。

引擎缺 minitouch 时会自己联网下载（走 GitHub / tool.appetizer.io），
国内网络经常直接失败，任务就崩在下载上。这里做两件事：
  1. 起任务前把安装包里的二进制推到 /data/local/tmp 并拉起进程；
  2. 启动时把二进制塞进 uiautomator2 的缓存目录，
     这样即使引擎自己走安装流程，也能命中缓存、不再联网。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSET_DIR = ROOT / "assets" / "minitouch"
REMOTE = "/data/local/tmp/minitouch"
URL_TEMPLATE = ("https://github.com/openatx/stf-binaries/raw/0.3.0/"
                "node_modules/@devicefarmer/minitouch-prebuilt/prebuilt/{abi}/bin/minitouch")
ABIS = ("x86_64", "x86", "armeabi-v7a", "arm64-v8a")


def _log(msg: str) -> None:
    try:
        print(f"[minitouch] {msg}", flush=True)
    except Exception:  # noqa: BLE001
        pass


def _adb() -> str:
    """优先用随运行时带的 adb，和引擎用的同一个。"""
    candidates = [
        Path(sys.prefix) / "Lib" / "site-packages" / "adbutils" / "binaries" / "adb.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "YYJio" / "runtime" / "python" / "Lib"
        / "site-packages" / "adbutils" / "binaries" / "adb.exe",
    ]
    for one in candidates:
        if one.is_file():
            return str(one)
    found = shutil.which("adb")
    return found or "adb"


def _run(args: list[str], timeout: float = 30.0) -> tuple[int, str]:
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        res = subprocess.run(args, capture_output=True, timeout=timeout, **kwargs)
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)
    out = (res.stdout or b"") + (res.stderr or b"")
    return res.returncode, out.decode("utf-8", "replace").strip()


def local_bin(abi: str) -> Path | None:
    path = ASSET_DIR / f"minitouch-{abi}"
    return path if path.is_file() and path.stat().st_size > 0 else None


def device_abi(serial: str) -> str:
    code, out = _run([_adb(), "-s", serial, "shell", "getprop", "ro.product.cpu.abi"])
    abi = out.strip().splitlines()[-1].strip() if out.strip() else ""
    if abi in ABIS:
        return abi
    if abi.startswith("arm64"):
        return "arm64-v8a"
    if abi.startswith("arm"):
        return "armeabi-v7a"
    if abi in ("x86_64", "x86"):
        return abi
    return "x86_64"


def remote_size(serial: str) -> int:
    code, out = _run([_adb(), "-s", serial, "shell", f"stat -c %s {REMOTE} 2>/dev/null"])
    try:
        return int(out.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        return 0


def running(serial: str) -> bool:
    code, out = _run([_adb(), "-s", serial, "shell", "ps -A 2>/dev/null | grep -c minitouch"])
    try:
        return int(out.strip().splitlines()[-1] or 0) > 0
    except Exception:  # noqa: BLE001
        return False


def ensure_binary(serial: str) -> bool:
    """确保 /data/local/tmp/minitouch 存在且大小对（同大小视为已就绪）。"""
    abi = device_abi(serial)
    src = local_bin(abi)
    if src is None:
        _log(f"安装包里没有 {abi} 的二进制")
        return False
    want = src.stat().st_size
    if remote_size(serial) == want:
        return True
    tmp = REMOTE + ".new"
    code, out = _run([_adb(), "-s", serial, "push", str(src), tmp], timeout=120)
    if code != 0:
        _log(f"推送失败：{out[:200]}")
        return False
    _run([_adb(), "-s", serial, "shell", f"chmod 755 {tmp} && mv -f {tmp} {REMOTE}"])
    return remote_size(serial) == want


def start_if_needed(serial: str) -> bool:
    if running(serial):
        return True
    _run([_adb(), "-s", serial, "shell",
          f"nohup {REMOTE} -n minitouch >/dev/null 2>&1 &"])
    return running(serial)


def ensure(serial: str) -> dict:
    state = {"serial": serial}
    try:
        state["abi"] = device_abi(serial)
        state["binary"] = ensure_binary(serial)
        state["running"] = start_if_needed(serial) if state["binary"] else False
    except Exception as exc:  # noqa: BLE001
        state["error"] = str(exc)
        state["running"] = False
    return state


def cache_path(abi: str) -> Path:
    """与 uiautomator2 的 init.gen_cachepath 保持一致的文件路径。"""
    url = URL_TEMPLATE.format(abi=abi)
    name = url.split("/")[-1]
    digest = hashlib.sha224(url.encode()).hexdigest()[:10]
    return Path(os.path.expanduser("~")) / ".uiautomator2" / "cache" / f"{name}-{digest}" / name


def seed_cache() -> int:
    """把内置二进制放进 u2 缓存，避免引擎自己联网下载。"""
    done = 0
    for abi in ABIS:
        src = local_bin(abi)
        if src is None:
            continue
        try:
            dest = cache_path(abi)
            if dest.is_file() and dest.stat().st_size == src.stat().st_size:
                done += 1
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            done += 1
        except Exception:  # noqa: BLE001
            continue
    if done:
        _log(f"已内置 {done} 个 ABI 的二进制，uiautomator2 不会联网下载")
    return done


def probe(serial: str) -> dict:
    """诊断用：看看设备上现在有没有、跑没跑。"""
    return {"serial": serial, "abi": device_abi(serial),
            "remote_size": remote_size(serial), "running": running(serial)}
