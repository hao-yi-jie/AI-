# -*- coding: utf-8 -*-
"""开通 Cloudflare 资源：D1 数据库 + Pages 项目 + D1 绑定。幂等，可重复运行。"""
import os
import sys
import io
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import cf_api as cf

conf = cf.load_conf()
acc = conf["account_id"]
print("账号:", acc)

# ---------- 1) D1 ----------
print("\n=== D1 数据库 ===")
r = cf.api(f"/accounts/{acc}/d1/database", conf=conf)
dbs = r.get("result") or []
db = next((d for d in dbs if d.get("name") == conf["db_name"]), None)
if db:
    print("  已存在:", db["name"], db["uuid"])
else:
    r = cf.api(f"/accounts/{acc}/d1/database", "POST",
               {"name": conf["db_name"], "primary_location_hint": "apac"}, conf=conf)
    if not r.get("success"):
        print("  创建失败:", json.dumps(r, ensure_ascii=False)[:400]); sys.exit(1)
    db = r["result"]
    print("  已创建:", db["name"], db["uuid"])
conf["db_id"] = db["uuid"]
cf.save_conf(conf)

# ---------- 2) 建表 ----------
print("\n=== 应用表结构 ===")
sql_text = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "schema.sql"), encoding="utf-8").read()
# 先剔除整行注释，再按分号切分（否则以注释开头的语句会被整条跳过）
sql_clean = "\n".join(l for l in sql_text.splitlines() if not l.strip().startswith("--"))
stmts = [s.strip() for s in sql_clean.split(";") if s.strip()]
for s in stmts:
    one = " ".join(s.split())
    r = cf.d1_query(s, conf=conf)
    ok = r.get("success")
    print(f"  {'✓' if ok else '✗'} {one[:64]}")
    if not ok:
        print("     ", json.dumps(r, ensure_ascii=False)[:300])

r = cf.d1_query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name", conf=conf)
tables = [x["name"] for x in (r.get("result") or [{}])[0].get("results", [])]
print("  D1 现有表:", tables)

# ---------- 3) Pages 项目 ----------
print("\n=== Pages 项目 ===")
r = cf.api(f"/accounts/{acc}/pages/projects", conf=conf)
projs = r.get("result") or []
p = next((x for x in projs if x.get("name") == conf["project"]), None)
if p:
    print("  已存在:", p["name"], "|", p.get("subdomain"))
else:
    r = cf.api(f"/accounts/{acc}/pages/projects", "POST",
               {"name": conf["project"], "production_branch": "main"}, conf=conf)
    if not r.get("success"):
        print("  创建失败:", json.dumps(r, ensure_ascii=False)[:600]); sys.exit(1)
    p = r["result"]
    print("  已创建:", p["name"], "|", p.get("subdomain"))

# ---------- 4) D1 绑定 ----------
print("\n=== 绑定 D1 到 Pages ===")
r = cf.api(f"/accounts/{acc}/pages/projects/{conf['project']}", "PATCH",
           {"deployment_configs": {"production": {
               "d1_databases": {conf["binding"]: {"id": conf["db_id"]}}}}}, conf=conf)
if r.get("success"):
    dc = r["result"].get("deployment_configs", {}).get("production", {})
    print("  ✓ 绑定成功:", json.dumps(dc.get("d1_databases"), ensure_ascii=False))
else:
    print("  ✗ 绑定失败:", json.dumps(r, ensure_ascii=False)[:600])

r = cf.api(f"/accounts/{acc}/pages/projects/{conf['project']}", conf=conf)
res = r.get("result") or {}
print("\n项目信息:", res.get("name"), "| subdomain:", res.get("subdomain"),
      "| domains:", res.get("domains"))
print("D1:", conf["db_name"], conf["db_id"])
print("\n配置已保存 -> data/cloudflare.json")
