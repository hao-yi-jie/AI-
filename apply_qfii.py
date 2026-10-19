# -*- coding: utf-8 -*-
"""应用 QFII 名单：离线重匹配 + banner 预览 + 名录核验报告。"""
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r"C:\Users\RKBL\WorkBuddy\股票看板工作台\csi300_workbench")

import db
from services import holders

conn = db.get_conn()
db.init_db()

stat = holders.rematch(conn)
print("重匹配:", stat)

seed = holders.load_shareholder_seed()
alias_map = {s["group"]: s.get("aliases", []) for s in seed["shareholders"]}

rows = conn.execute("""
  SELECT holder_group g, holder_category c, stock_code s, change_type t,
         SUM(COALESCE(est_amount,0)) amt
  FROM stock_holder_changes GROUP BY holder_group, holder_category, stock_code, change_type
""").fetchall()
agg = {}
for r in rows:
    a = agg.setdefault(r["g"], {"c": r["c"], "st": set(), "inc": set(), "amt": 0.0})
    a["st"].add(r["s"])
    if r["t"] in holders.ADD_ACTIONS and (r["amt"] or 0) >= holders.MIN_INCREASE_AMOUNT:
        a["inc"].add(r["s"])
        a["amt"] += r["amt"] or 0

print(f"\n===== 左侧 banner（{len(agg)} 组，全部有持仓）=====")
no_qfii = []
for g, v in sorted(agg.items(), key=lambda kv: (holders.category_rank(kv[1]["c"]), -len(kv[1]["st"]))):
    ref = holders.qfii_lookup(g, alias_map.get(g))
    mark = "✓" if ref else "通道"
    if not ref:
        no_qfii.append(g)
    ex = f"  ← {ref['cn']} | {ref['en']}" if ref else "  ← 非 QFII 名录主体"
    print(f"  [{mark}] {v['c']:<9} {g:<26} 覆盖{len(v['st']):>3} 加仓{len(v['inc']):>3} "
          f"{round(v['amt'],1):>8.1f}亿{ex}")

print("\n===== 名录外分组 =====")
for g in no_qfii:
    print("  ", g)
conn.close()
