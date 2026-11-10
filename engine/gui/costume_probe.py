# -*- coding: utf-8 -*-
"""庭院皮肤识别探针：由桥接服务以子进程方式拉起，供「刷新识别」按钮使用。

用法（cwd 为引擎根目录）：
    python -X utf8 -B gui/costume_probe.py --config oas1 [--force]

输出约定：标准输出最后一行是 JSON，便于 bridge 直接解析：
    {"ok": true, "detected": "costume_main_13", "label": "costume_main_13 (云景阆苑)",
     "score": 0.853, "configured": "costume_main", "changed": true, "checked_at": 1762...}

设计：与 runner 走同一套 Script/Device，保证与真正执行任务时的截图口径完全一致；
识别结果写进 config/gui_costume_state.json，任务启动时命中缓存就不再重复识别。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--force", action="store_true", help="忽略缓存，强制重新识别")
    args = parser.parse_args()

    result = {"ok": False, "error": ""}
    try:
        from script import Script
        from gui import costume_autodetect as detector

        script = Script(args.config)
        config = script.config
        configured = detector._value(config.model.global_game.costume_config.costume_main_type)
        changed = detector.autofix(script, force=args.force)
        state = detector.read_state(config.config_name) or {}
        result = {
            "ok": bool(state.get("skin")),
            "detected": state.get("skin") or "",
            "label": state.get("label") or "",
            "score": state.get("score"),
            "configured": detector._value(config.model.global_game.costume_config.costume_main_type),
            "previous": configured,
            "changed": bool(changed),
            "checked_at": state.get("checked_at"),
            "serial": state.get("serial") or "",
        }
        if not result["ok"]:
            result["error"] = "当前画面无法识别庭院（可能不在庭院，或在加载/战斗中）"
    except BaseException as exc:  # noqa: BLE001 - 必须把异常转成 JSON 给前端
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
