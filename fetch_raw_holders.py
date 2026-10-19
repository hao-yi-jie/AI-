# -*- coding: utf-8 -*-
"""抓取全部样本股票的十大流通股东原始数据（开发/补数用）。

更新流程（点「更新数据」）里已包含同一步骤；此脚本用于单独重跑或排查。
失败清单写入 data/raw_holder_failures.txt，可用 Wind 补齐。
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r"C:\Users\RKBL\WorkBuddy\股票看板工作台\csi300_workbench")

import db
from providers.ftshare_provider import FTShareProvider
from services import holders

conn = db.get_conn()
db.init_db()
stocks = [dict(r) for r in conn.execute(
    "SELECT stock_code AS code, ts_code, stock_name FROM stocks"
    " WHERE in_csi300=1 ORDER BY stock_code")]
print("样本股票:", len(stocks))

errors = []
raw = holders.fetch_raw_holders(FTShareProvider(), stocks, errors=errors)

failed = {c for c, _ in errors}
if failed:
    ok = [s["code"] for s in stocks if s["code"] not in failed]
    if ok:
        marks = ",".join("?" * len(ok))
        conn.execute(f"DELETE FROM stock_float_holders_raw WHERE stock_code IN ({marks})", ok)
else:
    conn.execute("DELETE FROM stock_float_holders_raw")
conn.executemany(
    """INSERT INTO stock_float_holders_raw
       (stock_code, report_date, rank, holder_raw, change_type,
        change_shares, shareholding, share_ratio, fetched_at)
       VALUES (?,?,?,?,?,?,?,?,?)""", raw)
conn.commit()

stat = holders.rematch(conn)
n_stocks = conn.execute(
    "SELECT COUNT(DISTINCT stock_code) c FROM stock_float_holders_raw").fetchone()["c"]
n_names = conn.execute(
    "SELECT COUNT(DISTINCT holder_raw) c FROM stock_float_holders_raw").fetchone()["c"]
print(f"原始入库 {len(raw)} 条 | 覆盖 {n_stocks} 只 | 不同股东名 {n_names} 个")
print(f"匹配结果: {stat}")
print(f"抓取失败 {len(errors)} 只")
for c, e in errors[:20]:
    print("   ", c, e)
if errors:
    with open("data/raw_holder_failures.txt", "w", encoding="utf-8") as fh:
        for c, e in errors:
            fh.write(f"{c}\t{e}\n")
    print("失败清单 -> data/raw_holder_failures.txt")
conn.close()
