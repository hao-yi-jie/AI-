# -*- coding: utf-8 -*-
"""本地 SQLite → Cloudflare D1 全量同步。

只推送「云端只读页面真正需要」的数据，控制 D1 免费额度占用：
  stocks / industries / stock_industries / stock_holder_changes  → 全量
  stock_metrics                                                 → 只推每只股票每个指标的**最新一行**
                                                                  (25110 行 → 约 3200 行)
  update_runs                                                   → 最近 20 条
  stock_float_holders_raw                                       → 不推（云端不做匹配）

用法：python cloudflare/sync_to_d1.py            # 同步
     from cloudflare.sync_to_d1 import sync    # 更新流程里调用
"""
from __future__ import annotations

import os
import sqlite3
import sys
import io
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cf_api as cf                                                  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "workbench.db")

ROWS_LIMIT_PARAMS = 90   # D1 对单条语句的绑定参数有上限（实测超过 ~330 就报
                         # "too many SQL variables"），按列数换算每行拼多少条
STMT_PER_REQ = 40        # 每次 API 请求带多少条语句


def _plan(conn: sqlite3.Connection) -> list[tuple[str, str, list, list]]:
    """返回 [(table, sql_select, columns, rows)]"""
    plan = []

    def q(sql):
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description]
        return cols, [list(r) for r in cur.fetchall()]

    for table, sql in [
        ("stocks", "SELECT stock_code, ts_code, stock_name, weight, in_csi300,"
                   " indices, sw_l1, sw_l2, sw_l3, updated_at FROM stocks"
                   " WHERE in_csi300=1"),
        ("industries", "SELECT id, name, parent_id, node_type, sort_order"
                       " FROM industries"),
        ("stock_industries", "SELECT stock_code, industry_id FROM stock_industries"),
        ("stock_holder_changes",
         "SELECT id, stock_code, report_date, holder_group, holder_category,"
         " holder_raw, rank, change_type, change_shares, shareholding,"
         " share_ratio, est_amount, data_date, source, updated_at"
         " FROM stock_holder_changes"),
        # 只推最新一期指标。注意：不能只按 MAX(id) 挑 —— np_yoy/np_momentum
        # 是多报告期并存的，旧报告期(如 2025Q3)的补披露/更正公告会获得更大的 id，
        # 若按 id 挑就会把云端展示期错误地退回上一期。这里与本地
        # db.latest_metrics 保持同构：先按报告期先后，再按 data_date / id 兜底。
        ("stock_metrics",
         "SELECT id, stock_code, metric_name, metric_value, report_period,"
         " data_date, source, updated_at FROM stock_metrics WHERE id IN ("
         "   SELECT id FROM ("
         "     SELECT id, ROW_NUMBER() OVER ("
         "       PARTITION BY stock_code, metric_name ORDER BY"
         "         CASE WHEN report_period IS NULL OR report_period = '' THEN 0"
         "              ELSE CAST(SUBSTR(report_period, 1, 4) AS INTEGER) * 10"
         "                   + CASE SUBSTR(report_period, -2)"
         "                       WHEN 'Q1' THEN 1 WHEN 'H1' THEN 2"
         "                       WHEN 'Q2' THEN 2 WHEN 'Q3' THEN 3"
         "                       WHEN 'FY' THEN 4 ELSE 0 END"
         "         END DESC, data_date DESC, id DESC) rn"
         "     FROM stock_metrics) WHERE rn = 1)"),
        ("update_runs", "SELECT id, started_at, finished_at, status, steps"
                        " FROM update_runs ORDER BY id DESC LIMIT 20"),
    ]:
        cols, rows = q(sql)
        plan.append((table, cols, rows))

    # 股东元信息：本地用 QFII 名录核验好再推上去（云端不需要名录文件）
    try:
        sys.path.insert(0, ROOT)
        from services import holders as _h
        seed = _h.load_shareholder_seed()
        alias_map = {s["group"]: s.get("aliases", [])
                     for s in seed.get("shareholders", [])}
        groups = [r[0] for r in conn.execute(
            "SELECT DISTINCT holder_group FROM stock_holder_changes"
            " WHERE holder_group IS NOT NULL ORDER BY holder_group")]
        meta_rows = []
        for g in groups:
            ref = _h.qfii_lookup(g, alias_map.get(g)) or {}
            cat = conn.execute(
                "SELECT holder_category FROM stock_holder_changes"
                " WHERE holder_group=? LIMIT 1", (g,)).fetchone()
            meta_rows.append([g, (cat[0] if cat else None),
                              ref.get("cn"), ref.get("en"),
                              ref.get("region"), ref.get("approved")])
        plan.append(("holder_meta",
                     ["holder_group", "category", "qfii_cn", "qfii_en",
                      "qfii_region", "qfii_approved"], meta_rows))
    except Exception as e:                                        # noqa: BLE001
        print("  ! 股东元信息生成失败（跳过）:", type(e).__name__, e)

    return plan


