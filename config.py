# -*- coding: utf-8 -*-
"""全局配置"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
WEB_DIR = PROJECT_ROOT / "web"
SEED_DIR = PROJECT_ROOT / "seed"
DB_PATH = DATA_DIR / "workbench.db"

HOST = "127.0.0.1"
PORT = 8310

# 更新流程并发度（对 FTShare 的并行请求数）
MAX_WORKERS = 8
# 重要股东接口并发度（该接口限流较严，429 频繁，单独调低）
HOLDER_WORKERS = 4
# 单次 HTTP 请求重试次数
HTTP_RETRIES = 2
