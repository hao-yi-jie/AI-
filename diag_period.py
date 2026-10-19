# -*- coding: utf-8 -*-
"""诊断：当前财务报告期口径 vs 数据源现在能拿到什么。"""
import sqlite3
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
DB = r"C:\Users\RKBL\WorkBuddy\股票看板工作台\csi300_workbench\data\workbench.db"
c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row

print("=== 1. 每只股票「最新」np_yoy 落在哪个报告期（A 页实际显示）===")
sql = """
WITH r AS (
  SELECT stock_code, report_period, data_date,
         ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY data_date DESC, id DESC) rn
  FROM stock_metrics WHERE metric_name='np_yoy')
SELECT report_period, COUNT(*) n, MIN(data_date) mn, MAX(data_date) mx
FROM r WHERE rn=1 GROUP BY report_period ORDER BY n DESC"""
for x in c.execute(sql):
    print("   ", dict(x))

print("\n=== 2. np_momentum（业绩变化）分布 ===")
for x in c.execute("SELECT report_period, COUNT(*) n FROM stock_metrics"
                   " WHERE metric_name='np_momentum' GROUP BY report_period"):
    print("   ", dict(x))

print("\n=== 3. 样例（A 页会显示什么）===")
for x in c.execute("""
WITH r AS (SELECT stock_code, report_period, data_date, metric_value,
   ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY data_date DESC, id DESC) rn
   FROM stock_metrics WHERE metric_name='np_yoy')
SELECT s.stock_code, s.stock_name, r.report_period, r.data_date, r.metric_value
FROM r JOIN stocks s ON s.stock_code=r.stock_code WHERE r.rn=1
ORDER BY s.stock_code LIMIT 12"""):
    print("   ", dict(x))

print("\n=== 4. np_yoy 每期每只股票的记录条数（是否有重复）===")
for x in c.execute("""
SELECT report_period, COUNT(*) rows_, COUNT(DISTINCT stock_code) codes,
       ROUND(COUNT(*)*1.0/COUNT(DISTINCT stock_code),2) per_stock
FROM stock_metrics WHERE metric_name='np_yoy' GROUP BY report_period"""):
    print("   ", dict(x))

print("\n=== 5. 股票池最新规模 ===")
print("    in_csi300=1:", c.execute("SELECT COUNT(*) FROM stocks WHERE in_csi300=1").fetchone()[0])
c.close()
