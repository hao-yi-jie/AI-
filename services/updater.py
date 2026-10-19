# -*- coding: utf-8 -*-
"""数据更新流程。

点击 [更新数据] 后在后台线程执行：
成分股 → 市场数据 → 财务数据 → 估值数据 → YTD计算 → 行业分类
每步独立成败，部分失败不影响其他步骤，状态通过 /api/update/status 轮询。
"""
import json
import os
import sys
import threading
import traceback
from datetime import datetime, date
from pathlib import Path

import db
from config import MAX_WORKERS
from providers.ftshare_provider import FTShareProvider, REPORT_LABEL
from services import classifier, holders


class UpdateManager:
    """进程内单例：管理后台更新线程与状态。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._status = {"running": False}
        self._thread = None

    # ---------------- 对外接口 ----------------
    def start(self) -> bool:
        with self._lock:
            if self._status.get("running"):
                return False
            self._status = {
                "running": True,
                "run_id": None,
                "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "finished_at": None,
                "overall": "running",
                "steps": self._init_steps(),
            }
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            return True

    def status(self) -> dict:
        with self._lock:
            return dict(self._status)

    # ---------------- 内部实现 ----------------
    @staticmethod
    def _init_steps() -> list:
        return [
            {"key": k, "label": l, "status": "pending", "detail": ""}
            for k, l in [
                ("constituents", "股票池成分"),
                ("market", "市场数据"),
                ("financial", "财务数据"),
                ("valuation", "估值数据"),
                ("ytd", "YTD计算"),
                ("holders", "重要股东"),
                ("classify", "行业分类"),
                ("cloud", "同步到云端"),
            ]
        ]

    def _step(self, key: str, status: str, detail: str = ""):
        with self._lock:
            for s in self._status["steps"]:
                if s["key"] == key:
                    s["status"] = status
                    s["detail"] = detail

    def _run(self):
        conn = db.get_conn()
        run_id = None
        provider = None
        try:
            provider = FTShareProvider()
            cur = conn.execute(
                "INSERT INTO update_runs (started_at, status) VALUES (?, 'running')",
                (db.now_str(),))
            run_id = cur.lastrowid
            conn.commit()
            with self._lock:
                self._status["run_id"] = run_id

            ctx = self._step_constituents(provider, conn)
            self._step_market(provider, conn, ctx)
            self._step_financial(provider, conn, ctx)
            self._step_valuation(conn, ctx)
            self._step_ytd(provider, conn, ctx)
            self._step_holders(provider, conn, ctx)
            self._step_classify(provider, conn)
            self._step_cloud(conn)

            statuses = [s["status"] for s in self.status()["steps"]]
            if all(s == "ok" for s in statuses):
                overall = "done"
            elif any(s == "failed" for s in statuses):
                overall = "partial"
            else:
                overall = "partial"
            self._finish(conn, run_id, overall)
        except Exception as e:
            traceback.print_exc()
            self._finish(conn, run_id, "failed", str(e))
        finally:
            conn.close()

    def _finish(self, conn, run_id, overall: str, error: str = ""):
        finished = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if run_id:
            snap = json.dumps(self.status()["steps"], ensure_ascii=False)
            conn.execute(
                "UPDATE update_runs SET finished_at=?, status=?, steps=? WHERE id=?",
                (finished, overall, snap, run_id))
            conn.commit()
        with self._lock:
            self._status["running"] = False
            self._status["finished_at"] = finished
            self._status["overall"] = overall
            if error:
                self._status["error"] = error

    # ---------------- 各步骤 ----------------
    def _step_constituents(self, provider, conn) -> dict:
        try:
            items = provider.get_universe_constituents()
            if not items:
                raise RuntimeError("成分股列表为空")
            for it in items:
                db.upsert_stock(conn, it["code"], it["ts_code"],
                                it["name"], it["weight"],
                                indices=it.get("indices"))
            conn.commit()
            snapshot = items[0].get("snapshot_date") or "-"
            by_idx = {}
            for it in items:
                for tag in it["indices"].split("|"):
                    by_idx[tag] = by_idx.get(tag, 0) + 1
            detail = f"共 {len(items)} 只（去重后，快照 {snapshot}）: " + \
                " / ".join(f"{k} {v}" for k, v in by_idx.items())
            self._step("constituents", "ok", detail)
            return {"stocks": items, "snapshot": snapshot}
        except Exception as e:
            self._step("constituents", "failed", str(e)[:200])
            raise  # 成分股失败则整个更新无意义

    def _step_market(self, provider, conn, ctx):
        try:
            trade_date, valuations = provider.get_latest_valuations()
            codes = {s["code"] for s in ctx["stocks"]}
            by_code = {v["code"]: v for v in valuations}
            n_cap = n_close = 0
            for s in ctx["stocks"]:
                v = by_code.get(s["code"])
                if not v:
                    continue
                if v["market_cap"] is not None:
                    db.save_metric(conn, s["code"], "market_cap",
                                   v["market_cap"], data_date=trade_date,
                                   source="FTShare:eastmoney_stock_valuation")
                    n_cap += 1
                if v["close"] is not None:
                    db.save_metric(conn, s["code"], "close_price", v["close"],
                                   data_date=trade_date,
                                   source="FTShare:eastmoney_stock_valuation")
                    n_close += 1
            conn.commit()
            ctx["valuations"] = by_code
            ctx["trade_date"] = trade_date
            self._step("market", "ok",
                       f"交易日 {trade_date}：市值 {n_cap} 只，收盘价 {n_close} 只")
        except Exception as e:
            ctx["valuations"] = {}
            self._step("market", "failed", str(e)[:200])

    def _step_financial(self, provider, conn, ctx):
        """财务数据：多期同比入库 + 计算业绩变化（改善/放缓）。"""
        try:
            codes = {s["code"] for s in ctx["stocks"]}
            recs = provider.get_net_profit_yoy(codes)
            periods = {}   # code -> {(year, report_type): rec}
            n_yoy = 0
            for r in recs:
                periods.setdefault(r["code"], {})[
                    (r["year"], r["report_type"])] = r
                if r.get("np_yoy") is not None:
                    db.save_metric(conn, r["code"], "np_yoy", r["np_yoy"],
                                   report_period=r["report_period"],
                                   data_date=r.get("publish_date"),
                                   source="FTShare:income")
                    n_yoy += 1
            ctx["income"] = periods  # PE 自算 / 业绩变化用

            # 业绩变化：1=改善 0=放缓（仅当年有财报时判断）
            y = date.today().year
            n_mom = n_imp = n_slow = 0
            for code, per in periods.items():
                mv = self._momentum(per, y)
                if mv is None:
                    continue
                cur_rt = self._latest_cur_rt(per, y)
                rec = per[(y, cur_rt)]
                db.save_metric(conn, code, "np_momentum", float(mv),
                               report_period=rec["report_period"],
                               data_date=rec.get("publish_date"),
                               source="calc:np-yoy-momentum")
                n_mom += 1
                if mv:
                    n_imp += 1
                else:
                    n_slow += 1
            conn.commit()
            self._step("financial", "ok",
                       f"同比入库 {n_yoy} 期；业绩变化 {n_mom} 只"
                       f"（改善 {n_imp} / 放缓 {n_slow}）")
        except Exception as e:
            traceback.print_exc()
            ctx["income"] = {}
            self._step("financial", "failed", str(e)[:200])

    # 各报告期对应的已披露季度数（h1=Q1+Q2 累计两季）
    N_QUARTERS = {"q1": 1, "h1": 2, "q3": 3, "annual": 4}
    # 各累计期对应的"前一期"累计期
    PREV_CUM = {"h1": "q1", "q3": "h1"}

    # 报告期先后次序（数值越大越新），用于确定「最新已披露报告期」。
    # 必须按报告期本身排序，不能按 publish_date —— 旧报告期的更正公告
    # 披露日可能晚于新报告期，会把最新期错误地选成上一期。
    RT_ORDER = {"q1": 1, "h1": 2, "q2": 2, "q3": 3, "annual": 4}

    @staticmethod
    def _latest_cur_rt(per, year_now):
        """当年已披露报告期中报告期最新的一个 report_type；当年无财报返回 None。"""
        rts = [rt for (y, rt) in per if y == year_now]
        if not rts:
            return None
        return max(rts, key=lambda rt: UpdateManager.RT_ORDER.get(rt, 0))

    @staticmethod
    def _momentum(per, year_now):
        """业绩变化判断（按用户规则）：
        - 当年有多期（最新累计期 H1/Q3 可对比前一期 Q1/H1）：
          最新累计期同比 > 前一期累计同比 → 改善(1)；否则放缓(0)。
        - 当年仅有 Q1：Q1 同比 > 0 → 改善；否则放缓。
        - 当年无财报（显示的是上年年报等）：无法判断 → None。
        - 极端缺前一期数据时退化为按最新期同比正负判断。
        """
        cur_rt = UpdateManager._latest_cur_rt(per, year_now)
        if not cur_rt:
            return None
        rec = per[(year_now, cur_rt)]
        yoy = rec.get("np_yoy")
        if yoy is None:
            return None
        if cur_rt == "q1":            # 当年仅有 Q1，无合并可对比 → 符号判断
            return 1 if yoy > 0 else 0
        prev = per.get((year_now, UpdateManager.PREV_CUM.get(cur_rt)))
        if prev and prev.get("np_yoy") is not None:
            return 1 if yoy > prev["np_yoy"] else 0   # 累计同比边际加速 → 改善
        return 1 if yoy > 0 else 0

    def _step_valuation(self, conn, ctx):
        """PE 自算（不用 API 的滚动 TTM，因其对高增长股失真）：

        年化归母净利 = 当年已披露季度的累计归母净利 ÷ 已披露季度数 × 4
        PE = 当前总市值 ÷ 年化归母净利
        当年无任何财报时回退用上年年报（静态 PE）；净利为负则 PE 为负（展示层显示"亏损"）。
        """
        try:
            by_code = ctx.get("valuations", {})
            trade_date = ctx.get("trade_date", db.now_str()[:10])
            income = ctx.get("income", {})
            year_now = date.today().year
            n = n_neg = n_null = 0
            bases = set()
            # 清掉同日旧 PE 记录（此前来自 API 滚动 TTM 的口径），保留历史日期
            conn.execute("DELETE FROM stock_metrics WHERE metric_name='pe_ttm'"
                         " AND data_date=?", (trade_date,))
            for s in ctx["stocks"]:
                code = s["code"]
                v = by_code.get(code)
                per = income.get(code, {})
                annualized, basis = None, None
                cur_rt = self._latest_cur_rt(per, year_now)
                if cur_rt:
                    # 当年已披露 → 年化：累计净利 ÷ 已披露季度数 × 4
                    rec = per[(year_now, cur_rt)]
                    if rec.get("cum_profit") is not None:
                        annualized = (rec["cum_profit"]
                                      / self.N_QUARTERS.get(cur_rt, 1) * 4)
                        basis = rec["report_period"]
                else:
                    # 当年无财报 → 回退上年年报（静态 PE）
                    prev_ann = per.get((year_now - 1, "annual"))
                    if prev_ann and prev_ann.get("cum_profit") is not None:
                        annualized = prev_ann["cum_profit"]
                        basis = f"{year_now - 1}FY"
                if v and v.get("market_cap") and annualized:
                    pe = v["market_cap"] / annualized
                    db.save_metric(conn, code, "pe_ttm", pe,
                                   report_period=basis, data_date=trade_date,
                                   source="calc:market_cap/annualized_np")
                    n += 1
                    bases.add(basis)
                    if pe < 0:
                        n_neg += 1
                else:
                    # 无市值/无净利数据 → 存空值，避免旧口径残留
                    db.save_metric(conn, code, "pe_ttm", None,
                                   data_date=trade_date,
                                   source="calc:market_cap/annualized_np")
                    n_null += 1
            conn.commit()
            bases_txt = ", ".join(sorted(bases, reverse=True)[:4]) or "-"
            self._step("valuation", "ok",
                       f"自算 {n} 只（市值÷当年已披露净利年化，基准 {bases_txt}）；"
                       f"亏损/缺失 {n_neg + n_null} 只")
        except Exception as e:
            traceback.print_exc()
            self._step("valuation", "failed", str(e)[:200])

    def _step_ytd(self, provider, conn, ctx):
        try:
            year = date.today().year
            codes = [s["ts_code"] for s in ctx["stocks"]]
            base = provider.get_year_first_close_many(codes, year,
                                                      max_workers=MAX_WORKERS)
            latest = db.latest_metrics(conn)
            n = 0
            for s in ctx["stocks"]:
                first = base.get(s["ts_code"])
                close_row = latest.get(s["code"], {}).get("close_price")
                if not first or not close_row or not close_row["metric_value"]:
                    continue
                ytd = (close_row["metric_value"] / first - 1) * 100
                db.save_metric(conn, s["code"], "ytd", ytd,
                               data_date=db.now_str()[:10],
                               source="calc:close_price/year_first_close(fwd-adj)")
                n += 1
            conn.commit()
            self._step("ytd", "ok", f"完成 {n} 只（基准：{year} 年首个交易日收盘，前复权）")
        except Exception as e:
            self._step("ytd", "failed", str(e)[:200])

    def _step_cloud(self, conn):
        """把最新数据同步到 Cloudflare D1（rkstock.pages.dev 的只读副本）。

        未配置云端（data/cloudflare.json 不存在）时跳过，不影响本地使用；
        同步失败也只标记该步失败，不回滚本地数据。
        """
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                                   / "cloudflare"))
            import cf_api  # noqa: PLC0415
            if not os.path.exists(cf_api.CONF):
                self._step("cloud", "skipped", "未配置云端，跳过")
                return
            import sync_to_d1  # noqa: PLC0415
            r = sync_to_d1.sync(verbose=False)
            if r.get("ok"):
                self._step("cloud", "ok",
                           f"已推送到 D1：{r['counts'].get('stocks')} 只股票 / "
                           f"{r['sent']} 条语句（{r['meta'].get('synced_at', '')}）")
            else:
                self._step("cloud", "failed",
                           f"{r['failed']} 条语句失败，请查看日志")
        except Exception as e:                                    # noqa: BLE001
            traceback.print_exc()
            self._step("cloud", "failed", f"{type(e).__name__}: {str(e)[:120]}")

    def _step_holders(self, provider, conn, ctx):
        """重要股东（十大流通股东）：

        ① 抓取全量原始股东 → stock_float_holders_raw
        ② 离线按 QFII 名单匹配 → stock_holder_changes
        把「抓数据」与「认名单」解耦：调整名单无需重新抓取。
        """
        try:
            errors = []
            raw = holders.fetch_raw_holders(provider, ctx["stocks"],
                                            errors=errors)
            # 抓取失败的股票保留其原始快照，避免出现空洞
            failed = {c for c, _ in errors}
            if failed:
                ok_codes = [s["code"] for s in ctx["stocks"]
                            if s["code"] not in failed]
                if ok_codes:
                    marks = ",".join("?" * len(ok_codes))
                    conn.execute(
                        f"DELETE FROM stock_float_holders_raw"
                        f" WHERE stock_code IN ({marks})", ok_codes)
            else:
                conn.execute("DELETE FROM stock_float_holders_raw")
            conn.executemany(
                """INSERT INTO stock_float_holders_raw
                   (stock_code, report_date, rank, holder_raw, change_type,
                    change_shares, shareholding, share_ratio, fetched_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""", raw)
            conn.commit()

            stat = holders.rematch(conn)
            raw_stocks = conn.execute(
                "SELECT COUNT(DISTINCT stock_code) c"
                " FROM stock_float_holders_raw").fetchone()["c"]
            note = ""
            if errors:
                note = (f"；{len(errors)} 只抓取失败（保留上期）："
                        + ", ".join(c for c, _ in errors[:8])
                        + ("…" if len(errors) > 8 else ""))
            detail = (f"原始 {raw_stocks} 只 / {len(raw)} 条；"
                      f"{stat['stocks']} 只出现重要股东，"
                      f"记录 {stat['records']} 条（增持 {stat['increases']} 笔）"
                      f"{note}")
            self._step("holders", "failed" if errors else "ok", detail)
        except Exception as e:
            traceback.print_exc()
            self._step("holders", "failed", str(e)[:200])

    def _step_classify(self, provider, conn):
        try:
            result = classifier.classify_stocks(provider, conn)
            self._step("classify", "ok",
                       f"规则 {result['rules']} 条：已归类 {result['matched']} 只，"
                       f"待归类 {result['unmatched']} 只")
        except Exception as e:
            traceback.print_exc()
            self._step("classify", "failed", str(e)[:200])


# 模块级单例
manager = UpdateManager()
