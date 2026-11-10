# -*- coding: utf-8 -*-
"""单任务执行器：由桥接服务以子进程方式拉起。

用法（cwd 为引擎根目录）：
    python -X utf8 -B gui/runner.py --config oas1 --task EvoZone

输出约定（供 bridge 解析）：
    === RUN <task> on config <config> ===
    ...
    === RESULT: True|False ===

说明：引擎已与上游 OnmyojiAutoScript 对齐，图像/OCR 服务由引擎自身
（script.py → module.ocr.rpc.ensure_ocr_server_started）负责，壳子层
不再注入任何自研服务或个人补丁，只做「解析任务名 → 调 Script.run」的薄封装。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def resolve_task(name: str) -> str:
    """把配置里的 snake_case 任务键解析成真实任务目录名。

    引擎内部用 ``tasks/<command>/script_task.py`` 拼路径，所以 command 必须是
    目录名（EvoZone / OtherWorldTwilight …），而配置键是 evo_zone /
    other_world_twilight。这里按「忽略大小写与下划线」做一次映射。
    """
    target = name.replace("_", "").replace("-", "").lower()
    tasks_dir = ROOT / "tasks"
    if tasks_dir.is_dir():
        for path in tasks_dir.iterdir():
            if path.is_dir() and path.name.replace("_", "").lower() == target:
                return path.name
    return name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument(
        "--force-fight",
        action="store_true",
        help="兼容旧版控制台传参。引擎已回归上游行为，此参数不再改变执行逻辑。",
    )
    args = parser.parse_args()
    task = resolve_task(args.task)

    if args.force_fight:
        print("=== NOTE: --force-fight 已废弃（引擎回归上游），忽略 ===", flush=True)

    try:
        from script import Script

        script = Script(args.config)
        print(f"=== RUN {task} on config {args.config} (key: {args.task}) ===", flush=True)
        result = script.run(task)
        print(f"=== RESULT: {result} ===", flush=True)
        return 0 if result else 2
    except SystemExit as exc:
        # 引擎对致命异常会直接 exit(1)（见 Script.run 的异常分支），
        # 这种退出必须判为失败；只有 code 为 None/0 才是正常的 TaskEnd。
        code = exc.code
        ok = code is None or code == 0
        print(f"=== RESULT: {ok} (SystemExit {code}) ===", flush=True)
        return 0 if ok else (code if isinstance(code, int) else 2)
    except BaseException as exc:  # noqa: BLE001 - 需要把任何异常转成可读结果
        print(f"=== RESULT: False ({type(exc).__name__}: {exc}) ===", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
