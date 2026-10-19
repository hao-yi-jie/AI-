# -*- coding: utf-8 -*-
"""FTShareProvider —— 基于 ftshare-python-sdk 的数据源实现。

所有字段名均经过真实接口验证（2026-09-03）：
- index_weight_list            成分股: component_code/component_name/weight/date
- eastmoney_stock_valuation    估值:   pe_ttm/total_market_cap/close_price/trade_date
- income                       利润表: parcomp_n_profit_yoy/publish_date/report_type
- stock_candlesticks           K线:    ts_millis/close（adjust_kind: none/forward/backward）
- sw_industry_overview         申万行业: industryCode/industryName/level
- sw_industry_constituent_history 成分: stockCode/swLevel1~3Name/outDate

注意：SDK 默认 base_url = https://market.ft.tech/gateway/，零凭据即可调用
本模块用到的全部接口。部分高级接口（实时行情等）需要 API Key，V1 不使用。
"""
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import ftshare as ft
from ftshare.endpoints import ENDPOINTS

from config import HTTP_RETRIES, MAX_WORKERS
from providers.base import DataProvider

REPORT_LABEL = {"q1": "Q1", "h1": "H1", "q2": "H1", "q3": "Q3", "annual": "FY"}


def _code6(raw: str) -> str:
    return raw.split(".")[0].zfill(6)


def _ts_code(code6: str) -> str:
    """6位代码 -> 带交易所后缀。沪深300无北交所标的。"""
    if code6.startswith("6"):
        return f"{code6}.SH"
    return f"{code6}.SZ"


