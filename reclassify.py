# -*- coding: utf-8 -*-
"""重新应用分类规则（全量重建 stock_industries），打印结果分布。"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r"C:/Users/RKBL/WorkBuddy/股票看板工作台/csi300_workbench")
import db
from providers.ftshare_provider import FTShareProvider
from services import classifier

conn = db.get_conn()
p = FTShareProvider()
result = classifier.classify_stocks(p, conn)
print("classify:", result)

rows = conn.execute("""
    SELECT COALESCE(g.name,'-') g, s.name n, COUNT(*) c FROM stock_industries si
    JOIN industries s ON s.id=si.industry_id
    LEFT JOIN industries g ON g.id=s.parent_id
    GROUP BY g.name, s.name HAVING g.name IS NOT NULL
    ORDER BY g.name, c DESC""").fetchall()
for r in rows:
    print(f"{r['g']:<8} / {r['n']:<8}: {r['c']}")
print("---- 仍待归类 ----")
left = conn.execute("""
    SELECT s.stock_code, s.stock_name, s.sw_l1, s.sw_l2 FROM stocks s
    WHERE s.in_csi300=1 AND s.stock_code IN (
      SELECT si.stock_code FROM stock_industries si
      JOIN industries i ON i.id=si.industry_id AND i.name='待归类')""").fetchall()
print(len(left), "只:", [f"{r['stock_name']}({r['sw_l1']}/{r['sw_l2']})" for r in left][:20])
conn.close()
