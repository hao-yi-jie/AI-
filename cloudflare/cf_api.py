# -*- coding: utf-8 -*-
"""Cloudflare API 轻量封装（只用标准库，不依赖 wrangler / node）。

令牌与账号信息从环境变量或 data/cloudflare.json 读取，不写死在代码里。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

API = "https://api.cloudflare.com/client/v4"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = os.path.join(ROOT, "data", "cloudflare.json")

DEFAULTS = {
    "account_id": "cb62d8144380d6946d429755636352c3",
    "db_name": "rkstock-db",
    "project": "rkstock",
    "domain": "rkstock.pages.dev",
    "binding": "DB",
}


def load_conf() -> dict:
    conf = dict(DEFAULTS)
    if os.path.exists(CONF):
        with open(CONF, encoding="utf-8") as f:
            conf.update(json.load(f))
    if os.environ.get("CF_TOKEN"):
        conf["token"] = os.environ["CF_TOKEN"]
    if not conf.get("token"):
        raise SystemExit(
            "缺少 Cloudflare 令牌：请设置环境变量 CF_TOKEN，或写入 "
            f"{CONF}（键名 token）。")
    return conf


def save_conf(conf: dict) -> None:
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    with open(CONF, "w", encoding="utf-8") as f:
        json.dump(conf, f, ensure_ascii=False, indent=1)
    try:
        os.chmod(CONF, 0o600)
    except OSError:
        pass


def api(path: str, method: str = "GET", body=None, conf: dict | None = None,
        raw_body: bytes | None = None, content_type: str | None = None,
        retries: int = 3):
    conf = conf or load_conf()
    url = API + path
    data = raw_body if raw_body is not None else (
        json.dumps(body).encode() if body is not None else None)
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", "Bearer " + conf["token"])
        req.add_header("Content-Type", content_type or "application/json")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                txt = r.read().decode()
                return json.loads(txt) if txt.strip() else {"success": True}
        except urllib.error.HTTPError as e:
            txt = e.read().decode()
            try:
                return json.loads(txt)
            except Exception:
                return {"success": False, "http": e.code, "raw": txt[:500]}
        except Exception as e:                                   # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            time.sleep(1.5 * (attempt + 1))
    return {"success": False, "error": last}


def d1_query(sql: str, params=None, conf: dict | None = None,
             db_id: str | None = None) -> dict:
    conf = conf or load_conf()
    db_id = db_id or conf["db_id"]
    return api(f"/accounts/{conf['account_id']}/d1/database/{db_id}/query",
               "POST", {"sql": sql, "params": params or []}, conf=conf)


def d1_batch(statements: list, conf: dict | None = None) -> dict:
    """批量执行。注意：D1 REST 只接受 {"batch": [...]} 这种对象包一层，
    直接 POST 数组会报 7400 "Expected object, received array"。"""
    conf = conf or load_conf()
    return api(f"/accounts/{conf['account_id']}/d1/database/{conf['db_id']}/query",
               "POST", {"batch": statements}, conf=conf)