class FTShareProvider(DataProvider):
    name = "FTShare"

    def __init__(self, timeout: float = 30.0):
        self.client = ft.market_api(timeout=timeout)

    # ------------------------------------------------------------------
    # 内部工具：重试 + 通用表格提取 + 分页
    # ------------------------------------------------------------------
    def _call(self, method: str, **kwargs):
        """带重试的 SDK 调用，raw=True 返回原始 JSON。"""
        last_err = None
        for i in range(HTTP_RETRIES + 1):
            try:
                return getattr(self.client, method)(**kwargs, raw=True)
            except Exception as e:  # FtshareError / requests 异常
                last_err = e
                if i < HTTP_RETRIES:
                    time.sleep(1.5 * (i + 1))
        raise last_err

    @staticmethod
    def _extract_rows(payload) -> list:
        """从服务端 JSON 中提取表格行（兼容 records/items/裸列表等结构）。"""
        data = payload.get("data") if isinstance(payload, dict) else payload
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("records", "items", "index_weights", "rows"):
                if isinstance(data.get(key), list):
                    return data[key]
            # 兜底：取第一个列表型字段
            for v in data.values():
                if isinstance(v, list) and (not v or isinstance(v[0], dict)):
                    return v
        return []

    @staticmethod
    def _total(payload) -> int:
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, dict):
            return int(data.get("total") or 0)
        return 0

    def _paginate(self, method: str, page_size: int = 200, max_pages: int = 80,
                  **params) -> list:
        """通用分页拉取，返回全部行。page_size 超过服务端上限时自动降级。"""
        limit = ENDPOINTS[method].max_page_size if method in ENDPOINTS else None
        if limit:
            page_size = min(page_size, limit)
        rows, page = [], 1
        while page <= max_pages:
            payload = self._call(method, page=page, page_size=page_size, **params)
            batch = self._extract_rows(payload)
            if not batch:
                break
            rows.extend(batch)
            total = self._total(payload)
            if total and len(rows) >= total:
                break
            if len(batch) < page_size:
                break
            page += 1
        return rows

    # ------------------------------------------------------------------
    # 1) 股票池成分：沪深300 + 创业板指 + 科创50（按代码去重）
    # ------------------------------------------------------------------
    UNIVERSE_INDEXES = [
        ("000300", "沪深300"),
        ("399006", "创业板指"),
        ("000688", "科创50"),
    ]

    def get_universe_constituents(self) -> list:
        """合并三个指数成分，按 6 位代码去重。

        返回每项: {code, ts_code, name, weight, indices, snapshot_date}
        - weight: 多指数重叠时按 沪深300 > 创业板指 > 科创50 优先取
        - indices: 该股所属指数标签，如 "沪深300|创业板指"
        """
        by_code = {}
        snapshot = None
        for idx_code, idx_name in self.UNIVERSE_INDEXES:
            try:
                rows = self._paginate("index_weight_list", page_size=100,
                                      index_code=idx_code)
            except Exception:
                continue  # 单个指数失败不拖垮整个股票池
            for r in rows:
                code = _code6(str(r.get("component_code", "")))
                if not code:
                    continue
                snapshot = r.get("date") or snapshot
                weight = (float(r["weight"])
                          if r.get("weight") not in (None, "") else None)
                if code in by_code:
                    by_code[code]["indices"].add(idx_name)
                    if by_code[code]["weight"] is None:
                        by_code[code]["weight"] = weight
                else:
                    by_code[code] = {
                        "code": code,
                        "ts_code": _ts_code(code),
                        "name": (r.get("component_name") or "").replace(" ", "").replace("\u3000", ""),
                        "weight": weight,
                        "indices": {idx_name},
                        "snapshot_date": snapshot,
                    }
        out = []
        for it in by_code.values():
            it["indices"] = "|".join(
                name for _, name in self.UNIVERSE_INDEXES
                if name in it["indices"])
            out.append(it)
        return out

    # ------------------------------------------------------------------
    # 2) 全市场估值快照（市值 / PE TTM / 收盘价）
    # ------------------------------------------------------------------
    def get_latest_valuations(self) -> tuple:
        # 注意：eastmoney_stock_valuation 的 trade_date 必须为 YYYYMMDD（无连字符），
        # 传 YYYY-MM-DD 会被服务端拒绝（HTTP 400 "trade_date must use YYYYMMDD format"）。
        d = time.strftime("%Y%m%d")
        rows = []
        for _ in range(15):  # 最多向前找 15 天（覆盖长假）
            rows = self._paginate("eastmoney_stock_valuation", page_size=200,
                                  trade_date=d)
            if rows:
                break
            d = self._prev_day_compact(d)
        out = []
        for r in rows:
            code = _code6(str(r.get("stock_code", "")))
            if not code:
                continue
            pe = r.get("pe_ttm")
            cap = r.get("total_market_cap")
            close = r.get("close_price")
            # 服务端返回的 trade_date 可能是 YYYYMMDD，统一成 YYYY-MM-DD 入库
            td = str(r.get("trade_date") or d).replace("-", "")
            td_fmt = (f"{td[:4]}-{td[4:6]}-{td[6:8]}"
                      if len(td) == 8 and td.isdigit() else td)
            out.append({
                "code": code,
                "ts_code": _ts_code(code),
                "name": r.get("stock_name") or "",
                "close": float(close) if close not in (None, "") else None,
                "market_cap": float(cap) if cap not in (None, "") else None,
                "pe_ttm": float(pe) if pe not in (None, "") else None,
                "trade_date": td_fmt,
            })
        if out:
            return out[0]["trade_date"], out
        # 全部失败：把紧凑日期还原成 YYYY-MM-DD 供上层做回退展示
        return (f"{d[:4]}-{d[4:6]}-{d[6:8]}"
                if len(d) == 8 else d), out

    @staticmethod
    def _prev_day(date_str: str) -> str:
        from datetime import datetime, timedelta
        d = datetime.strptime(date_str.replace("-", ""), "%Y%m%d") - timedelta(days=1)
        return d.strftime("%Y-%m-%d")

    @staticmethod
    def _prev_day_compact(date_str: str) -> str:
        """YYYYMMDD 格式的前一天。"""
        from datetime import datetime, timedelta
        d = datetime.strptime(date_str, "%Y%m%d") - timedelta(days=1)
        return d.strftime("%Y%m%d")

    # ------------------------------------------------------------------
    # 3) 归母净利润快照（批量模式）：返回每只股票所有候选报告期的同比与累计净利
    #    候选期 = 今年 q3/h1/q1 + 去年 q3/h1/q1/annual，供：
    #    - np_yoy 展示（取最新披露期）
    #    - PE 自算（当年净利年化，fallback 上年年报）
    #    - 业绩变化趋势（当年最新累计期同比 vs 前一期累计同比）
    #
    #    重要：同比一律用「同期累计净利」自算，不直接采用数据源返回的
    #    parcomp_n_profit_yoy —— 该字段在「去年同期净利为负」时符号会整体翻转
    #    （数据源公式等价于 (今-去)/去，分母是带符号的旧值；当旧值为负，
    #    结果符号就反了）。典型受害者：佰维存储 2026H1 实际 +3273%（扭亏），
    #    数据源给 -3273%；摩尔线程实际 +96%（亏损收窄），数据源给 -96%。
    #    标准公式应为 (今-去)/|去|，故此处改为自算。数据源的 yoy 仅在
    #    缺同期数据时作为兜底。
    # ------------------------------------------------------------------
    # 需要去年同期的报告期（同比口径要求"同季对照"，而非相邻期）
    SAME_PERIOD_MAP = {"q1": "q1", "h1": "h1", "q3": "q3", "annual": "annual"}

    def get_net_profit_yoy(self, ts_codes: set) -> list:
        """返回每只目标股票所有候选期的利润快照记录（含自算同比）。"""
        now = time.localtime()
        year = now.tm_year
        # 按「由新到旧」排列；去年各期用于今年同期的同比对照
        candidates = [(year, "q3"), (year, "h1"), (year, "q1"),
                      (year - 1, "annual"), (year - 1, "q3"),
                      (year - 1, "h1"), (year - 1, "q1")]

        # 先抓全量，按 (code, year, report_type) 存累计净利，供同期对照
        profit_map = {}    # code -> {(y, rt): cum_profit}
        recs_meta = {}     # (code, y, rt) -> rec 元信息
        for y, rt in candidates:
            try:
                rows = self._paginate("income", page_size=200, year=y,
                                      report_type=rt)
            except Exception:
                continue
            for r in rows:
                code = _code6(str(r.get("stock_code", "")))
                if code not in ts_codes:
                    continue
                profit = r.get("parcomp_n_profit")
                yoy = r.get("parcomp_n_profit_yoy")
                if profit in (None, "") and yoy in (None, ""):
                    continue
                rec = {
                    "code": code,
                    "ts_code": r.get("stock_code") or _ts_code(code),
                    "name": r.get("stock_name") or "",
                    "report_period": f"{y}{REPORT_LABEL.get(rt, rt.upper())}",
                    "publish_date": r.get("publish_date"),
                    "year": y,
                    "report_type": rt,   # q1 / h1 / q3 / annual（h1=累计两季）
                }
                if profit not in (None, ""):
                    rec["cum_profit"] = float(profit)  # 归母净利润（该期累计）
                    profit_map.setdefault(code, {})[(y, rt)] = float(profit)
                if yoy not in (None, ""):
                    rec["src_yoy"] = float(yoy)        # 数据源原始值（兜底用）
                # 同一 (code, y, rt) 若重复出现，保留披露日更晚的
                key = (code, y, rt)
                old = recs_meta.get(key)
                if old is None or (rec.get("publish_date") or "") > \
                        (old.get("publish_date") or ""):
                    recs_meta[key] = rec

        out = []
        for (code, y, rt), rec in recs_meta.items():
            # 自算同比：今年各期与去年同期对比（同比 = 同季对照）
            if rt != "annual" or y == year - 1:
                prev_key = (y - 1, self.SAME_PERIOD_MAP.get(rt, rt))
                prev = profit_map.get(code, {}).get(prev_key)
                cur = rec.get("cum_profit")
                if prev is not None and cur is not None and prev != 0:
                    rec["np_yoy"] = (cur - prev) / abs(prev) * 100
            # 自算不可得时退回数据源值（可能符号有误，但好过没有）
            if "np_yoy" not in rec and rec.get("src_yoy") is not None:
                rec["np_yoy"] = rec["src_yoy"]
            out.append(rec)
        return out

    # ------------------------------------------------------------------
    # 4) 年初首个交易日收盘价（前复权，用于 YTD 计算）
    # ------------------------------------------------------------------
    def get_year_first_close(self, ts_code: str, year: int):
        since = int(time.mktime((year, 1, 1, 0, 0, 0, 0, 0, -1)) * 1000)
        until = int(time.mktime((year, 1, 20, 0, 0, 0, 0, 0, -1)) * 1000)
        try:
            rows = self._extract_rows(self._call(
                "stock_candlesticks", symbol=ts_code, interval_unit="day",
                interval_value=1, adjust_kind="forward",
                since_ts_millis=since, until_ts_millis=until, limit=1))
            if rows:
                return float(rows[0]["close"])
        except Exception:
            return None
        return None

    def get_year_first_close_many(self, ts_codes: list, year: int,
                                  max_workers: int = MAX_WORKERS) -> dict:
        """并发获取多只股票的年初收盘价。"""
        out = {}

        def work(code):
            return code, self.get_year_first_close(code, year)

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for code, close in ex.map(work, ts_codes):
                out[code] = close
        return out

    # ------------------------------------------------------------------
    # 5) 申万行业映射（行业分类引导，可选能力）
    # ------------------------------------------------------------------
    def get_sw_industry_map(self, levels=(2, 3)) -> dict:
        """返回 {code6: {'l1':..,'l2':..,'l3':..}}。

        levels 控制拉取哪些层级的行业成分（层级越高请求越少）：
        行内每条记录自带 swLevel1~3Name，因此查 L2 即可同时拿到 L1+L2 归属，
        仅当分类规则引用了 L3 名称时才需要拉取 L3。
        """
        # 申万日频快照当日盘中可能尚未生成，逐步回退日期（最多 15 天，覆盖长假）
        industries = []
        date = time.strftime("%Y%m%d")
        for _ in range(15):
            try:
                industries = self._paginate("sw_industry_overview",
                                            page_size=200, date=date)
            except Exception:
                industries = []
            if industries:
                break
            from datetime import datetime, timedelta
            d = datetime.strptime(date, "%Y%m%d") - timedelta(days=1)
            date = d.strftime("%Y%m%d")
        codes = [r["industryCode"] for r in industries
                 if r.get("industryCode") and r.get("level") in levels]
        stock_map = defaultdict(dict)

        def work(code):
            try:
                rows = self._paginate("sw_industry_constituent_history",
                                      page_size=200, industry_code=code)
            except Exception:
                return []
            return [r for r in rows if not r.get("outDate")]

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            for rows in ex.map(work, codes):
                for r in rows:
                    c = _code6(str(r.get("stockCode", "")))
                    if not c:
                        continue
                    m = stock_map[c]
                    for lv in ("swLevel1Name", "swLevel2Name", "swLevel3Name"):
                        if r.get(lv):
                            key = "l" + lv[7]  # l1/l2/l3
                            m[key] = r[lv]
        return dict(stock_map)
