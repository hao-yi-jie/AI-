# -*- coding: utf-8 -*-
"""重要股东（十大流通股东）监控服务。

数据源：FTShare stock_float_holders（十大流通股东，注意不是十大股东）
名单：seed/important_shareholders.json —— 支持中英文/多实体别名，
      按数组顺序优先匹配（精确主体在前，避免"摩根"/"摩根士丹利"混淆）。
"""
import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor

from config import SEED_DIR, HOLDER_WORKERS
import db

# 增持金额下限（亿元）：2000 万以内的增持不展示
MIN_INCREASE_AMOUNT = 0.2

# 计入「重要股东增持」列的变动类型：
#   增持 = 主动加仓；新进 = 本期新进入十大流通股东（建仓），同样属于加仓行为。
#   减持 / 不变 不计入（用户明确要求减持不显示）。
ADD_ACTIONS = ("增持", "新进")

# 左侧 banner 的类别显示顺序（同一类别必须连续，否则表头会重复出现）
CATEGORY_ORDER = ["北向资金", "港股托管", "主权基金", "外资投行", "外资资管",
                  "其他外资机构", "其他QFII", "中资机构QFII"]


def category_rank(cat: str) -> int:
    return CATEGORY_ORDER.index(cat) if cat in CATEGORY_ORDER else len(CATEGORY_ORDER)

# 归一化：大小写、空格、常见中英文标点一律去掉后再比较。
# 例：名录写 "J.P. Morgan Securities plc"，股东名却是
#     "J.P.Morgan Securities PLC-自有资金" —— 不归一化就会漏匹配。
_PUNCT_RE = re.compile(r"[\s\u3000\.\,\-\&/·、()（）\[\]【】]")


def _norm(s: str) -> str:
    return _PUNCT_RE.sub("", str(s or "")).upper()


