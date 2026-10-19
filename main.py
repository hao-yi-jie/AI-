# -*- coding: utf-8 -*-
"""CSI 300 Industry Intelligence Workbench 启动入口。

用法:
    python main.py
然后浏览器打开 http://127.0.0.1:8310

说明:
- 无论从哪里启动（任务计划/自启动/手动），都会先切换到本文件所在目录，
  保证 api 模块导入与 data/workbench.db 路径正确。
- 日志同时输出到控制台与 data/workbench.log（>10MB 自动轮转为 .old），
  便于无窗口启动时排查。
- 单实例保护：若 8310 端口已有本工作台在运行，直接退出，
  因此多个自启动入口（快捷方式+脚本）同时存在也不会冲突。
"""
import logging
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from config import HOST, PORT, DATA_DIR

LOG_FILE = DATA_DIR / "workbench.log"
DATA_DIR.mkdir(exist_ok=True)

# 简单日志轮转：超过 10MB 归档为 .old
if LOG_FILE.exists() and LOG_FILE.stat().st_size > 10 * 1024 * 1024:
    try:
        Path(str(LOG_FILE) + ".old").unlink(missing_ok=True)
        LOG_FILE.rename(Path(str(LOG_FILE) + ".old"))
    except OSError:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("workbench")


def _already_running() -> bool:
    """8310 端口已有服务在监听则视为已运行（单实例保护）。"""
    s = socket.socket()
    s.settimeout(0.5)
    try:
        s.connect((HOST, PORT))
        return True
    except OSError:
        return False
    finally:
        s.close()


# log_config=None：让 uvicorn 沿用上面的根日志配置（含文件输出）
uvicorn_config = {
    "app": "api:app",
    "host": HOST,
    "port": PORT,
    "log_level": "info",
    "log_config": None,
}

if __name__ == "__main__":
    if _already_running():
        log.info(f"Port {PORT} already in use by the workbench — exit (单实例保护).")
        sys.exit(0)
    log.info(f"Starting CSI 300 Industry Intelligence Workbench → http://{HOST}:{PORT}")
    log.info(f"Log file: {LOG_FILE}")
    import uvicorn
    uvicorn.run(**uvicorn_config)
