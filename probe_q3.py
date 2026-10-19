# -*- coding: utf-8 -*-
"""测试 FTShare 现在能拿到多少 2026 三季报。"""
import sys, io
sys.path.insert(0, r"C:\Users\RKBL\WorkBuddy\股票看板工作台\csi300_workbench")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from providers.ftshare_provider import FTShareProvider, _code6
import sqlite3

p = FTShareProvider()
conn = sqlite3.connect(r"C:\Users\RKBL\WorkBuddy\股票看板工作台\csi300_workbench\data\workbench.db")
codes = {r[0] for r in conn.execute("SELECT stock_code FROM stocks WHERE in_csi300=1")}
conn.close()
print("股票池:", len(codes))

for y, rt in [(2026, "q3"), (2026, "h1"), (2026, "q1"), (2025, "annual")]:
    try:
        rows = p._paginate("income", page_size=200, year=y, report_type=rt)
    except Exception as e:
        print(f"  {y} {rt}: 抓取失败 {type(e).__name__}: {str(e)[:100]}")
        continue
    hit = [r for r in rows if _code6(str(r.get("stock_code", ""))) in codes]
    yoy_ok = [r for r in hit if r.get("parcomp_n_profit_yoy") not in (None, "")]
    dates = sorted({str(r.get("publish_date"))[:10] for r in hit if r.get("publish_date")})
    print(f"  {y} {rt}: 接口返回 {len(rows)} 条 | 命中股票池 {len(hit)} 只 | "
          f"有同比 {len(yoy_ok)} 只 | 披露日 {dates[:1]}~{dates[-1:] if dates else '—'}")
    if hit[:2]:
        for r in hit[:2]:
            print(f"      样例 {r.get('stock_code')} {r.get('stock_name')} "
                  f"yoy={r.get('parcomp_n_profit_yoy')} profit={r.get('parcomp_n_profit')} "
                  f"pub={r.get('publish_date')} type={r.get('report_type_cn') or r.get('report_type')}")
