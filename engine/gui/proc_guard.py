# -*- coding: utf-8 -*-
"""进程守卫：让子进程跟着控制台一起退出，避免留下孤儿。

背景
----
控制台（Electron）退出时用 ``TerminateProcess`` 结束 ``gui/bridge.py``，
这条路**不会执行 Python 的 atexit**，所以 bridge 里注册的「退出时回收守护进程」
从来没生效过；而 ``server_daemon.py`` 里还挂着一个 multiprocessing 的 OCR 服务，
于是关掉控制台后任务管理器里还留着 python 进程，重装/卸载时提示「程序未关闭」。

两条保险：
1. 控制台侧用 ``taskkill /PID <bridge> /T /F`` 结束整棵进程树（见 console/main.js）。
2. 子进程侧各自盯着父进程，父进程没了就自杀（连自己的子树一起），
   这样哪怕 bridge 被崩溃/任务管理器强杀，也不会留下孤儿。
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time


def parent_alive(ppid: int) -> bool:
    """判断父进程是否还活着（Windows 用 OpenProcess+WaitForSingleObject）。"""
    if not ppid or ppid <= 0:
        return True
    if os.name == "nt":
        try:
            import ctypes

            synchronize = 0x00100000
            wait_timeout = 0x00000102
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(synchronize, False, int(ppid))
            if not handle:
                return False
            try:
                return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
            finally:
                kernel32.CloseHandle(handle)
        except Exception:  # noqa: BLE001 - 判定失败时宁可认为父进程活着
            return True
    try:
        os.kill(int(ppid), 0)
        return True
    except OSError:
        return False


def kill_self_tree() -> None:
    """把自己和整棵子树干掉（Windows 用 taskkill /T）。"""
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(os.getpid()), "/T", "/F"],
                           capture_output=True, timeout=15)
            return
        except Exception:  # noqa: BLE001
            pass
    os._exit(3)


def watch_parent(ppid: int, interval: float = 5.0, on_dead=None) -> threading.Thread:
    """后台盯着父进程，父进程消失后调用 on_dead（默认杀自己整棵树）。

    参数为 0 或负数时不启动，方便手工命令行运行调试。
    """

    def _loop() -> None:
        while True:
            time.sleep(interval)
            if parent_alive(ppid):
                continue
            try:
                print(f"[proc_guard] 父进程 {ppid} 已退出，回收自身进程树", flush=True)
            except Exception:  # noqa: BLE001
                pass
            if on_dead is not None:
                on_dead()
            else:
                kill_self_tree()
            return

    thread = threading.Thread(target=_loop, name="proc_guard", daemon=True)
    if ppid and ppid > 0:
        thread.start()
    return thread


def ppid_from_argv(argv: list[str]) -> int:
    """从 ``--parent-pid N`` 解析父进程号，缺省返回 0（不启用看门狗）。"""
    for index, item in enumerate(argv):
        if item == "--parent-pid" and index + 1 < len(argv):
            try:
                return int(argv[index + 1])
            except ValueError:
                return 0
        if item.startswith("--parent-pid="):
            try:
                return int(item.split("=", 1)[1])
            except ValueError:
                return 0
    return 0


if __name__ == "__main__":
    print("parent_alive:", parent_alive(os.getppid()))
    sys.exit(0)
