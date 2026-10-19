# -*- coding: utf-8 -*-
"""CSI 300 工作台守护进程（watchdog）。

解决的问题：之前只有"登录自启动"这一个时点 —— 电脑没重启（只关了 WorkBuddy）、
或服务在运行中意外退出时，没有任何机制把它拉回来。

本进程由登录自启动(autostart.bat)以 pythonw 隐藏拉起，然后：
  · 每 30 秒检查一次 127.0.0.1:8310
  · 一旦发现没在监听，立刻用 pythonw 重新拉起 main.py（子进程完全脱钩）
  · 自身用 127.0.0.1:8311 做单实例锁，重复启动会自动退出

日志：data/watchdog.log
"""
import datetime
import os
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8310
LOCK_PORT = 8311
LOG = os.path.join(ROOT, "data", "watchdog.log")
PYW = os.path.join(ROOT, ".venv", "Scripts", "pythonw.exe")
MAIN = os.path.join(ROOT, "main.py")
INTERVAL = 30

# DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
FLAGS = 0x00000008 | 0x00000200 | 0x08000000


def log(msg: str) -> None:
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        # 日志超过 2MB 先归档，避免无限增长
        if os.path.exists(LOG) and os.path.getsize(LOG) > 2 * 1024 * 1024:
            try:
                os.replace(LOG, LOG + ".old")
            except OSError:
                pass
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except OSError:
        pass


def is_up(port: int = PORT) -> bool:
    s = socket.socket()
    s.settimeout(1.5)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def start_server() -> None:
    exe = PYW if os.path.exists(PYW) else sys.executable
    try:
        subprocess.Popen(
            [exe, MAIN], cwd=ROOT, close_fds=True, creationflags=FLAGS,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log(f"服务未监听 → 已拉起 ({os.path.basename(exe)} main.py)")
    except Exception as e:                                      # noqa: BLE001
        log(f"拉起失败: {type(e).__name__}: {e}")


def acquire_lock() -> socket.socket | None:
    """用 LOCK_PORT 做单实例锁；已被占用说明已有守护进程在跑。"""
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
        return s
    except OSError:
        s.close()
        return None


def main() -> None:
    lock = acquire_lock()
    if lock is None:
        log("已有守护进程在运行，本实例退出")
        return
    log(f"守护进程启动 pid={os.getpid()}，间隔 {INTERVAL}s，监控 127.0.0.1:{PORT}")
    while True:
        try:
            if not is_up():
                start_server()
                for _ in range(30):          # 最多等 30 秒
                    time.sleep(1)
                    if is_up():
                        break
                log("服务已恢复" if is_up() else "拉起后仍未监听，下一轮重试")
        except Exception as e:                                  # noqa: BLE001
            log(f"巡检异常: {type(e).__name__}: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