def load_shareholder_seed() -> dict:
    path = SEED_DIR / "important_shareholders.json"
    if not path.exists():
        return {"shareholders": [], "exclude_keywords": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_matchers() -> tuple:
    """构建匹配规则：(rules, excludes)。

    rules 每项 (alias_norm, group, category, exact)：
    - exact=False 用包含匹配（一般机构名）
    - exact=True 用于过短的纯英文缩写（如 QIA/PIF/GIC），必须完全相等，
      避免误匹配自然人姓名（例如 "QIAO LONG HUANG" 曾误中 "QIA"）
    excludes 用于剔除境内公募/资管产品（"景顺长城…证券投资基金"、
    "交银施罗德…混合型"、"摩根士丹利数字经济混合型证券投资基金" 等）。
    """
    seed = load_shareholder_seed()
    rules = []
    for item in seed.get("shareholders", []):
        for alias in item.get("aliases", []):
            up = _norm(alias)
            if len(up) < 2:
                continue
            exact = len(up) <= 4 and up.isascii()
            rules.append((up, item["group"], item.get("category", ""), exact))
    excludes = [_norm(k) for k in seed.get("exclude_keywords", []) if k]
    return rules, excludes


def match_holder(name: str, matchers) -> tuple:
    """返回 (group, category)；未命中或属境内公募产品返回 (None, None)。"""
    if not name:
        return None, None
    rules, excludes = matchers
    upper = _norm(name)
    if any(k in upper for k in excludes):
        return None, None
    for alias, group, category, exact in rules:
        if (upper == alias) if exact else (alias in upper):
            return group, category
    return None, None


def _fetch_latest(provider, ts_code: str, attempts: int = 4):
    """拉取某只股票十大流通股东的最新一期。

    该接口限流较严（HTTP 429），必须带指数退避重试，
    否则会静默漏掉整只股票的股东数据。
    返回 (latest_dict | None, error_str | None)。
    """
    last_err = None
    for i in range(attempts):
        try:
            rows = provider._extract_rows(provider._call(
                "stock_float_holders", stock_code=ts_code, page=1, page_size=20))
        except Exception as e:                      # noqa: BLE001
            last_err = str(e)[:120]
            time.sleep(1.2 * (2 ** i) + random.random())
            continue
        if not rows:
            return None, None
        return max(rows, key=lambda r: r.get("publish_date") or ""), None
    return None, last_err


def fetch_raw_holders(provider, stocks: list, errors: list | None = None) -> list:
    """并发抓取全部股票十大流通股东的**原始全量**（不做名单匹配）。

    返回 [(stock_code, report_date, rank, holder_raw, change_type,
           change_shares, shareholding, share_ratio, fetched_at), ...]
    匹配改为离线 rematch() 完成 —— 调整 QFII 名单时无需重新抓取。
    """
    def work(s):
        code6, ts_code = s["code"], s.get("ts_code") or ""
        if not ts_code:
            if errors is not None:
                errors.append((code6, "缺少 ts_code"))
            return []
        latest, err = _fetch_latest(provider, ts_code)
        if err:
            if errors is not None:
                errors.append((code6, err))
            return []
        if not latest:
            return []
        rd = latest.get("publish_date")
        out = []
        for h in (latest.get("fen_holders") or []):
            def f(v):
                try:
                    return float(v) if v not in (None, "") else None
                except (TypeError, ValueError):
                    return None
            out.append((code6, rd, h.get("rank"),
                        (h.get("shareholder_name") or "").strip(),
                        h.get("change_type") or "",
                        f(h.get("change_shares")), f(h.get("shareholding")),
                        f(h.get("share_ratio")), db.now_str()))
        return out

    rows = []
    with ThreadPoolExecutor(max_workers=HOLDER_WORKERS) as ex:
        for res in ex.map(work, stocks):
            rows.extend(res)
    return rows


def rematch(conn) -> dict:
    """按当前 QFII 名单，把 stock_float_holders_raw 重新匹配成 stock_holder_changes。

    完全离线（不访问 API），因此调整名单后秒级生效。
    """
    matchers = build_matchers()
    latest = db.latest_metrics(conn)
    close_map = {c: m.get("close_price", {}).get("metric_value")
                 for c, m in latest.items()}

    raw_rows = conn.execute(
        "SELECT stock_code, report_date, rank, holder_raw, change_type,"
        " change_shares, shareholding, share_ratio"
        " FROM stock_float_holders_raw").fetchall()

    records = []
    for r in raw_rows:
        group, category = match_holder(r["holder_raw"], matchers)
        if not group:
            continue
        close = close_map.get(r["stock_code"]) or 0
        chg = r["change_shares"] or 0
        hold = r["shareholding"] or 0
        ct = r["change_type"] or ""
        # 金额口径：增持/减持用变动股数；「新进」的变动股数接口常返回 0，
        # 改用期末持仓衡量建仓规模（否则新进永远算不出金额、显示为空）。
        base = hold if (ct == "新进" and not chg) else chg
        records.append((
            r["stock_code"], r["report_date"], group, category,
            r["holder_raw"], r["rank"], ct, chg,
            r["shareholding"], r["share_ratio"],
            abs(base) * close / 1e8 if close else None,
            r["report_date"], "FTShare:stock_float_holders", db.now_str()))

    conn.execute("DELETE FROM stock_holder_changes")
    conn.executemany(
        """INSERT INTO stock_holder_changes
           (stock_code, report_date, holder_group, holder_category, holder_raw,
            rank, change_type, change_shares, shareholding, share_ratio,
            est_amount, data_date, source, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", records)
    conn.commit()

    return {
        "records": len(records),
        "stocks": len({r[0] for r in records}),
        "groups": len({r[2] for r in records}),
        "increases": sum(1 for r in records if r[6] == "增持"),
    }


# ----------------------------------------------------------------------
# QFII 名录（证监会《合格境外投资者名录》）
# ----------------------------------------------------------------------
def load_qfii_registry() -> list:
    path = SEED_DIR / "qfii_registry.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("items", [])


def qfii_lookup(group_name: str, aliases=None) -> dict | None:
    """按分组名/别名在 QFII 名录中查证。

    返回名录条目（官方中文名 / 英文名 / 注册地 / 批准日期），未收录返回 None。
    命中规则取「完全相等」或「单向包含」，且要求名称足够长（中文≥6、英文≥8），
    避免短词误匹配。
    """
    reg = load_qfii_registry()
    if not reg:
        return None
    keys = [_norm(k) for k in ([group_name] + list(aliases or [])) if k]
    keys = [k for k in keys if len(k) >= 4]

    def index():
        return [(_norm(it.get("cn", "")), _norm(it.get("en", "")), it)
                for it in reg]

    idx = index()
    # 第一轮：完全相等（按别名顺序，别名表里代表性主体在前）
    for k in keys:
        for cn, en, it in idx:
            if k in (cn, en):
                return it
    # 第二轮：互为子串，取最长的匹配，避免短名"劫持"（如「三菱日联」抢到合资券商）
    best, best_score = None, 0
    for k in keys:
        for cn, en, it in idx:
            if cn and len(cn) >= 6 and (cn in k or k in cn):
                score = min(len(cn), len(k))
            elif en and len(en) >= 8 and (en in k or k in en):
                score = min(len(en), len(k))
            else:
                continue
            if score > best_score:
                best, best_score = it, score
    return best