def sync(verbose: bool = True, conf: dict | None = None) -> dict:
    conf = conf or cf.load_conf()
    conn = sqlite3.connect(DB)
    plan = _plan(conn)
    conn.close()

    total_rows = sum(len(r) for _, _, r in plan)
    if verbose:
        print(f"待同步 {len(plan)} 张表 / {total_rows} 行")
        for t, c, r in plan:
            print(f"   {t:<26} {len(r):>6} 行 × {len(c)} 列")

    # 拼语句：先清表，再分批多行 INSERT
    stmts: list[dict] = []
    for table, cols, rows in plan:
        stmts.append({"sql": f"DELETE FROM {table}", "params": []})
        collist = ",".join(cols)
        ph = "(" + ",".join("?" * len(cols)) + ")"
        per_stmt = max(1, ROWS_LIMIT_PARAMS // len(cols))
        for i in range(0, len(rows), per_stmt):
            chunk = rows[i:i + per_stmt]
            sql = (f"INSERT INTO {table} ({collist}) VALUES "
                   + ",".join([ph] * len(chunk)))
            params = [v for row in chunk for v in row]
            stmts.append({"sql": sql, "params": params})

    # 元信息
    def s(k, v):
        stmts.append({"sql": "INSERT INTO sync_meta (k,v) VALUES (?,?)"
                             " ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                      "params": [k, str(v)]})
    s("synced_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    s("stock_count", sum(len(r) for t, _, r in plan if t == "stocks"))
    s("source", conf.get("host_label", "local-workbench"))
    try:
        sys.path.insert(0, ROOT)
        from services import holders as _h
        s("qfii_registry_count", len(_h.load_qfii_registry()))
    except Exception:                                             # noqa: BLE001
        pass

    # 分批提交
    sent, failed = 0, 0
    t0 = time.time()
    for i in range(0, len(stmts), STMT_PER_REQ):
        batch = stmts[i:i + STMT_PER_REQ]
        r = cf.d1_batch(batch, conf=conf)
        if r.get("success"):
            sent += len(batch)
        else:
            failed += len(batch)
            if verbose:
                print("   ✗ 批次失败:", json.dumps(r, ensure_ascii=False)[:300])
    if verbose:
        print(f"完成：{sent} 条语句成功 / {failed} 失败，用时 {time.time()-t0:.1f}s")

    # 回读校验
    r = cf.d1_query("SELECT k, v FROM sync_meta", conf=conf)
    meta = {x["k"]: x["v"] for x in (r.get("result") or [{}])[0].get("results", [])}
    counts = {}
    for t, _, _ in plan:
        rr = cf.d1_query(f"SELECT COUNT(*) AS c FROM {t}", conf=conf)
        counts[t] = (rr.get("result") or [{}])[0].get("results", [{}])[0].get("c")
    if verbose:
        print("D1 回读:", counts)
        print("sync_meta:", meta)
    return {"ok": failed == 0, "sent": sent, "failed": failed,
            "counts": counts, "meta": meta}


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sync()
