# -*- coding: utf-8 -*-
"""Step 6 验证：跑一次完整更新流程，确认数据库中有真实数据。"""
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r"C:\Users\RKBL\WorkBuddy\股票看板工作台\csi300_workbench")

import db
db.init_db()
from services.updater import manager

assert manager.start(), "更新已在进行中"
last_snapshot = None
while manager.status()["running"]:
    time.sleep(3)
    snap = [(s["key"], s["status"]) for s in manager.status()["steps"]]
    if snap != last_snapshot:
        last_snapshot = snap
        print("...", snap, flush=True)

st = manager.status()
print("\n===== 更新结果 =====")
print("overall:", st["overall"])
for s in st["steps"]:
    mark = {"ok": "[OK]", "failed": "[FAIL]", "pending": "[ ..]", "running": "[...]"}.get(s["status"], "[?]")
    print(f"{mark} {s['label']}: {s['detail']}")
if st.get("error"):
    print("error:", st["error"])

conn = db.get_conn()
print("\n===== 数据库抽样 =====")
print("stocks:", conn.execute("SELECT COUNT(*) FROM stocks WHERE in_csi300=1").fetchone()[0])
print("metrics:", conn.execute("SELECT metric_name, COUNT(*) c FROM stock_metrics GROUP BY metric_name").fetchall())
print("industries:", conn.execute("SELECT COUNT(*) FROM industries").fetchone()[0])
print("stock_industries:", conn.execute("SELECT COUNT(*) FROM stock_industries").fetchone()[0])
row = conn.execute("""
    SELECT s.stock_code, s.stock_name,
        MAX(CASE WHEN m.metric_name='market_cap' THEN m.metric_value END) mc,
        MAX(CASE WHEN m.metric_name='pe_ttm' THEN m.metric_value END) pe,
        MAX(CASE WHEN m.metric_name='np_yoy' THEN m.metric_value END) yoy,
        MAX(CASE WHEN m.metric_name='np_yoy' THEN m.report_period END) rp,
        MAX(CASE WHEN m.metric_name='ytd' THEN m.metric_value END) ytd
    FROM stocks s LEFT JOIN stock_metrics m ON m.stock_code=s.stock_code
    WHERE s.stock_code IN ('600519','300760','603501','000001')
    GROUP BY s.stock_code""").fetchall()
for r in row:
    print(dict(r))
conn.close()
