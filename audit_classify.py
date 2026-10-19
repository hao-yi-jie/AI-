# -*- coding: utf-8 -*-
"""审计各分类节点成员，暴露宽泛 L2 规则导致的误归类。"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r'C:\Users\RKBL\WorkBuddy\股票看板工作台\csi300_workbench')
import db

conn = db.get_conn()
rows = conn.execute("""
    SELECT g.name g, s.name n, st.stock_code, st.stock_name,
           st.sw_l1, st.sw_l2, st.sw_l3
    FROM stock_industries si
    JOIN industries s ON s.id = si.industry_id
    JOIN industries g ON g.id = s.parent_id
    JOIN stocks st ON st.stock_code = si.stock_code
    WHERE g.name IS NOT NULL
    ORDER BY g.sort_order, s.name, st.stock_code""").fetchall()

cur = None
for r in rows:
    key = f"{r['g']} / {r['n']}"
    if key != cur:
        cur = key
        print(f"\n### {key}")
    lv = "·".join(x for x in (r['sw_l2'], r['sw_l3']) if x)
    print(f"   {r['stock_name']}({r['stock_code']})  [{r['sw_l1']} / {lv}]")
conn.close()
