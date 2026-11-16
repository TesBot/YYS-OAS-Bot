# -*- coding: utf-8 -*-
"""控制台「自定义点击」执行器 + 实时画面截取。

只在 engine/gui/（控制台层）新增，不修改 module/ 与 tasks/ 下任何引擎内核文件。
所有画面与模拟动作一律复用引擎既有能力，不自造随机算法：

    module.device.device.Device              截图 + 点击（control_method 自带拟人化）
    module.ocr.base_ocr.BaseCor              中文 OCR（含 score 过滤 / 预处理 / 后处理）
    module.base.utils.random_rectangle_point 矩形内正态随机落点
    module.base.protect.random_sleep         概率触发的防封长休眠
    Device.sleep((min, max))                 ensure_time 正态随机间隔

两种用法（cwd 必须是引擎根目录，由 bridge 保证）：
    python -X utf8 -B gui/custom_click_runner.py --config oas1 --plan-file <plan.json>
    python -X utf8 -B gui/custom_click_runner.py --config oas1 --capture <out.png>

输出约定与 gui/runner.py 一致，bridge 的 _pump 靠 === RESULT: 判定成功失败。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FULL_ROI = (0, 0, 1280, 720)  # 引擎强制 1280x720，见 screenshot.py:206


def log(msg: str) -> None:
    print(f"[自定义点击] {msg}", flush=True)


def build_device(config_name: str):
    """最小初始化：直接构造 Device，不必走 Script（避免调度器/防封作息等冗余状态）。"""
    from module.config.config import Config
    from module.device.device import Device

    device = Device(config=Config(config_name=config_name))
    # 自研循环会长时间盯着同一画面，不关掉会被引擎 60s stuck 检测误杀
    device.disable_stuck_detection()
    return device


def build_ocr(roi, score: float):
    """用引擎的 BaseCor 做全屏/局部 OCR，自带 score 过滤与文本后处理。"""
    from module.ocr.base_ocr import BaseCor

    x1, y1, x2, y2 = roi
    box = (x1, y1, x2 - x1, y2 - y1)  # BaseCor 用 (x, y, w, h)
    ocr = BaseCor(name="custom_click", mode="Full", method="Default",
                  roi=box, area=box, keyword="")
    ocr.score = float(score)
    return ocr


def ocr_texts(device, engine_ocr, roi, image=None) -> list[dict]:
    """返回 [{'text', 'score', 'rect'}]；rect 是相对整张 1280x720 的坐标。
    可由调用方传入已截取的帧，避免同一帧截图两次。"""
    if image is None:
        image = device.screenshot()  # np.ndarray, RGB, (720, 1280, 3)
    results = engine_ocr.detect_and_ocr(image)
    x1, y1, _, _ = roi
    out = []
    for item in results or []:
        text = str(getattr(item, "ocr_text", "") or "").strip()
        if not text:
            continue
        sc = float(getattr(item, "score", 0) or 0)
        box = getattr(item, "box", None)
        rect = None
        if box is not None:
            pts = box.tolist() if hasattr(box, "tolist") else list(box)
            xs = [float(p[0]) for p in pts]
            ys = [float(p[1]) for p in pts]
            # BaseCor 先按 roi 裁剪再识别，box 是相对 roi 左上角的坐标
            rect = [int(min(xs) + x1), int(min(ys) + y1),
                    int(max(xs) + x1), int(max(ys) + y1)]
        out.append({"text": text, "score": round(sc, 3), "rect": rect})
    return out


def check(items: list[dict], texts: list[str], forbid: list[str], match: str) -> tuple[bool, str]:
    """文字条件判定。子串包含匹配；禁止词优先；match = all / any。"""
    joined = "".join(x["text"] for x in items)
    if any(f and f in joined for f in forbid):
        bad = next(f for f in forbid if f and f in joined)
        return False, f"命中禁止文字「{bad}」"
    if not texts:
        return True, "未设置文字条件，跳过画面判定"
    hits = [t for t in texts if t in joined or any(t in x["text"] for x in items)]
    if match == "any":
        ok = bool(hits)
    else:
        ok = len(hits) == len(texts)
    return ok, f"命中 {len(hits)}/{len(texts)} 条文字"


def as_range(value, default: tuple[float, float]) -> tuple[float, float]:
    """把用户填的 [min, max] 规整成合法的浮点区间，供 device.sleep 随机化。"""
    try:
        a, b = (float(v) for v in (value or default)[:2])
    except (TypeError, ValueError):
        return default
    a, b = max(0.0, min(a, 300.0)), max(0.0, min(b, 300.0))
    return (a, b) if a <= b else (b, a)


def as_rect(value) -> tuple[int, int, int, int]:
    try:
        x1, y1, x2, y2 = (int(round(float(v))) for v in (value or FULL_ROI)[:4])
    except (TypeError, ValueError):
        return FULL_ROI
    x1, x2 = sorted((max(0, min(x1, 1280)), max(0, min(x2, 1280))))
    y1, y2 = sorted((max(0, min(y1, 720)), max(0, min(y2, 720))))
    if x2 - x1 < 2:
        x2 = min(1280, x1 + 2)
    if y2 - y1 < 2:
        y2 = min(720, y1 + 2)
    return x1, y1, x2, y2


def as_repeat(value) -> dict:
    """层级内循环配置。旧方案没有 repeat 字段时按「仅一次」处理。"""
    value = value if isinstance(value, dict) else {}
    mode = value.get("mode")
    if mode not in ("once", "count", "forever"):
        mode = "once"
    try:
        count = max(1, min(int(value.get("count") or 2), 999))
    except (TypeError, ValueError):
        count = 2
    try:
        gap = max(0.0, min(float(value.get("gap") or 0), 300.0))
    except (TypeError, ValueError):
        gap = 0.0
    return {"mode": mode, "count": count, "gap": gap,
            "recheck": value.get("recheck") is not False}


def as_jump(value, total) -> int:
    """本层执行完要跳转到的层号（1-based）；0 = 不跳转，越界一律归零。"""
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return n if 1 <= n <= total else 0


def as_idle(value) -> dict:
    """编排级「随机发呆」。由 bridge 运行时注入 plan，不写进方案库，
    因此同一份自定义点击方案在不同编排里可以配不同发呆策略。"""
    value = value if isinstance(value, dict) else {}

    def seconds(key, default):
        try:
            raw = value.get(key)
            return max(0.0, min(float(default if raw is None else raw), 600.0))
        except (TypeError, ValueError):
            return default

    lo, hi = seconds("min", 2.0), seconds("max", 6.0)
    if hi < lo:
        lo, hi = hi, lo
    try:
        prob = max(0.0, min(float(value.get("probability", 0.15)), 1.0))
    except (TypeError, ValueError):
        prob = 0.15
    return {"enable": value.get("enable") is True,
            "min": round(lo, 2), "max": round(hi, 2), "probability": round(prob, 3)}


def maybe_idle(device, idle: dict, tag: str, stats: list[int]) -> bool:
    """按概率随机静止一段时间，期间零操作。时长走引擎 ensure_time 的正态随机通道。"""
    if not idle["enable"] or idle["probability"] <= 0 or idle["max"] <= 0:
        return False
    if random.random() >= idle["probability"]:
        return False
    from module.base.utils.utils import ensure_time

    sec = round(max(0.0, ensure_time((idle["min"], idle["max"]))), 2)
    if sec <= 0:
        return False
    log(f"  ⏸ {tag} 随机发呆 {sec:g}s")
    device.sleep(sec)
    stats[0] += 1
    return True


FRAME_DIFF_THRESHOLD = 1.5    # 缩略灰度平均差，低于视为画面静止
FRAME_LOCAL_THRESHOLD = 24.0  # 局部明显变化的像素差
FRAME_LOCAL_RATIO = 0.002     # 局部变化像素占比，兜底「只冒出一小块文字」
OCR_FORCE_INTERVAL = 1.2      # 秒：画面静止时最长多久强制 OCR 一次
OCR_MIN_INTERVAL = 0.6        # 秒：画面持续变化时两次 OCR 的最小间隔


def frame_fingerprint(image):
    """抽样缩略灰度指纹，只用于判断画面是否变化；成本约为一次全屏 OCR 的百分之一。"""
    import numpy as np

    return np.asarray(image[::10, ::10, :], dtype=np.float32).mean(axis=2)


def frame_changed(prev, cur) -> bool:
    if prev is None or cur is None or getattr(prev, "shape", None) != getattr(cur, "shape", None):
        return True
    import numpy as np

    diff = np.abs(prev - cur)
    if float(diff.mean()) >= FRAME_DIFF_THRESHOLD:
        return True
    # 整屏大面积不动、只出现一小块文字/按钮时，均值会被稀释，用局部变化兜底
    return float((diff >= FRAME_LOCAL_THRESHOLD).mean()) >= FRAME_LOCAL_RATIO


class FrameOCR:
    """画面不变时复用上次 OCR 结果，不再每轮轮询都跑一次全屏 OCR。

    每轮只截一帧，这帧同时供战斗检测（device.image）与 OCR 使用；
    点击、战斗、发呆等会改变画面的动作后需 invalidate() 强制重新识别。
    """

    def __init__(self, device, engine_ocr, roi, force_interval=None, min_interval=None):
        self.device = device
        self.engine_ocr = engine_ocr
        self.roi = roi
        self.force_interval = float(OCR_FORCE_INTERVAL if force_interval is None else force_interval)
        self.min_interval = float(OCR_MIN_INTERVAL if min_interval is None else min_interval)
        self._fp = None
        self._items: list[dict] = []
        self._last_ocr = 0.0
        self.ocr_calls = 0
        self.reused = 0

    def observe(self) -> tuple[list[dict], bool]:
        """返回 (当前帧文字, 本帧是否真的跑了 OCR)。"""
        image = self.device.screenshot()
        fp = frame_fingerprint(image)
        now = time.monotonic()
        elapsed = now - self._last_ocr
        changed = frame_changed(self._fp, fp)
        must_ocr = self._fp is None or elapsed >= self.force_interval
        # 画面持续变化（动画/渐变）时也限流，避免把 OCR 拉满；静止画面则直接复用。
        if not must_ocr and (not changed or elapsed < self.min_interval):
            self.reused += 1
            return self._items, False
        items = ocr_texts(self.device, self.engine_ocr, self.roi, image=image)
        self._fp, self._items, self._last_ocr = fp, items, now
        self.ocr_calls += 1
        return items, True

    def invalidate(self) -> None:
        self._fp = None
        self._items = []
        self._last_ocr = 0.0


BATTLE_TIMEOUT = 180.0  # 秒：引擎 battle_wait 无超时，控制台层兜底


class BattleTimeout(Exception):
    """战斗接管超时。"""


def quiet_engine_logs() -> None:
    """自定义点击每 0.3~0.8s OCR 一次，引擎默认 INFO 会把日志刷爆。
    只抬高引擎 logger 级别，WARNING/ERROR 保留；自身进度仍用 print 输出。"""
    import logging
    try:
        from module.logger import logger as engine_logger
        engine_logger.setLevel(logging.WARNING)
        for handler in engine_logger.handlers:
            handler.setLevel(logging.WARNING)
    except Exception:
        pass


def build_battle(config_name: str, device):
    """懒加载引擎通用战斗组件，共用同一个 Device；module/ 与 tasks/ 不改动。"""
    from module.config.config import Config
    from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
    from tasks.Component.GeneralBattle.general_battle import GeneralBattle

    return (GeneralBattle(config=Config(config_name=config_name), device=device),
            GeneralBattleConfig())


def battle_state(gb) -> bool:
    """用引擎资产判断当前帧是否处于战斗生命周期。
    比 is_in_battle() 更严：不把 I_FRIENDS 算进来，避免普通界面误判。
    调用前需已 device.screenshot()，这里复用同一帧，不额外截图。"""
    return bool(gb.appear(gb.I_BATTLE_INFO) or gb.appear(gb.I_PREPARE_HIGHLIGHT)
                or gb.appear(gb.I_WIN) or gb.appear(gb.I_FALSE)
                or gb.appear(gb.I_REWARD))


def run_battle(gb, cfg, device, timeout: float = BATTLE_TIMEOUT) -> bool:
    """引擎 battle_wait 是无超时 while，靠 stuck 检测兜底；本执行器已禁用 stuck 检测，
    因此临时给 device.screenshot 注入计时，超时抛 BattleTimeout 中断。"""
    deadline = time.monotonic() + timeout
    original = device.screenshot

    def timed_screenshot(*args, **kwargs):
        if time.monotonic() >= deadline:
            raise BattleTimeout()
        return original(*args, **kwargs)

    device.screenshot = timed_screenshot
    try:
        return bool(gb.run_general_battle(config=cfg))
    finally:
        device.screenshot = original


# ───────────────────────── 滚动寻找并点击 ─────────────────────────
# 「直接识别并点击」靠 OCR 文字判定，「滚动寻找并点击」靠目标图片匹配：
# 先把鼠标停在用户指定的位置（anchor），一边滚动一边截图比对，命中后再点目标图片。
# 滚动优先投递真实滚轮消息（Win32 WM_MOUSEWHEEL，MuMu/夜神/雷电的客户区句柄都能收），
# 拿不到窗口句柄时退回引擎自带 swipe（minitouch/ADB/uiautomator2/scrcpy），两者都复用引擎既有触控实现。
WM_MOUSEMOVE = 0x0200
WM_MOUSEWHEEL = 0x020A
WHEEL_DELTA = 120            # Win32 单格滚轮增量
SCROLL_DEFAULT_ANCHOR = (640, 400)
SCROLL_DRAG_SPAN = 260       # 拖动兜底时的滑动距离（像素）
SCROLL_METHOD_LABEL = {"auto": "自动", "wheel": "滚轮", "drag": "拖动"}


def as_point(value, default=SCROLL_DEFAULT_ANCHOR) -> tuple[int, int]:
    """鼠标停留点：clamp 进 1280x720。"""
    try:
        x, y = (int(round(float(v))) for v in (value or default)[:2])
    except (TypeError, ValueError):
        return default
    return max(0, min(x, 1279)), max(0, min(y, 719))


def as_scroll(value) -> dict:
    """滚动参数规范化；缺省值就是 UI 上的默认值。"""
    raw = value if isinstance(value, dict) else {}

    def num(key, default, low, high):
        try:
            n = float(raw.get(key, default))
        except (TypeError, ValueError):
            n = float(default)
        return max(low, min(n, high))

    return {
        "anchor": as_point(raw.get("anchor")),
        "direction": "up" if raw.get("direction") == "up" else "down",
        "wheel": int(round(num("wheel", 5, 1, 30))),
        "interval": num("interval", 0.8, 0.2, 5.0),
        "timeout": num("timeout", 15.0, 1.0, 120.0),
        "threshold": num("threshold", 0.8, 0.5, 0.99),
        "method": raw.get("method") if raw.get("method") in ("auto", "wheel", "drag") else "auto",
        "template": str(raw.get("template") or ""),
    }


def decode_template(value):
    """目标图片（base64 PNG，可带 data: 前缀）→ BGR ndarray；无效返回 None。"""
    import base64

    import cv2
    import numpy as np

    data = str(value or "").strip()
    if not data:
        return None
    if data.startswith("data:") and "," in data:
        data = data.split(",", 1)[1]
    try:
        buf = np.frombuffer(base64.b64decode(data, validate=False), np.uint8)
        image = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception:  # noqa: BLE001 - 用户可能存了非图片内容
        return None
    return image if image is not None and image.size else None


def match_template(image, template) -> tuple[float, int, int]:
    """整屏找目标图片，返回 (相似度, 命中中心 x, 命中中心 y)。"""
    import cv2
    import numpy as np

    screen = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    gray = template if template.ndim == 2 else cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    th, tw = gray.shape[:2]
    if th > screen.shape[0] or tw > screen.shape[1]:
        return 0.0, 0, 0
    result = cv2.matchTemplate(screen, gray, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(result)
    return float(score), int(loc[0] + tw / 2), int(loc[1] + th / 2)


def window_handle(device):
    """模拟器客户区句柄；可用句柄位置与引擎 swipe_window_message 的取值一致。

    只有 window_message 控制方式下引擎才会创建窗口句柄对象，adb/minitouch 走的是
    adb shell，属于正常情况（返回 None，调用方退回拖动滚动）。
    """
    try:
        handles = [h for h in (device.control_handle_list or []) if h]
    except Exception:  # noqa: BLE001 - 非 Windows 后端没有窗口句柄
        return None
    if not handles:
        return None
    if len(handles) == 1:  # 雷电
        return handles[0]
    if len(handles) == 2:  # MuMu
        return handles[1]
    return handles[3] if len(handles) > 3 else handles[-1]  # 夜神


def _user32():
    import ctypes
    import os

    if os.name != "nt":
        return None
    user32 = ctypes.windll.user32
    if not getattr(_user32, "ready", False):
        user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                       ctypes.c_size_t, ctypes.c_ssize_t]
        user32.PostMessageW.restype = ctypes.c_bool
        user32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.ClientToScreen.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        _user32.ready = True
    return user32


def _client_to_screen(hwnd, x, y):
    """客户区坐标 → 屏幕坐标（WM_MOUSEWHEEL 的 lParam 用的是屏幕坐标）。"""
    import ctypes
    from ctypes import wintypes

    point = wintypes.POINT(int(x), int(y))
    ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(point))
    return int(point.x), int(point.y)


def wheel_scroll(device, anchor, direction, notches) -> bool:
    """把鼠标停在 anchor 上逐格滚动；只投递移动 + 滚轮消息，不产生点击。"""
    import ctypes
    from ctypes import wintypes

    user32 = _user32()
    if user32 is None:
        return False
    hwnd = window_handle(device)
    if not hwnd:
        return False
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    cw, ch = max(1, rect.right), max(1, rect.bottom)  # 客户区可能被缩放，不是 1280x720
    x, y = anchor
    client_x = int(round(x * cw / 1280.0))
    client_y = int(round(y * ch / 720.0))
    screen_x, screen_y = _client_to_screen(hwnd, client_x, client_y)
    move_lparam = ((client_y & 0xFFFF) << 16) | (client_x & 0xFFFF)
    wheel_lparam = ((screen_y & 0xFFFF) << 16) | (screen_x & 0xFFFF)
    delta = -WHEEL_DELTA if direction == "down" else WHEEL_DELTA
    wparam = (delta & 0xFFFF) << 16
    ok = True
    for _ in range(max(1, int(notches))):
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, move_lparam)   # 先让光标落在该点
        if not user32.PostMessageW(hwnd, WM_MOUSEWHEEL, wparam, wheel_lparam):
            ok = False
            break
        time.sleep(random.uniform(0.05, 0.11))  # 逐格 + 抖动，避免一次甩到底
    return ok


def drag_scroll(device, anchor, direction, span=SCROLL_DRAG_SPAN) -> bool:
    """拖动模拟滚动（滚动向下 = 手指上滑）；按当前 control_method 直接调引擎 swipe。"""
    x, y = anchor
    half = max(40, int(span) // 2)
    y1 = y + half if direction == "down" else y - half
    y2 = y - half if direction == "down" else y + half
    y1, y2 = max(10, min(y1, 709)), max(10, min(y2, 709))
    if abs(y2 - y1) < 20:
        return False
    p1, p2 = (int(x), int(y1)), (int(x), int(y2))
    method = getattr(getattr(device.config.script, "device", None), "control_method", "minitouch")
    try:
        if method == "minitouch":
            device.swipe_minitouch(p1, p2)
        elif method == "window_message":
            device.swipe_window_message(p1, p2)
        elif method == "uiautomator2":
            device.swipe_uiautomator2(p1, p2, duration=0.3)
        elif method == "scrcpy":
            device.swipe_scrcpy(p1, p2)
        else:
            device.swipe_adb(p1, p2, duration=0.3)
    except Exception as exc:  # noqa: BLE001 - 单次滚动失败不该让整层直接崩
        log(f"  … 拖动滚动失败：{type(exc).__name__}: {exc}")
        return False
    return True


def run_scroll_search(device, opt: dict, tag: str) -> tuple[bool, str]:
    """一边滚动一边找图；命中即点目标中心。返回 (是否成功, 说明)。"""
    from module.base.utils import random_rectangle_point

    template = decode_template(opt.get("template"))
    if template is None:
        return False, "未设置目标图片：编辑时先抓图，再在图上框选要点击的图案"
    deadline = time.monotonic() + opt["timeout"]
    best, ticks, method = 0.0, 0, opt["method"]
    log(f"  滚动寻找：鼠标停在 {opt['anchor']}，{'向上' if opt['direction'] == 'up' else '向下'}"
        f" ×{opt['wheel']} 格 / {opt['interval']:g}s，超时 {opt['timeout']:g}s")
    while True:
        score, cx, cy = match_template(device.screenshot(), template)
        best = max(best, score)
        if score >= opt["threshold"]:
            x, y = random_rectangle_point((cx - 8, cy - 8, cx + 8, cy + 8))
            log(f"  ✓ {tag} 找到目标（相似度 {score:.2f}）→ 点击 ({x}, {y})")
            device.click(x, y, control_check=False, control_name="CUSTOM_SCROLL")
            return True, f"相似度 {score:.2f}"
        if time.monotonic() >= deadline:
            break
        ticks += 1
        if method == "drag":
            ok = drag_scroll(device, opt["anchor"], opt["direction"])
        else:
            ok = wheel_scroll(device, opt["anchor"], opt["direction"], opt["wheel"])
            if ok:
                log(f"  … 滚轮 {opt['direction'] == 'up' and '上' or '下'}滚 {opt['wheel']} 格")
            elif method == "wheel":
                return False, "当前控制方式拿不到模拟器窗口句柄，滚轮发不出去；把滚动方式改成「拖动」即可"
            else:  # auto：拿不到句柄就退回拖动，两条路都能滚动
                log("  … 控制方式为 adb/minitouch，拿不到窗口句柄，改用拖动滚动")
                method = "drag"
                ok = drag_scroll(device, opt["anchor"], opt["direction"])
        if not ok:
            return False, "滚动动作执行失败"
        device.sleep(opt["interval"])
    return False, f"滚动 {ticks} 次仍未找到目标（最高相似度 {best:.2f}）"


def run_plan(config_name: str, plan: dict) -> bool:
    from module.base.protect import random_sleep
    from module.base.utils import random_rectangle_point

    device = build_device(config_name)
    steps = plan.get("steps") or []
    timeout = max(1.0, min(float(plan.get("timeout") or 30), 3600))
    poll = as_range(plan.get("poll"), (0.3, 0.8))
    idle = as_idle(plan.get("idle"))
    idle_stats = [0]
    frame_stats = [0, 0]  # [实际 OCR 次数, 静止复用次数]
    log(f"方案「{plan.get('name') or '未命名'}」共 {len(steps)} 层；等待超时 {timeout:g}s"
        + (f"；随机发呆 {idle['min']:g}~{idle['max']:g}s / {idle['probability'] * 100:g}%"
           if idle["enable"] else ""))

    battle_on = plan.get("battle") is not False
    gb = cfg = None
    if battle_on:
        try:
            gb, cfg = build_battle(config_name, device)
            log(f"战斗接管已就绪 · 超时 {BATTLE_TIMEOUT:g}s")
        except Exception as exc:
            log(f"战斗组件不可用，本次跳过接管：{type(exc).__name__}: {exc}")
            battle_on = False
    cooldown_until = 0.0

    def handoff_battle(tag):
        """返回 (alive, handled)。handled 表示刚打完一场，本轮需重新判定画面。"""
        nonlocal cooldown_until
        if not battle_on or time.monotonic() < cooldown_until or not battle_state(gb):
            return True, False
        log(f"  ⚔ {tag} 检测到战斗，交给引擎接管")
        try:
            win = run_battle(gb, cfg, device)
        except BattleTimeout:
            log(f"  ✗ {tag} 战斗超时（{BATTLE_TIMEOUT:g}s）")
            return False, True
        except Exception as exc:
            log(f"  ✗ {tag} 战斗接管异常：{type(exc).__name__}: {exc}")
            return False, True
        log(f"  ⚔ {tag} 战斗结束：{'胜利' if win else '失败'}")
        cooldown_until = time.monotonic() + 3  # 避免奖励残留帧被再次判成战斗
        return bool(win), True

    index = 0
    while index < len(steps):
        i = index + 1
        st = steps[index]
        name = st.get("name") or f"第 {i} 层"
        texts = [str(t).strip() for t in (st.get("texts") or []) if str(t).strip()]
        forbid = [str(t).strip() for t in (st.get("forbid") or []) if str(t).strip()]
        match = "any" if st.get("match") == "any" else "all"
        roi = as_rect(st.get("ocr_roi"))
        rect = as_rect(st.get("rect"))
        score = max(0.1, min(float(st.get("score") or 0.6), 1.0))
        before = as_range(st.get("delay_before"), (0.2, 0.8))
        after = as_range(st.get("delay_after"), (0.4, 1.2))
        rep = as_repeat(st.get("repeat"))
        total = 1 if rep["mode"] == "once" else (rep["count"] if rep["mode"] == "count" else None)
        loop_desc = "仅一次" if total == 1 else (f"{total} 轮" if total else "一直循环")
        scroll_mode = (st.get("mode") or "direct") == "scroll"
        scroll_opt = as_scroll(st.get("scroll")) if scroll_mode else {}
        if scroll_mode:
            log(f"第 {i}/{len(steps)} 层「{name}」：滚动寻找并点击，鼠标点 {scroll_opt['anchor']}，"
                f"{'向上' if scroll_opt['direction'] == 'up' else '向下'}滚动 ×{scroll_opt['wheel']} 格"
                f"（{SCROLL_METHOD_LABEL[scroll_opt['method']]}），"
                f"匹配度 {scroll_opt['threshold']:g}，寻找超时 {scroll_opt['timeout']:g}s，"
                f"本层 {loop_desc}，间隔 {rep['gap']:g}s")
        else:
            log(f"第 {i}/{len(steps)} 层「{name}」：等待文字 {texts or '（无条件）'} "
                f"({match})，识别区 {roi}，点击区 {rect}，本层 {loop_desc}，间隔 {rep['gap']:g}s")

        # 滚动层不看文字，OCR 模型按需构建，避免白载一次识别器
        engine_ocr = None if scroll_mode else build_ocr(roi, score)
        cache = None if scroll_mode else FrameOCR(device, engine_ocr, roi)
        if maybe_idle(device, idle, f"第 {i} 层前", idle_stats) and cache is not None:
            cache.invalidate()
        rounds = 0
        while True:
            rounds += 1
            tag = f"第 {i}/{len(steps)} 层" + (f" 第 {rounds} 轮" if (total is None or total > 1) else "")
            if maybe_idle(device, idle, f"{tag} 前", idle_stats) and cache is not None:
                cache.invalidate()
            if scroll_mode:
                # 滚动层：鼠标停点 + 滚轮 + 逐帧找图，命中后自己点目标中心
                alive, handled = handoff_battle(tag)
                if not alive:
                    print("=== RESULT: False ===", flush=True)
                    return False
                if handled:
                    continue
                device.sleep(before)
                ok, why = run_scroll_search(device, scroll_opt, tag)
                if not ok:
                    log(f"  ✗ {tag} {why}")
                    print("=== RESULT: False ===", flush=True)
                    return False
            elif rep["recheck"] or rounds == 1:
                started = time.monotonic()
                last_seen: list[str] = []
                while True:
                    items, ocr_done = cache.observe()
                    frame_stats[0] += int(ocr_done)
                    frame_stats[1] += int(not ocr_done)
                    if items:  # 空帧不冲掉上一次有效结果，超时日志里仍能看到关键词
                        last_seen = [f'{x["text"]}({x["score"]})' for x in items]
                    alive, handled = handoff_battle(tag)
                    if not alive:
                        print("=== RESULT: False ===", flush=True)
                        return False
                    if handled:
                        started = time.monotonic()  # 战斗耗时不计入本轮等待超时
                        cache.invalidate()
                        continue
                    ok, why = check(items, texts, forbid, match)
                    if ok:
                        log(f"  ✓ {tag} 画面满足：{why}")
                        break
                    if time.monotonic() - started >= timeout:
                        if total is None:
                            # 一直循环只认手动停止：本轮没等到就重置计时继续等，不判失败
                            log(f"  … {tag} 本轮未满足：{why}；继续等待")
                            started = time.monotonic()
                            device.sleep(poll)
                            continue
                        log(f"  ✗ {tag} 超时未满足：{why}；最后 OCR: "
                            f"{' / '.join(last_seen[:6]) or '（一直未识别到文字）'}")
                        print("=== RESULT: False ===", flush=True)
                        return False
                    device.sleep(poll)  # ensure_time 随机轮询间隔
            else:
                log(f"  {tag} 跳过文字复核，直接点击")
                device.screenshot()
                alive, handled = handoff_battle(tag)
                if not alive:
                    print("=== RESULT: False ===", flush=True)
                    return False
                if handled:
                    cache.invalidate()
                    continue

            if not scroll_mode:
                device.sleep(before)
                x, y = random_rectangle_point(rect)  # 矩形内正态随机落点，偏中心
                log(f"  {tag} 拟人点击 ({x}, {y})")
                # control_check=False：自研循环点同名太多次会被引擎 GameTooManyClickError 误杀。
                # 点击本身仍走 control_method（默认 minitouch，自带随机压力/时长/微移）。
                device.click(x, y, control_check=False, control_name="CUSTOM_CLICK")
            random_sleep(probability=0.05)  # 引擎概率防封长休眠
            device.sleep(after)
            if cache is not None:
                cache.invalidate()  # 点击/滚动会改变画面，下一轮必须重新识别
            maybe_idle(device, idle, f"{tag} 后", idle_stats)

            if total is not None and rounds >= total:
                break
            if rep["gap"] > 0:
                # 轮间隔同样走引擎正态随机，避免固定节拍
                device.sleep((round(rep["gap"] * 0.8, 3), round(rep["gap"] * 1.2, 3)))

        jump = as_jump(st.get("jump"), len(steps))
        if jump:
            log(f"  ↩ 第 {i} 层结束，跳转到第 {jump} 层")
            index = jump - 1
        else:
            index += 1

    log(f"画面判定：OCR {frame_stats[0]} 次 · 静止复用 {frame_stats[1]} 次"
        + (f" · 随机发呆 {idle_stats[0]} 次" if idle_stats[0] else ""))
    log("全部层级执行完毕")
    print("=== RESULT: True ===", flush=True)
    return True


def capture(config_name: str, out: Path) -> None:
    import cv2

    device = build_device(config_name)  # 截图不需要预热 OCR 模型
    image = device.screenshot()
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
    log(f"画面已保存 {out}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--plan-file")
    parser.add_argument("--capture")
    parser.add_argument("--parent-pid", type=int, default=0)
    args = parser.parse_args()

    if args.parent_pid:
        from gui.proc_guard import watch_parent

        watch_parent(args.parent_pid, interval=3.0)

    quiet_engine_logs()  # 抑制引擎每帧 OCR 的 INFO，保留 WARNING/ERROR

    try:
        if args.capture:
            capture(args.config, Path(args.capture))
            return 0
        if not args.plan_file:
            print("=== RESULT: False (缺少 --plan-file) ===", flush=True)
            return 2
        plan = json.loads(Path(args.plan_file).read_text(encoding="utf-8"))
        print(f"=== RUN custom_click on config {args.config} ===", flush=True)
        ok = run_plan(args.config, plan)
        return 0 if ok else 2
    except SystemExit as exc:
        ok = exc.code is None or exc.code == 0
        print(f"=== RESULT: {ok} (SystemExit {exc.code}) ===", flush=True)
        return 0 if ok else 2
    except BaseException as exc:  # noqa: BLE001 - 任何异常都要转成可读结果
        import traceback

        traceback.print_exc()
        print(f"=== RESULT: False ({type(exc).__name__}: {exc}) ===", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
