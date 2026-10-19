# -*- coding: utf-8 -*-
"""SQLite 数据访问层。

设计原则：
- stock_metrics 保留全部历史（每次更新插入新行，不覆盖），可追溯报告期/数据日期/来源。
- 行业分类多对多：stock_industries 关联表，一只股票可属于多个行业节点。
- 预留 industry_relationships 表，为未来 Industry Chain Map 扩展做准备（V1 不使用）。
"""
import os
import sqlite3
from datetime import datetime

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS stocks (
    stock_code  TEXT PRIMARY KEY,          -- 6位代码，如 600519
    ts_code     TEXT,                      -- 带后缀代码，如 600519.SH
    stock_name  TEXT,
    weight      REAL,                      -- 指数权重(%)
    in_csi300   INTEGER DEFAULT 1,         -- 1=在股票池（沪深300+创业板指+科创50）
    indices     TEXT,                      -- 所属指数标签，如 "沪深300|创业板指"
    sw_l1       TEXT,
    sw_l2       TEXT,
    sw_l3       TEXT,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS industries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    parent_id   INTEGER REFERENCES industries(id),
    node_type   TEXT DEFAULT 'sub',        -- 'group' | 'sub'
    sort_order  INTEGER DEFAULT 0,
    UNIQUE(name, parent_id)
);

CREATE TABLE IF NOT EXISTS stock_industries (
    stock_code  TEXT NOT NULL REFERENCES stocks(stock_code),
    industry_id INTEGER NOT NULL REFERENCES industries(id),
    PRIMARY KEY (stock_code, industry_id)
);

