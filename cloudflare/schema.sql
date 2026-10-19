-- rkstock 工作台 · Cloudflare D1 结构（与本地 SQLite 保持一致）
CREATE TABLE IF NOT EXISTS stocks (
    stock_code  TEXT PRIMARY KEY,
    ts_code     TEXT,
    stock_name  TEXT,
    weight      REAL,
    in_csi300   INTEGER DEFAULT 1,
    indices     TEXT,
    sw_l1       TEXT,
    sw_l2       TEXT,
    sw_l3       TEXT,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS industries (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    parent_id   INTEGER,
    node_type   TEXT DEFAULT 'sub',
    sort_order  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS stock_industries (
    stock_code  TEXT NOT NULL,
    industry_id INTEGER NOT NULL,
    PRIMARY KEY (stock_code, industry_id)
);

CREATE TABLE IF NOT EXISTS stock_metrics (
    id            INTEGER PRIMARY KEY,
    stock_code    TEXT NOT NULL,
    metric_name   TEXT NOT NULL,
    metric_value  REAL,
    report_period TEXT,
    data_date     TEXT,
    source        TEXT,
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS stock_holder_changes (
    id              INTEGER PRIMARY KEY,
    stock_code      TEXT NOT NULL,
    report_date     TEXT,
    holder_group    TEXT,
    holder_category TEXT,
    holder_raw      TEXT,
    rank            INTEGER,
    change_type     TEXT,
    change_shares   REAL,
    shareholding    REAL,
    share_ratio     REAL,
    est_amount      REAL,
    data_date       TEXT,
    source          TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS stock_float_holders_raw (
    id              INTEGER PRIMARY KEY,
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

CREATE TABLE IF NOT EXISTS update_runs (
    id          INTEGER PRIMARY KEY,
    started_at  TEXT,
    finished_at TEXT,
    status      TEXT,
    steps       TEXT
);

-- 云端元信息：构建戳、最近同步时间等
CREATE TABLE IF NOT EXISTS sync_meta (
    k TEXT PRIMARY KEY,
    v TEXT
);

-- 股东元信息：本地用 QFII 名录预先算好（官方中英文名/注册地），
-- 云端直接查表展示，避免把 168KB 名录打进函数包。
CREATE TABLE IF NOT EXISTS holder_meta (
    holder_group  TEXT PRIMARY KEY,
    category      TEXT,
    qfii_cn       TEXT,
    qfii_en       TEXT,
    qfii_region   TEXT,
    qfii_approved TEXT
);

CREATE INDEX IF NOT EXISTS idx_metrics_code ON stock_metrics(stock_code);
CREATE INDEX IF NOT EXISTS idx_metrics_name ON stock_metrics(metric_name);
CREATE INDEX IF NOT EXISTS idx_holder_code  ON stock_holder_changes(stock_code);
CREATE INDEX IF NOT EXISTS idx_holder_group ON stock_holder_changes(holder_group);
CREATE INDEX IF NOT EXISTS idx_si_code      ON stock_industries(stock_code);
CREATE INDEX IF NOT EXISTS idx_raw_code     ON stock_float_holders_raw(stock_code);
