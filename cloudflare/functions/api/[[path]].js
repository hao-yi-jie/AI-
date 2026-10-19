/**
 * rkstock 工作台 · 云端只读 API（Cloudflare Pages Functions + D1）
 *
 * 与本地 FastAPI 的读接口一一对应，逻辑尽量保持同构：
 *   GET  /api/stocks                  股票主表（支持 industry_id / q / holder / require_increase）
 *   GET  /api/important-shareholders  左侧重要股东列表（含 QFII 名录核验信息）
 *   GET  /api/industries              行业树
 *   GET  /api/version                 前端构建戳（用于旧标签页自愈刷新）
 *   GET  /api/update/last             最近一次更新记录
 *   GET  /api/update/status           更新状态（云端恒为未运行）
 *   POST /api/update                  云端不执行抓取，返回说明
 *
 * 数据由本地工作台在「更新数据」后推送到 D1（cloudflare/sync_to_d1.py）。
 */

const MIN_INCREASE_AMOUNT = 0.2;
const ADD_ACTIONS = ["增持", "新进"];
const CATEGORY_ORDER = ["北向资金", "港股托管", "主权基金", "外资投行",
  "外资资管", "其他外资机构", "其他QFII", "中资机构QFII"];

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json; charset=utf-8",
               "cache-control": "no-store" },
  });

const catRank = (c) => {
  const i = CATEGORY_ORDER.indexOf(c);
  return i < 0 ? CATEGORY_ORDER.length : i;
};

/** 最近一期指标：{stock_code: {metric_name: row}}
 *  排序与本地 db.latest_metrics 同构：带 report_period 的指标先按报告期先后排，
 *  再按 data_date / id 兜底（否则旧报告期的补披露会污染展示期）。 */
async function latestMetrics(DB) {
  const r = await DB.prepare(`
    SELECT stock_code, metric_name, metric_value, report_period, data_date
    FROM (
      SELECT sm.*, ROW_NUMBER() OVER (
               PARTITION BY stock_code, metric_name
               ORDER BY
                 CASE WHEN report_period IS NULL OR report_period = '' THEN 0
                      ELSE CAST(SUBSTR(report_period, 1, 4) AS INTEGER) * 10
                           + CASE SUBSTR(report_period, -2)
                               WHEN 'Q1' THEN 1 WHEN 'H1' THEN 2 WHEN 'Q2' THEN 2
                               WHEN 'Q3' THEN 3 WHEN 'FY' THEN 4 ELSE 0 END
                 END DESC,
                 data_date DESC, id DESC) AS rn
      FROM stock_metrics sm)
    WHERE rn = 1`).all();
  const out = {};
  for (const row of r.results) {
    (out[row.stock_code] ||= {})[row.metric_name] = row;
  }
  return out;
}

/** 加仓记录 + 该股出现过的全部重要股东 */
async function holderMaps(DB) {
  const r = await DB.prepare(
    `SELECT stock_code, holder_group, holder_category, change_type,
            est_amount, change_shares, holder_raw, rank, report_date
     FROM stock_holder_changes`).all();
  const map = {}, present = {};
  for (const x of r.results) {
    (present[x.stock_code] ||= new Set()).add(x.holder_group);
    if (!ADD_ACTIONS.includes(x.change_type)) continue;
    if ((x.est_amount || 0) < MIN_INCREASE_AMOUNT) continue;
    (map[x.stock_code] ||= []).push({
      group: x.holder_group, category: x.holder_category,
      action: x.change_type, amount: x.est_amount,
      shares: x.change_shares, raw: x.holder_raw, rank: x.rank,
      report_date: x.report_date,
    });
  }
  for (const k of Object.keys(map)) {
    map[k].sort((a, b) => (b.amount || 0) - (a.amount || 0));
  }
  return { map, present };
}