-- 指标历史表：不覆盖旧值，每次更新插入新行
CREATE TABLE IF NOT EXISTS stock_metrics (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code    TEXT NOT NULL,
    metric_name   TEXT NOT NULL,   -- market_cap / pe_ttm / close_price / np_yoy / ytd
    metric_value  REAL,
    report_period TEXT,            -- 财报期，如 2026H1（np_yoy 专用）
    data_date     TEXT,            -- 数据所属日期（交易日/披露日/计算日）
    source        TEXT,            -- 数据来源，如 FTShare:eastmoney_stock_valuation
    updated_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_metrics_code_name
    ON stock_metrics(stock_code, metric_name, data_date DESC);

-- 未来 Industry Chain Map 预留（V1 不写入）
CREATE TABLE IF NOT EXISTS industry_relationships (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_industry_id  INTEGER NOT NULL REFERENCES industries(id),
    target_industry_id  INTEGER NOT NULL REFERENCES industries(id),
    relationship_type   TEXT        -- upstream / downstream / substitute ...
);

-- 重要股东（十大流通股东中的外资/主权/资管机构）变动快照
CREATE TABLE IF NOT EXISTS stock_holder_changes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code      TEXT NOT NULL,
    report_date     TEXT,          -- 十大流通股东报告期
    holder_group    TEXT,          -- 归并后的重要股东名（如 高盛 / 香港中央结算）
    holder_category TEXT,          -- 外资投行 / 主权基金 / 外资资管 / 北向资金
    holder_raw      TEXT,          -- 原始股东名称
    rank            INTEGER,       -- 流通股东排名
    change_type     TEXT,          -- 增持 / 减持 / 不变 / 新进
    change_shares   REAL,          -- 变动股数（负=减持）
    shareholding    REAL,          -- 期末持股数
    share_ratio     REAL,          -- 持股占流通股比例(%)
    est_amount      REAL,          -- 估算变动金额（亿元，绝对值为准）
    data_date       TEXT,
    source          TEXT,
    updated_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_holder_code ON stock_holder_changes(stock_code);
CREATE INDEX IF NOT EXISTS idx_holder_group ON stock_holder_changes(holder_group);

-- 十大流通股东「原始」快照：保存全部股东（不只名单内的），
-- 用于离线按证监会 QFII 名录重新匹配，无需重新抓取 API。
CREATE TABLE IF NOT EXISTS stock_float_holders_raw (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code      TEXT NOT NULL,
    report_date     TEXT,
    rank            INTEGER,
    holder_raw      TEXT,
    change_type     TEXT,
    change_shares   REAL,
    shareholding    REAL,
    share_ratio     REAL,
    fetched_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_raw_code ON stock_float_holders_raw(stock_code);
CREATE INDEX IF NOT EXISTS idx_raw_name ON stock_float_holders_raw(holder_raw);

CREATE TABLE IF NOT EXISTS update_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT,
    finished_at TEXT,
    status      TEXT,              -- running / done / partial / failed
    steps       TEXT               -- JSON，各步骤状态
);
"""


def get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        # 旧库迁移：stocks 补 indices 列
        cols = {r[1] for r in conn.execute("PRAGMA table_info(stocks)")}
        if "indices" not in cols:
            conn.execute("ALTER TABLE stocks ADD COLUMN indices TEXT")
        conn.commit()
    finally:
        conn.close()


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def save_metric(conn, code: str, name: str, value, report_period=None,
                data_date=None, source=""):
    """插入一条指标记录（保留历史，不覆盖）"""
    conn.execute(
        "INSERT INTO stock_metrics (stock_code, metric_name, metric_value,"
        " report_period, data_date, source, updated_at) VALUES (?,?,?,?,?,?,?)",
        (code, name, value, report_period, data_date, source, now_str()),
    )


def latest_metrics(conn) -> dict:
    """返回 {stock_code: {metric_name: row_dict}}。

    排序规则（关键，曾导致界面停留在旧报告期）：
    - 带 report_period 的指标（np_yoy / np_momentum）：先按「报告期先后」排序，
      再按 data_date / id 兜底。绝不能只按 data_date —— 因为旧报告期的
      更正公告/补披露日期可能晚于新报告期，会把界面错误地拉回上一期。
      报告期排序键 = 年份*10 + 期次（Q1=1, H1=2, Q3=3, FY=4）。
    - 不带 report_period 的指标（市值/收盘价/PE/YTD 等）：仍按 data_date 最新。
    """
    rows = conn.execute(
        """
        SELECT stock_code, metric_name, metric_value, report_period,
               data_date, source, updated_at
        FROM (
            SELECT sm.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY stock_code, metric_name
                       ORDER BY
                         -- 报告期排序键：2026H1 -> 20262（数值越大越新）
                         CASE WHEN report_period IS NULL OR report_period = ''
                              THEN 0
                              ELSE CAST(SUBSTR(report_period, 1, 4) AS INTEGER) * 10
                                   + CASE SUBSTR(report_period, -2)
                                       WHEN 'Q1' THEN 1
                                       WHEN 'H1' THEN 2
                                       WHEN 'Q2' THEN 2
                                       WHEN 'Q3' THEN 3
                                       WHEN 'FY' THEN 4
                                       ELSE 0 END
                         END DESC,
                         data_date DESC, id DESC
                   ) AS rn
            FROM stock_metrics sm
        )
        WHERE rn = 1
        """
    ).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["stock_code"], {})[r["metric_name"]] = dict(r)
    return out


def upsert_stock(conn, code: str, ts_code: str, name: str, weight=None,
                 sw=None, indices: str | None = None):
    conn.execute(
        """
        INSERT INTO stocks (stock_code, ts_code, stock_name, weight,
                            in_csi300, indices, sw_l1, sw_l2, sw_l3, updated_at)
        VALUES (?,?,?,?,1,?,?,?,?,?)
        ON CONFLICT(stock_code) DO UPDATE SET
            ts_code=excluded.ts_code, stock_name=excluded.stock_name,
            weight=excluded.weight, in_csi300=1, indices=excluded.indices,
            sw_l1=COALESCE(excluded.sw_l1, stocks.sw_l1),
            sw_l2=COALESCE(excluded.sw_l2, stocks.sw_l2),
            sw_l3=COALESCE(excluded.sw_l3, stocks.sw_l3),
            updated_at=excluded.updated_at
        """,
        (code, ts_code, name, weight, indices,
         (sw or {}).get("l1"), (sw or {}).get("l2"), (sw or {}).get("l3"),
         now_str()),
    )
