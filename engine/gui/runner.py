# -*- coding: utf-8 -*-
"""单任务执行器：由桥接服务以子进程方式拉起。

用法（cwd 为仓库根目录）：
    python -X utf8 -B gui/runner.py --config oas1 --task EvoZone

输出约定（供 bridge 解析）：
    === RUN <task> on config <config> ===
    ...
    === RESULT: True|False ===
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
    目录名（EvoZone / OtherWorldTwilight / LBS …），而配置键是 evo_zone /
    other_world_twilight / lbs。这里按「忽略大小写与下划线」做一次映射。
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
    parser.add_argument("--force-fight", action="store_true",
                        help="绕过『今日已挑战』判定（仅 AreaBoss 使用）")
    args = parser.parse_args()
    task = resolve_task(args.task)

    from module.image.rpc import ensure_image_server_ready, shutdown_image_server
    from module.ocr import rpc as ocr_rpc

    # 上游新版接口改名为 ensure_ocr_server_started，保留对旧名的兼容
    _ensure_ocr_server = getattr(ocr_rpc, "ensure_ocr_server_ready", None) or getattr(
        ocr_rpc, "ensure_ocr_server_started", None
    )
    shutdown_ocr_server = ocr_rpc.shutdown_ocr_server

    ensure_image_server_ready()
    if _ensure_ocr_server is not None:
        _ensure_ocr_server()

    if args.force_fight:
        import module.base.utils as base_utils
        _orig_load_module = base_utils.load_module

        def patched_load_module(module_name, module_file):
            module = _orig_load_module(module_name, module_file)
            task_cls = getattr(module, "ScriptTask", None)
            if task_cls is not None and hasattr(task_cls, "is_group_ranked"):
                task_cls.is_group_ranked = lambda self: False
                print("=== FORCE-FIGHT enabled ===", flush=True)
            return module

        base_utils.load_module = patched_load_module
        import script as script_module
        script_module.load_module = patched_load_module

    try:
        from script import Script
        script = Script(args.config)
        print(f"=== RUN {task} on config {args.config} (key: {args.task}) ===", flush=True)
        result = script.run(task)
        print(f"=== RESULT: {result} ===", flush=True)
        return 0 if result else 2
    except SystemExit as exc:
        # 引擎对致命异常会直接 exit(1)（见 Script._handle_task_exception），
        # 这种退出必须判为失败；只有 code 为 None/0 才是正常的 TaskEnd。
        code = exc.code
        ok = code is None or code == 0
        print(f"=== RESULT: {ok} (SystemExit {code}) ===", flush=True)
        return 0 if ok else (code if isinstance(code, int) else 2)
    except BaseException as exc:  # noqa: BLE001 - 需要把任何异常转成可读结果
        print(f"=== RESULT: False ({type(exc).__name__}: {exc}) ===", flush=True)
        return 2
    finally:
        try:
            shutdown_image_server()
            shutdown_ocr_server()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    raise SystemExit(main())