async function stocks(DB, url) {
  const industryId = url.searchParams.get("industry_id");
  const q = (url.searchParams.get("q") || "").trim().toLowerCase();
  const holder = url.searchParams.get("holder");
  const requireIncrease = url.searchParams.get("require_increase") === "true";

  const jobs = [
    DB.prepare("SELECT stock_code, ts_code, stock_name, weight FROM stocks WHERE in_csi300=1").all(),
    latestMetrics(DB),
    holderMaps(DB),
    DB.prepare(`SELECT si.stock_code, g.name AS gname, s.name AS sname
                FROM stock_industries si
                JOIN industries s ON s.id = si.industry_id
                LEFT JOIN industries g ON g.id = s.parent_id`).all(),
  ];
  if (industryId) {
    jobs.push(DB.prepare("SELECT id FROM industries WHERE parent_id=?")
      .bind(Number(industryId)).all());
  }
  if (holder) {
    jobs.push(DB.prepare("SELECT DISTINCT stock_code FROM stock_holder_changes WHERE holder_group=?")
      .bind(holder).all());
  }
  const [stockRes, metrics, { map: holderMap0, present }, indRes, ...extra] = await Promise.all(jobs);

  let codesFilter = null;
  let idx = 0;
  if (industryId) {
    const ids = [Number(industryId), ...extra[idx++].results.map((k) => k.id)];
    const marks = ids.map(() => "?").join(",");
    const r = await DB.prepare(
      `SELECT DISTINCT stock_code FROM stock_industries WHERE industry_id IN (${marks})`)
      .bind(...ids).all();
    codesFilter = new Set(r.results.map((x) => x.stock_code));
  }
  if (holder) {
    const s = new Set(extra[idx++].results.map((x) => x.stock_code));
    codesFilter = codesFilter
      ? new Set([...codesFilter].filter((x) => s.has(x))) : s;
  }

  // 指定股东时，只保留该股东自己的加仓记录（与本地口径一致）
  let holderMap = holderMap0;
  if (holder) {
    const scoped = {};
    for (const [k, v] of Object.entries(holderMap0)) {
      const f = v.filter((h) => h.group === holder);
      if (f.length) scoped[k] = f;
    }
    holderMap = scoped;
  }

  const indMap = {};
  for (const r of indRes.results) {
    const label = r.gname ? `${r.gname}·${r.sname}` : r.sname;
    (indMap[r.stock_code] ||= []).push(label);
  }

  const rows = [];
  for (const s of stockRes.results) {
    if (codesFilter && !codesFilter.has(s.stock_code)) continue;
    if (q && !s.stock_code.toLowerCase().includes(q) &&
        !(s.stock_name || "").toLowerCase().includes(q)) continue;
    if (requireIncrease && !holderMap[s.stock_code]) continue;
    const m = metrics[s.stock_code] || {};
    const np = m.np_yoy || {};
    rows.push({
      code: s.stock_code,
      name: s.stock_name,
      weight: s.weight,
      industries: indMap[s.stock_code] || [],
      market_cap: (m.market_cap || {}).metric_value ?? null,
      close: (m.close_price || {}).metric_value ?? null,
      pe_ttm: (m.pe_ttm || {}).metric_value ?? null,
      np_yoy: np.metric_value ?? null,
      report_period: np.report_period ?? null,
      publish_date: np.data_date ?? null,
      np_trend: (m.np_momentum || {}).metric_value === 1 ? "改善"
        : (m.np_momentum || {}).metric_value === 0 ? "放缓" : null,
      ytd: (m.ytd || {}).metric_value ?? null,
      holders: holderMap[s.stock_code] || [],
      holder_groups: [...(present[s.stock_code] || [])].sort(),
    });
  }
  rows.sort((a, b) => (b.market_cap || 0) - (a.market_cap || 0));
  return json({ rows, count: rows.length });
}

