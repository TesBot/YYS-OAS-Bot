# -*- coding: utf-8 -*-
"""常驻 OCR 服务守护进程。

为什么需要它：
    gui/runner.py 以子进程方式执行每个编排步骤，进程退出时 OCR 服务可能
    一并结束；下一个步骤又要重新启动（OCR 模型预热约 6 秒），这就是
    「点运行到任务真正开始」「任务与任务之间」等待很久的主要来源。

工作方式：
    由 bridge 在启动时以分离进程方式拉起本守护进程。守护进程确保 OCR 服务
    在线并保持存活（进程崩溃后 10 秒内自动重启）；runner 侧的引擎脚本
    （script.py）调用 ensure_ocr_server_started() 时发现端口已被监听会直接复用。

    引擎已对齐上游：图像处理不再有独立的常驻服务（上游直接在同进程做
    模板匹配），因此这里只守护 OCR。

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
    from module.ocr.rpc import ensure_ocr_server_started

    logger.info("Server daemon: starting ocr service")
    ensure_ocr_server_started()
    logger.info("Server daemon: service ready")
    print("SERVER_DAEMON_READY", flush=True)

    # 保持存活并自愈：服务进程意外退出时重新拉起。
    while True:
        time.sleep(10)
        try:
            ensure_ocr_server_started()
        except Exception:  # noqa: BLE001 - 守护进程不能因为一次失败退出
            pass


if __name__ == "__main__":
    raise SystemExit(main())
