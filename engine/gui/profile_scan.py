"""绑定账号时从当前游戏画面里认出「这是谁」：昵称 + 头像。

画面固定 1280x720，角色信息固定在左上角（等级圆牌 + 圆形头像 + 昵称条），
所以这里直接按坐标取，不做全屏查找：更快，也不会误认到别的文字上。

两种用法：
    python profile_scan.py --config oas1 --out-avatar a.png
        跑一次，输出一行 JSON 就退出（bridge 的兜底路径）。
    python profile_scan.py --serve
        常驻模式：引擎/OCR 模型只加载一次，之后每行一条请求、每行一条结果。
        冷启动要 7 秒左右（导入引擎 + 载模型），常驻后每次只要 1 秒左右。

请求：{"config": "oas1", "out_avatar": "a.png"}
输出：{"ok": true, "nickname": "溪木镇的鸡", "avatar": "oas1.png", "texts": [...]}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from gui.custom_click_runner import build_device, build_ocr, ocr_texts

SCREEN = (1280, 720)
# 昵称文字所在位置（左上角信息条里，头像右侧那一行）；x2/y2 为右下角
NAME_ROI = (126, 20, 246, 56)
# 圆形头像：画面固定 1280x720，圆框就在这个位置，直接按坐标裁（美术换皮不影响位置）
AVATAR_BOX = (14, 22, 100, 108)
AVATAR_SIZE = 96       # 存下来的头像边长，够 28px 的图标用还能放大看
OCR_SCORE = 0.3

# 常驻模式下缓存起来，避免每次重新初始化（导入 + 载模型是大头）
_DEVICES: dict = {}
_ENGINE_OCR = None


def pick_nickname(items: list[dict]) -> str:
    """从 OCR 结果里挑昵称：要含汉字、长度 2~12，优先分数高的。"""
    best = ""
    best_score = -1.0
    for item in items:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        # 昵称里一定有汉字；等级、时间这类纯数字/符号直接丢
        if not any("\u4e00" <= ch <= "\u9fff" for ch in text):
            continue
        text = "".join(text.split())
        if not 2 <= len(text) <= 12:
            continue
        score = float(item.get("score") or 0)
        if score > best_score:
            best, best_score = text, score
    return best


def crop_avatar(image: np.ndarray) -> np.ndarray:
    """裁出圆形头像，圆外做成透明，避免带上背后的场景。"""
    x1, y1, x2, y2 = AVATAR_BOX
    x2 = min(x2, image.shape[1])
    y2 = min(y2, image.shape[0])
    crop = image[max(0, y1):y2, max(0, x1):x2]
    if crop.size == 0:
        return np.zeros((AVATAR_SIZE, AVATAR_SIZE, 4), np.uint8)

    crop = cv2.resize(crop, (AVATAR_SIZE, AVATAR_SIZE), interpolation=cv2.INTER_AREA)
    # 4 倍超采样画圆再缩小，边缘不会有锯齿
    mask = np.zeros((AVATAR_SIZE * 4, AVATAR_SIZE * 4), np.uint8)
    cv2.circle(mask, (AVATAR_SIZE * 2, AVATAR_SIZE * 2), AVATAR_SIZE * 2 - 4, 255, -1)
    mask = cv2.resize(mask, (AVATAR_SIZE, AVATAR_SIZE), interpolation=cv2.INTER_AREA)

    bgra = cv2.cvtColor(crop, cv2.COLOR_RGB2BGRA)
    bgra[:, :, 3] = mask
    return bgra


def get_device(config_name: str):
    """同一实例复用同一个 Device；掉线了才重建。"""
    device = _DEVICES.get(config_name)
    if device is not None:
        try:
            if device.adb.device_online:
                return device
        except Exception:  # noqa: BLE001 - 状态取不到就当掉线，重建
            pass
        _DEVICES.pop(config_name, None)
    device = build_device(config_name)
    _DEVICES[config_name] = device
    return device


def get_ocr():
    global _ENGINE_OCR
    if _ENGINE_OCR is None:
        _ENGINE_OCR = build_ocr(NAME_ROI, OCR_SCORE)
    return _ENGINE_OCR


def _orientations(image):
    """把截图统一成 1280x720：竖屏帧转 90°，奇怪尺寸按比例塞进去补边。"""
    h, w = image.shape[:2]
    if (w, h) == SCREEN:
        yield "as-is", image
        return
    if (h, w) == SCREEN:
        yield "rot90", cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        yield "rot270", cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return
    scale = min(SCREEN[0] / w, SCREEN[1] / h)
    resized = cv2.resize(image, (max(1, int(w * scale)), max(1, int(h * scale))),
                         interpolation=cv2.INTER_AREA)
    channels = 3 if resized.ndim == 2 else resized.shape[2]
    canvas = np.zeros((SCREEN[1], SCREEN[0], channels), np.uint8)
    top = (SCREEN[1] - resized.shape[0]) // 2
    left = (SCREEN[0] - resized.shape[1]) // 2
    canvas[top:top + resized.shape[0], left:left + resized.shape[1]] = resized
    yield "letterbox", canvas


def scan(config_name: str, out_avatar: str) -> dict:
    """抓一帧、认昵称、裁头像，返回结果 dict（不打印）。"""
    try:
        device = get_device(config_name)
        image = device.screenshot()
    except Exception as exc:  # noqa: BLE001
        _DEVICES.pop(config_name, None)
        # 引擎抛的异常经常没有 message，这里退到异常类型名，别让界面显示成空字符串
        reason = str(exc).strip() or type(exc).__name__
        return {"ok": False, "error": f"连不上模拟器或截图失败（{reason}）"}

    if image is None or not getattr(image, "size", 0):
        return {"ok": False, "error": "截图失败：没有拿到画面"}

    shot = {"w": int(image.shape[1]), "h": int(image.shape[0])}
    # 有的机器 screencap 给的是竖屏帧（720x1280），硬拉成 1280x720 会把名字条压扁，
    # 这里改为旋转后重试，取能认出昵称的那个方向。
    best = None
    for name, frame in _orientations(image):
        try:
            texts = ocr_texts(device, get_ocr(), NAME_ROI, image=frame)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"识别失败：{exc}"}
        nickname = pick_nickname(texts)
        if best is None:
            best = {"orientation": name, "frame": frame, "texts": texts, "nickname": nickname}
        if nickname:
            best = {"orientation": name, "frame": frame, "texts": texts, "nickname": nickname}
            break

    image = best["frame"]
    texts = best["texts"]
    nickname = best["nickname"]
    shot["orientation"] = best["orientation"]

    avatar_path = Path(out_avatar)
    avatar_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        cv2.imwrite(str(avatar_path), crop_avatar(image))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"头像保存失败：{exc}"}

    result = {
        "ok": bool(nickname),
        "nickname": nickname,
        "avatar": avatar_path.name,
        "shot": shot,
        "texts": [{"text": t.get("text"), "score": round(float(t.get("score") or 0), 3)}
                  for t in texts],
    }
    if not nickname:
        result["error"] = f"没认出昵称（画面 {shot['w']}x{shot['h']}，已按 {shot['orientation']} 处理）"
    return result


def serve() -> int:
    """常驻：每行一条 JSON 请求，回一行 JSON。引擎与模型只初始化一次。"""
    # 先把重的东西加载好，第一条请求就不用等了
    get_ocr()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if str(req.get("cmd") or "") == "exit":
            break
        if str(req.get("cmd") or "") == "warm":
            # 预热：把 Device 建好并抓一帧，后续第一次识别就不用等这几秒
            config_name = str(req.get("config") or "")
            try:
                if config_name:
                    get_device(config_name).screenshot()
                result = {"ok": True, "warm": True, "config": config_name}
            except Exception as exc:  # noqa: BLE001 - 预热失败无所谓，识别时还会重建
                _DEVICES.pop(config_name, None)
                result = {"ok": False, "warm": True, "error": str(exc)}
            sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            continue
        config_name = str(req.get("config") or "")
        out_avatar = str(req.get("out_avatar") or "")
        if not config_name or not out_avatar:
            result = {"ok": False, "error": "缺少 config 或 out_avatar"}
        else:
            try:
                result = scan(config_name, out_avatar)
            except Exception as exc:  # noqa: BLE001 - 单次失败不能拖垮常驻进程
                result = {"ok": False, "error": f"识别失败：{exc}"}
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="实例名（config/<name>.json）")
    parser.add_argument("--out-avatar", help="头像 PNG 输出路径")
    parser.add_argument("--serve", action="store_true", help="常驻模式，一行一请求")
    args = parser.parse_args()

    if args.serve:
        return serve()

    if not args.config or not args.out_avatar:
        print(json.dumps({"ok": False, "error": "缺少 --config 或 --out-avatar"}, ensure_ascii=False))
        return 2

    result = scan(args.config, args.out_avatar)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