async function importantShareholders(DB) {
  const [aggRes, metaRes, regRes] = await Promise.all([
    DB.prepare(`SELECT holder_group g, holder_category cat, stock_code s,
                       change_type t, SUM(COALESCE(est_amount,0)) amount
                FROM stock_holder_changes
                GROUP BY holder_group, holder_category, stock_code, change_type`).all(),
    DB.prepare("SELECT * FROM holder_meta").all(),
    DB.prepare("SELECT v FROM sync_meta WHERE k='qfii_registry_count'").all(),
  ]);
  const meta = {};
  for (const m of metaRes.results) meta[m.holder_group] = m;

  const agg = {};
  for (const r of aggRes.results) {
    const a = (agg[r.g] ||= { group: r.g, category: r.cat,
                              stocks: new Set(), increases: new Set(), amount: 0 });
    a.stocks.add(r.s);
    if (ADD_ACTIONS.includes(r.t) && (r.amount || 0) >= MIN_INCREASE_AMOUNT) {
      a.increases.add(r.s);
      a.amount += r.amount || 0;
    }
  }
  const out = [];
  for (const v of Object.values(agg)) {
    if (!v.stocks.size) continue;
    const m = meta[v.group] || {};
    out.push({
      group: v.group,
      category: v.category,
      stocks: v.stocks.size,
      increases: v.increases.size,
      amount: Math.round(v.amount * 10) / 10,
      qfii: m.qfii_cn ? { cn: m.qfii_cn, en: m.qfii_en,
                          region: m.qfii_region, approved: m.qfii_approved } : null,
    });
  }
  out.sort((a, b) => catRank(a.category) - catRank(b.category) ||
                     b.stocks - a.stocks || a.group.localeCompare(b.group));
  const regCount = Number((regRes.results[0] || {}).v || 0);
  return json({ shareholders: out, total: out.length,
                min_increase: MIN_INCREASE_AMOUNT,
                qfii_registry_count: regCount });
}

async function industries(DB) {
  const [nodeRes, directRes] = await Promise.all([
    DB.prepare(`SELECT id, name, parent_id, node_type, sort_order FROM industries
                ORDER BY sort_order, id`).all(),
    DB.prepare("SELECT industry_id, COUNT(*) c FROM stock_industries GROUP BY industry_id").all(),
  ]);
  const direct = {};
  for (const r of directRes.results) direct[r.industry_id] = r.c;
  const byId = {};
  for (const n of nodeRes.results) {
    byId[n.id] = { ...n, count: direct[n.id] || 0, children: [] };
  }
  const tree = [];
  for (const n of Object.values(byId).sort((a, b) => a.sort_order - b.sort_order)) {
    if (n.parent_id && byId[n.parent_id]) byId[n.parent_id].children.push(n);
    else tree.push(n);
  }
  for (const g of tree) {
    const subIds = g.children.map((c) => c.id);
    if (subIds.length) {
      const marks = subIds.map(() => "?").join(",");
      const r = await DB.prepare(
        `SELECT COUNT(DISTINCT stock_code) c FROM stock_industries
         WHERE industry_id IN (${marks})`).bind(...subIds).first();
      g.count = r ? r.c : 0;
    }
  }
  return json({ tree });
}

export async function onRequest(context) {
  const { request, env } = context;
  const DB = env.DB;
  const url = new URL(request.url);
  const path = url.pathname.replace(/^\/api\/?/, "").replace(/\/$/, "");
  if (!DB) return json({ error: "D1 绑定缺失（env.DB）" }, 500);

  try {
    if (request.method === "POST") {
      if (path === "update") {
        return json({
          ok: false, cloud: true,
          message: "云端为只读副本。数据抓取在本地工作台执行，" +
                   "点本地「更新数据」完成后会自动同步到这里（免费 D1）。",
        }, 200);
      }
      return json({ error: "method not allowed" }, 405);
    }
    switch (path) {
      case "":
      case "stocks":
        return await stocks(DB, url);
      case "important-shareholders":
        return await importantShareholders(DB);
      case "industries":
        return await industries(DB);
      case "version": {
        const r = await DB.prepare("SELECT v FROM sync_meta WHERE k='build'").first();
        return json({ build: (r && r.v) || "", syncedAt: await syncedAt(DB) });
      }
      case "update/status":
        return json({ running: false, overall: "done", steps: [], cloud: true });
      case "update/last": {
        const r = await DB.prepare(
          `SELECT * FROM update_runs WHERE status != 'running'
           ORDER BY id DESC LIMIT 1`).first();
        return json(r || null);
      }
      default:
        return json({ error: "not found", path }, 404);
    }
  } catch (e) {
    return json({ error: String((e && e.message) || e) }, 500);
  }
}

async function syncedAt(DB) {
  const r = await DB.prepare("SELECT v FROM sync_meta WHERE k='synced_at'").first();
  return (r && r.v) || "";
}
