# -*- coding: utf-8 -*-
"""更细地探测：三季报到底有没有、单票查得到吗、report_type 取值有哪些。"""
import sys, io, collections
sys.path.insert(0, r"C:\Users\RKBL\WorkBuddy\股票看板工作台\csi300_workbench")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from providers.ftshare_provider import FTShareProvider

p = FTShareProvider()

print("=== 1) 2026 全市场各 report_type 的记录数 ===")
for rt in ["q1", "h1", "q2", "q3", "annual", None]:
    try:
        rows = p._paginate("income", page_size=200, year=2026, report_type=rt) \
            if rt else p._paginate("income", page_size=200, year=2026)
    except Exception as e:
        print(f"   report_type={rt}: 失败 {type(e).__name__} {str(e)[:80]}")
        continue
    cnt = collections.Counter(r.get("report_type_cn") or r.get("report_type") for r in rows)
    print(f"   report_type={rt}: 共 {len(rows)} 条 -> {dict(cnt)}")

print("\n=== 2) 单票查三季报（常见早披露个股）===")
for code in ["000001.SZ", "600036.SH", "601398.SH", "300750.SZ", "000333.SZ"]:
    for rt in ["q3", "h1"]:
        try:
            rows = p._extract_rows(p._call("income", stock_code=code,
                                           year=2026, report_type=rt))
        except Exception as e:
            print(f"   {code} {rt}: 失败 {str(e)[:60]}")
            continue
        if not rows:
            print(f"   {code} {rt}: 无数据")
            continue
        r = max(rows, key=lambda x: x.get("publish_date") or "")
        print(f"   {code} {rt}: {len(rows)} 条 | 最新 pub={r.get('publish_date')} "
              f"yoy={r.get('parcomp_n_profit_yoy')} type={r.get('report_type_cn')}")

print("\n=== 3) 2025 三季报对照（去年同期的可得性）===")
rows = p._paginate("income", page_size=200, year=2025, report_type="q3")
print(f"   2025 q3: {len(rows)} 条, 最早披露 "
      f"{min((str(r.get('publish_date'))[:10] for r in rows if r.get('publish_date')), default='—')}")
