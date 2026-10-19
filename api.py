# -*- coding: utf-8 -*-
"""FastAPI 服务与静态前端托管。"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import db
from config import WEB_DIR
from services import holders
from services.updater import manager

app = FastAPI(title="CSI 300 Industry Intelligence Workbench", version="1.0")


@app.on_event("startup")
def _startup():
    db.init_db()


@app.middleware("http")
async def _no_store_api(request, call_next):
    """API 响应禁止缓存：避免浏览器复用旧 JSON 导致「数据对不上/表格空」。"""
    resp = await call_next(request)
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# ----------------------------------------------------------------------
# 数据查询
# ----------------------------------------------------------------------
@app.get("/api/stocks")
def api_stocks(industry_id: int | None = Query(default=None),
               q: str | None = Query(default=None),
               holder: str | None = Query(default=None),
               require_increase: bool = Query(default=False)):
    """股票主表数据。

    require_increase=true 只返回存在「合格增持（≥ MIN_INCREASE_AMOUNT）」的公司，
    供重要股东监控页的默认视图使用（服务端筛选，前端不再二次过滤，
    避免前后端口径不一致导致「有持仓却显示暂无数据」）。
    """
    conn = db.get_conn()
    try:
        codes_filter = None
        if industry_id:
            node = conn.execute("SELECT id FROM industries WHERE id=?",
                                (industry_id,)).fetchone()
            if not node:
                raise HTTPException(404, "industry not found")
            children = conn.execute(
                "SELECT id FROM industries WHERE parent_id=?",
                (industry_id,)).fetchall()
            ids = [industry_id] + [c["id"] for c in children]
            marks = ",".join("?" * len(ids))
            codes_filter = {r["stock_code"] for r in conn.execute(
                f"SELECT DISTINCT stock_code FROM stock_industries"
                f" WHERE industry_id IN ({marks})", ids)}
        if holder:
            codes_filter = {r["stock_code"] for r in conn.execute(
                "SELECT DISTINCT stock_code FROM stock_holder_changes"
                " WHERE holder_group=?", (holder,))} if codes_filter is None else \
                codes_filter & {r["stock_code"] for r in conn.execute(
                    "SELECT DISTINCT stock_code FROM stock_holder_changes"
                    " WHERE holder_group=?", (holder,))}

        stocks = conn.execute(
            "SELECT stock_code, ts_code, stock_name, weight FROM stocks"
            " WHERE in_csi300=1 ORDER BY stock_code").fetchall()
        metrics = db.latest_metrics(conn)

        # 重要股东变动（十大流通股东）
        #   holder_map     ：可展示的「加仓」记录（增持 / 新进，金额≥2000万）
        #                    → 「重要股东增持」列；新进因变动股数为 0，用建仓市值计量
        #   holder_present ：该股十大流通股东中出现过的全部重要股东（含减持/不变）
        #                    → 左侧点击某股东后用于"持仓"筛选
        holder_map, holder_present = {}, {}
        for r in conn.execute(
                "SELECT stock_code, holder_group, holder_category, change_type,"
                " est_amount, change_shares, holder_raw, rank, report_date"
                " FROM stock_holder_changes"):
            holder_present.setdefault(r["stock_code"], set()).add(r["holder_group"])
            if r["change_type"] not in holders.ADD_ACTIONS:
                continue
            if (r["est_amount"] or 0) < holders.MIN_INCREASE_AMOUNT:
                continue
            holder_map.setdefault(r["stock_code"], []).append({
                "group": r["holder_group"],
                "category": r["holder_category"],
                "action": r["change_type"],
                "amount": r["est_amount"],
                "shares": r["change_shares"],
                "raw": r["holder_raw"],
                "rank": r["rank"],
                "report_date": r["report_date"],
            })
        for v in holder_map.values():
            v.sort(key=lambda x: -(x["amount"] or 0))

        # 指定股东时，只保留该股东自己的加仓记录：
        # 这样「行」与「单元格内容」口径一致 —— 选中某股东后，表格里不再出现
        # 既无增持也无新进的空行（减持/不变/金额不足的行直接不显示）。
        if holder:
            holder_map = {
                code: [h for h in lst if h["group"] == holder]
                for code, lst in holder_map.items()
            }
            holder_map = {c: v for c, v in holder_map.items() if v}

        # 股票 → 行业标签（含分组路径）
        ind_rows = conn.execute(
            """
            SELECT si.stock_code, g.name AS gname, s.name AS sname
            FROM stock_industries si
            JOIN industries s ON s.id = si.industry_id
            LEFT JOIN industries g ON g.id = s.parent_id
            """
        ).fetchall()
        ind_map = {}
        for r in ind_rows:
            label = f"{r['gname']}·{r['sname']}" if r["gname"] else r["sname"]
            ind_map.setdefault(r["stock_code"], []).append(label)

        q_low = q.lower() if q else None
        rows = []
        for s in stocks:
            if codes_filter is not None and s["stock_code"] not in codes_filter:
                continue
            if q_low and q_low not in s["stock_code"].lower() \
                    and q_low not in (s["stock_name"] or "").lower():
                continue
            if require_increase and not holder_map.get(s["stock_code"]):
                continue
            m = metrics.get(s["stock_code"], {})
            np_row = m.get("np_yoy", {})
            rows.append({
                "code": s["stock_code"],
                "name": s["stock_name"],
                "weight": s["weight"],
                "industries": ind_map.get(s["stock_code"], []),
                "market_cap": m.get("market_cap", {}).get("metric_value"),
                "close": m.get("close_price", {}).get("metric_value"),
                "pe_ttm": m.get("pe_ttm", {}).get("metric_value"),
                "np_yoy": np_row.get("metric_value"),
                "report_period": np_row.get("report_period"),
                "publish_date": np_row.get("data_date"),
                # 业绩变化：np_momentum 1=改善 0=放缓（与 np_yoy 同报告期）
                "np_trend": (
                    "改善" if m.get("np_momentum", {}).get("metric_value") == 1
                    else "放缓" if m.get("np_momentum", {}).get("metric_value") == 0
                    else None
                ),
                "ytd": m.get("ytd", {}).get("metric_value"),
                "holders": holder_map.get(s["stock_code"], []),
                "holder_groups": sorted(holder_present.get(s["stock_code"], [])),
            })
        # 默认按市值降序
        rows.sort(key=lambda r: r["market_cap"] or 0, reverse=True)
        return {"rows": rows, "count": len(rows)}
    finally:
        conn.close()


@app.get("/api/important-shareholders")
def api_important_shareholders():
    """左侧重要股东列表：QFII 名录核验 + 覆盖股票数 / 合格增持股票数。

    - 每个分组附带 QFII 名录信息（官方中英文名/注册地/批准日期），
      可在左侧悬浮查看，确保「重要股东」都能追溯到证监会名录。
    - 覆盖数 = 出现在十大流通股东中的股票数（含减持）；
      增持数仅统计「增持且金额 ≥ 2000 万」的股票。
    - 一只持仓都没有的分组不会出现在列表中。
    """
    conn = db.get_conn()
    try:
        # 名单里的别名表（用于在 QFII 名录中查证）
        seed = holders.load_shareholder_seed()
        alias_map = {s["group"]: s.get("aliases", []) for s in seed.get("shareholders", [])}

        rows = conn.execute(
            "SELECT holder_group, holder_category, stock_code, change_type,"
            " SUM(COALESCE(est_amount,0)) amount"
            " FROM stock_holder_changes GROUP BY holder_group, holder_category,"
            " stock_code, change_type").fetchall()
        agg = {}
        for r in rows:
            a = agg.setdefault(r["holder_group"], {
                "group": r["holder_group"], "category": r["holder_category"],
                "stocks": set(), "increases": set(), "amount": 0.0,
            })
            a["stocks"].add(r["stock_code"])
            # 「增持 + 新进」都算加仓（与主表列口径一致）
            if (r["change_type"] in holders.ADD_ACTIONS
                    and (r["amount"] or 0) >= holders.MIN_INCREASE_AMOUNT):
                a["increases"].add(r["stock_code"])
                a["amount"] += r["amount"] or 0

        out = []
        for v in agg.values():
            if not v["stocks"]:          # 一只持仓都没有 → 不进入 banner
                continue
            ref = holders.qfii_lookup(v["group"], alias_map.get(v["group"]))
            out.append({
                "group": v["group"],
                "category": v["category"],
                "stocks": len(v["stocks"]),
                "increases": len(v["increases"]),
                "amount": round(v["amount"], 1),
                # QFII 名录核验结果：None = 名录外（跨境通道等）
                "qfii": None if not ref else {
                    "cn": ref.get("cn"), "en": ref.get("en"),
                    "region": ref.get("region"), "approved": ref.get("approved"),
                },
            })
        out.sort(key=lambda x: (holders.category_rank(x["category"]),
                                -x["stocks"], x["group"]))
        return {"shareholders": out, "total": len(out),
                "min_increase": holders.MIN_INCREASE_AMOUNT,
                # 名录规模，供前端说明"为什么只有这些"
                "qfii_registry_count": len(holders.load_qfii_registry())}
    finally:
        conn.close()


@app.get("/api/version")
def api_version():
    """前端构建版本：页面据此判断自己是否已被后端更新，若过期则自动刷新。"""
    return {"build": _build_stamp()}


@app.get("/api/industries")
def api_industries():
    conn = db.get_conn()
    try:
        nodes = conn.execute(
            "SELECT id, name, parent_id, node_type, sort_order FROM industries"
            " ORDER BY sort_order, id").fetchall()
        direct = {r["industry_id"]: r["c"] for r in conn.execute(
            "SELECT industry_id, COUNT(*) c FROM stock_industries"
            " GROUP BY industry_id")}
        by_id = {n["id"]: dict(n) for n in nodes}
        for n in by_id.values():
            n["count"] = direct.get(n["id"], 0)
            n["children"] = []
        tree = []
        for n in sorted(by_id.values(), key=lambda x: x["sort_order"]):
            if n["parent_id"] and n["parent_id"] in by_id:
                by_id[n["parent_id"]]["children"].append(n)
            else:
                tree.append(n)
        for g in tree:
            sub_ids = [c["id"] for c in g["children"]]
            if sub_ids:
                marks = ",".join("?" * len(sub_ids))
                g["count"] = conn.execute(
                    f"SELECT COUNT(DISTINCT stock_code) c FROM stock_industries"
                    f" WHERE industry_id IN ({marks})", sub_ids).fetchone()["c"]
        return {"tree": tree}
    finally:
        conn.close()


# ----------------------------------------------------------------------
# 更新流程
# ----------------------------------------------------------------------
@app.post("/api/update")
def api_update():
    if not manager.start():
        raise HTTPException(409, "更新已在进行中")
    return {"ok": True}


@app.get("/api/update/status")
def api_update_status():
    return manager.status()


@app.get("/api/update/last")
def api_update_last():
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM update_runs WHERE status != 'running'"
            " ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ----------------------------------------------------------------------
# 前端静态资源
#
# 缓存问题曾导致「后端已修好、用户浏览器仍跑旧 JS」的假故障（数据不显示、
# 金额格式未变等）。这里做双保险：
#   1) 所有静态响应带 no-store，浏览器不得复用；
#   2) 首页注入 __BUILD__ = web 目录最新修改时间 —— 文件一改，app.js/style.css
#      的 URL 就变，任何代理/磁盘缓存都不可能命中旧版本。
# ----------------------------------------------------------------------
import time as _time
from fastapi.responses import HTMLResponse


def _build_stamp() -> str:
    latest = 0.0
    for p in WEB_DIR.rglob("*"):
        if p.is_file():
            try:
                latest = max(latest, p.stat().st_mtime)
            except OSError:
                pass
    return _time.strftime("%Y%m%d%H%M%S", _time.localtime(latest or _time.time()))


class NoCacheStaticFiles(StaticFiles):
    """vendor/ 下是不会变的第三方库 → 长缓存；其余（app.js/style.css）→ 禁缓存。"""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        probe = " ".join(str(a) for a in args if isinstance(a, (str, bytes)))
        is_vendor = "vendor" in probe
        if is_vendor:
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
        return resp


@app.get("/")
def index():
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace("__BUILD__", _build_stamp()).replace("__MODE__", "local")
    return HTMLResponse(html, headers={
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache",
    })


app.mount("/assets", NoCacheStaticFiles(directory=WEB_DIR), name="assets")
