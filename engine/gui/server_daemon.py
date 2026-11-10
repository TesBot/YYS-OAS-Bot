# -*- coding: utf-8 -*-
"""常驻图像/OCR 服务守护进程。

为什么需要它：
    gui/runner.py 以子进程方式执行每个编排步骤，结束时会把图像服务和
    OCR 服务一并杀掉；下一个步骤又要重新启动（OCR 模型预热约 6 秒、
    图像服务约 1.5 秒），这就是「点运行到任务真正开始」「任务与任务
    之间」等待很久的主要来源。

工作方式：
    由 bridge 在启动时以分离进程方式拉起本守护进程。守护进程确保两个
    服务在线并保持存活（进程崩溃后 10 秒内自动重启）；runner 的
    ensure_*_ready() 发现端口已被监听时直接复用，不再自己拉起，
    也不再在退出时杀服务（它不是服务的父进程，shutdown 是空操作）。

    若 deploy 配置关闭了 StartImageServer / StartOcrServer，这里
    对应的 ensure 会直接返回，行为与单跑 runner 完全一致。

    bridge 退出时通过 PID 文件 taskkill 整个进程树；异常退出留下的
    残留会在 bridge 下次启动时被清理。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from module.logger import logger
    from module.image.rpc import ensure_image_server_started
    from module.ocr.rpc import ensure_ocr_server_started

    logger.info("Server daemon: starting image/ocr services")
    ensure_image_server_started()
    ensure_ocr_server_started()
    logger.info("Server daemon: services ready")
    print("SERVER_DAEMON_READY", flush=True)

    # 保持存活并自愈：服务进程意外退出时重新拉起。
    while True:
        time.sleep(10)
        try:
            ensure_image_server_started()
            ensure_ocr_server_started()
        except Exception:  # noqa: BLE001 - 守护进程不能因为一次失败退出
            pass


if __name__ == "__main__":
    raise SystemExit(main())
