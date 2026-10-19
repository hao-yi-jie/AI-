# -*- coding: utf-8 -*-
"""排查：每个重要股东分组实际匹配到的原始股东名。"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r'C:\Users\RKBL\WorkBuddy\股票看板工作台\csi300_workbench')
import db

conn = db.get_conn()
rows = conn.execute("""
    SELECT holder_group, holder_category, holder_raw, COUNT(DISTINCT stock_code) s,
           SUM(CASE WHEN change_type='增持' THEN 1 ELSE 0 END) inc
    FROM stock_holder_changes
    GROUP BY holder_group, holder_raw
    ORDER BY holder_group, s DESC""").fetchall()

cur = None
for r in rows:
    if r['holder_group'] != cur:
        cur = r['holder_group']
        print(f"\n### {cur}  [{r['holder_category']}]")
    print(f"   覆盖{r['s']:>3}只 增持{r['inc']:>2} | {r['holder_raw']}")
conn.close()
