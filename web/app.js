/* CSI 300 Industry Intelligence —— 前端逻辑 */
"use strict";

const fmt = {
  cap(v) {                       // 元 -> 亿（整数，无小数）
    if (v == null) return null;
    return (v / 1e8).toLocaleString("zh-CN", { maximumFractionDigits: 0 });
  },
  pct(v) {                       // 百分数，保留两位（YTD 等使用）
    if (v == null) return null;
    const s = v > 0 ? "+" : "";
    return s + v.toFixed(2) + "%";
  },
  pct0(v) {                      // 百分数，四舍五入到个位（归母净利同比使用）
    if (v == null) return null;
    const s = v > 0 ? "+" : "";
    return s + Math.round(v) + "%";
  },
  pe(v) {
    if (v == null) return null;
    if (v <= 0) return "亏损";    // 负 PE / 零 -> 亏损，不是估值
    return v.toFixed(1) + "x";
  },
  period(v) {                    // 2026H1 -> 2026中报；2026Q3 -> 2026三季报
    if (!v) return null;
    const m = String(v).match(/^(\d{4})(.+)$/);
    if (!m) return v;
    const label = { Q1: "一季报", H1: "中报", Q2: "中报",
                    Q3: "三季报", FY: "年报" }[m[2]] || m[2];
    return m[1] + label;
  },
};

const columnDefs = [
  {
    headerName: "代码", field: "code", width: 92, pinned: "left",
    cellClass: "col-code", sortable: true, filter: false, suppressMovable: true,
  },
  {
    headerName: "公司", field: "name", width: 110, pinned: "left",
    cellClass: "col-name", sortable: true, filter: false, suppressMovable: true,
    tooltipField: "name",
  },
  {
    headerName: "行业", field: "industries", width: 190, sortable: false, filter: false,
    tooltipValueGetter: p => (p.value || []).join(" / "),
    cellRenderer: p => (p.value || []).slice(0, 2)
      .map(t => `<span class="ind-tag">${t}</span>`).join("") +
      ((p.value || []).length > 2 ? `<span class="report-tag">+${p.value.length - 2}</span>` : ""),
  },
  {
    headerName: "市值(亿)", field: "market_cap", width: 118, type: "rightAligned",
    valueGetter: p => p.data.market_cap,
    valueFormatter: p => fmt.cap(p.value),
    sortable: true, filter: false,
    headerTooltip: "最新总市值（人民币）",
  },
  {
    headerName: "归母净利YoY", field: "np_yoy", width: 124, type: "rightAligned",
    valueGetter: p => p.data.np_yoy,
    valueFormatter: p => fmt.pct0(p.value),
    cellClassRules: {
      "cell-up": p => p.value > 0,
      "cell-down": p => p.value < 0,
      "cell-dash": p => p.value == null,
    },
    sortable: true, filter: false,
    headerTooltip: "最新已披露财报归母净利润同比增长率",
  },
  {
    headerName: "业绩变化", field: "np_trend", width: 84,
    valueGetter: p => p.data.np_trend,
    valueFormatter: p => p.value == null ? "—" : p.value,
    cellClassRules: {
      "cell-improve": p => p.value === "改善",
      "cell-slow": p => p.value === "放缓",
      "cell-dash": p => p.value == null,
    },
    sortable: true, filter: false,
    headerTooltip: "最新累计期归母净利同比 vs 前一期累计同比：边际加快=改善；放缓=放缓。当年仅Q1时按Q1同比正负判断",
  },
  {
    headerName: "报告期", field: "report_period", width: 96,
    cellClass: "report-tag", sortable: false, filter: false,
    valueFormatter: p => fmt.period(p.value),
    tooltipValueGetter: p =>
      `披露日 ${p.data.publish_date || "-"}`,
    headerTooltip: "归母净利同比对应的财报期（悬浮显示披露日）",
  },
  {
    headerName: "PE TTM", field: "pe_ttm", width: 100, type: "rightAligned",
    valueGetter: p => p.data.pe_ttm,
    valueFormatter: p => fmt.pe(p.value),
    cellClassRules: {
      "cell-loss": p => p.value != null && p.value <= 0,
      "cell-dash": p => p.value == null,
    },
    sortable: true, filter: false,
    headerTooltip: "PE = 总市值 ÷ 年化归母净利；年化 = 当年已披露季度累计归母净利 ÷ 已披露季度数 × 4（当年无财报用上年年报，即静态 PE）；净利为负显示「亏损」",
  },
  {
    headerName: "YTD", field: "ytd", width: 96, type: "rightAligned",
    valueGetter: p => p.data.ytd,
    valueFormatter: p => fmt.pct(p.value),
    cellClassRules: {
      "cell-up": p => p.value > 0,
      "cell-down": p => p.value < 0,
      "cell-dash": p => p.value == null,
    },
    sortable: true, filter: false,
    headerTooltip: "年初至今涨跌幅 = 最新收盘 / 当年首个交易日收盘(前复权) - 1",
  },
];

const gridOptions = {
  columnDefs,
  defaultColDef: {
    resizable: true,
    suppressHeaderMenuButton: true,
  },
  rowData: [],
  animateRows: false,
  rowSelection: "single",
  headerHeight: 34,
  tooltipShowDelay: 300,
  localeText: { noRowsToShow: "暂无数据，请点击右上角「更新数据」" },
};

/* ---------------- 重要股东监控页（B） ---------------- */
const holderColumnDefs = [
  {
    headerName: "代码", field: "code", width: 92, pinned: "left",
    cellClass: "col-code", sortable: true, filter: false, suppressMovable: true,
  },
  {
    headerName: "公司", field: "name", width: 110, pinned: "left",
    cellClass: "col-name", sortable: true, filter: false, suppressMovable: true,
    tooltipField: "name",
  },
  {
    headerName: "重要股东增持", field: "holder_amount", width: 190,
    autoHeight: true,
    cellClass: "cell-holders",
    // 服务端已按「选中股东」收窄内容，这里直接渲染即可
    valueGetter: p => (p.data.holders || [])
      .reduce((s, h) => s + (h.amount || 0), 0),
    cellRenderer: p => {
      const list = p.data.holders || [];
      if (!list.length) return `<span class="cell-dash">—</span>`;
      return list.map(h =>
        `<div class="holder-line${h.action === "新进" ? " holder-new" : ""}">` +
        `${h.group}${h.action}` +
        `${h.amount != null ? h.amount.toFixed(1) + "亿" : ""}</div>`).join("");
    },
    tooltipValueGetter: p => (p.data.holders || []).map(h =>
      `${h.group}（${h.raw}）${h.action} 排名${h.rank} 持股${(h.shares/1e4).toFixed(0)}万股`).join("\n"),
    sortable: true, sort: "desc", filter: false,
    headerTooltip: "十大流通股东中的重要股东加仓（增持/新进，仅显示金额≥2000万；减持不显示）。"
      + "金额按最新收盘价估算；「新进」以建仓市值计量。点击列头按金额排序",
  },
  {
    headerName: "行业", field: "industries", width: 150, sortable: false, filter: false,
    tooltipValueGetter: p => (p.value || []).join(" / "),
    cellRenderer: p => (p.value || []).map(t => `<span class="ind-tag">${t}</span>`).join(""),
  },
  {
    headerName: "市值(亿)", field: "market_cap", width: 100, type: "rightAligned",
    valueGetter: p => p.data.market_cap,
    valueFormatter: p => fmt.cap(p.value),
    sortable: true, filter: false,
  },
  {
    headerName: "归母净利", field: "np_yoy", width: 108, type: "rightAligned",
    valueGetter: p => p.data.np_yoy,
    valueFormatter: p => fmt.pct0(p.value),
    cellClassRules: {
      "cell-up": p => p.value > 0,
      "cell-down": p => p.value < 0,
      "cell-dash": p => p.value == null,
    },
    sortable: true, filter: false,
  },
  {
    headerName: "业绩变化", field: "np_trend", width: 80,
    valueGetter: p => p.data.np_trend,
    valueFormatter: p => p.value == null ? "—" : p.value,
    cellClassRules: {
      "cell-improve": p => p.value === "改善",
      "cell-slow": p => p.value === "放缓",
      "cell-dash": p => p.value == null,
    },
    sortable: true, filter: false,
  },
  {
    headerName: "报告期", field: "report_period", width: 88,
    cellClass: "report-tag", sortable: false, filter: false,
    valueFormatter: p => fmt.period(p.value),
    tooltipValueGetter: p => `披露日 ${p.data.publish_date || "-"}`,
  },
  {
    headerName: "PE TTM", field: "pe_ttm", width: 92, type: "rightAligned",
    valueGetter: p => p.data.pe_ttm,
    valueFormatter: p => fmt.pe(p.value),
    cellClassRules: {
      "cell-loss": p => p.value != null && p.value <= 0,
      "cell-dash": p => p.value == null,
    },
    sortable: true, filter: false,
  },
  {
    headerName: "YTD", field: "ytd", width: 88, type: "rightAligned",
    valueGetter: p => p.data.ytd,
    valueFormatter: p => fmt.pct(p.value),
    cellClassRules: {
      "cell-up": p => p.value > 0,
      "cell-down": p => p.value < 0,
      "cell-dash": p => p.value == null,
    },
    sortable: true, filter: false,
  },
];

const holderGridOptions = {
  columnDefs: holderColumnDefs,
  defaultColDef: { resizable: true, suppressHeaderMenuButton: true },
  rowData: [],
  animateRows: false,
  rowSelection: "single",
  headerHeight: 34,
  tooltipShowDelay: 300,
  localeText: { noRowsToShow: "暂无数据，请点击右上角「更新数据」" },
};

let currentIndustry = null;   // null = 全部
let gridApi = null;           // AG Grid v31+：api 只能从 createGrid 返回值获取
let holderGridApi = null;     // 重要股东页表格 api（首次切换时懒初始化）
let currentHolder = null;     // 选中的重要股东
let holderListCache = [];
let holderRegistryCount = 0;  // QFII 名录总家数

// 本地 = 可抓取更新；cloud = Cloudflare 上的只读副本（数据由本地同步上来）
const CLOUD = (document.querySelector('meta[name="rk-mode"]') || {}).content === "cloud";

// 界面构建版本：由 index.html 注入（= web 目录最新修改时间）。
// 显示出来，便于一眼确认浏览器跑的是不是最新代码。
const BUILD = (function () {
  const s = document.querySelector('script[src*="app.js?v="]');
  return s && s.src.includes("?v=") ? s.src.split("?v=")[1] : "";
})();

// 旧标签页自愈：页面可能已经开了很久，里面的 JS 是旧的（后端早就修好了）。
// 切回前台 / 获得焦点 / 定时轮询时比对后端构建版本，不一致就自动刷新。
(function autoReloadOnUpdate() {
  if (!BUILD) return;
  let reloading = false;
  async function check() {
    if (reloading || document.hidden) return;
    try {
      const r = await fetch("/api/version", { cache: "no-store" });
      const d = await r.json();
      if (d.build && d.build !== BUILD) {
        reloading = true;
        const el = document.getElementById("ui-build");
        if (el) el.textContent = "界面已更新，正在刷新…";
        setTimeout(() => location.reload(), 400);
      }
    } catch (e) { /* 忽略：离线时不打扰 */ }
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) check(); });
  window.addEventListener("focus", check);
  setInterval(check, 60000);
})();

document.addEventListener("DOMContentLoaded", () => {
  const el = document.getElementById("ui-build");
  if (el) el.textContent = BUILD ? "界面 " + BUILD : "";
  if (CLOUD) applyCloudMode();
});

/** 云端只读模式：禁用「更新数据」，改为显示数据同步时间 */
function applyCloudMode() {
  const btn = document.getElementById("btn-update");
  if (btn) {
    btn.disabled = true;
    btn.classList.remove("spinning");
    btn.title = "云端为只读副本：数据由本地工作台点「更新数据」后自动同步到这里（免费 D1）";
    btn.innerHTML = `<span class="icon">&#9729;</span> 云端只读`;
  }
  const panel = document.getElementById("update-panel");
  if (panel) panel.classList.add("hidden");
  fetch("/api/version").then(r => r.json()).then(d => {
    if (d && d.syncedAt) {
      const t = document.getElementById("last-updated");
      if (t) t.textContent = "数据同步 " + d.syncedAt;
    }
  }).catch(() => { /* 忽略 */ });
}

document.addEventListener("DOMContentLoaded", () => {
  const gridDiv = document.getElementById("stock-grid");
  gridApi = agGrid.createGrid(gridDiv, gridOptions);

  document.getElementById("btn-update").addEventListener("click", triggerUpdate);
  document.getElementById("btn-close-panel").addEventListener("click", () => {
    document.getElementById("update-panel").classList.add("hidden");
  });
  document.getElementById("quick-filter").addEventListener("input", e => {
    gridApi.setQuickFilter(e.target.value.trim());
  });
  document.getElementById("holder-filter").addEventListener("input", e => {
    renderHolderList(holderListCache, e.target.value.trim());
  });
  document.querySelectorAll("#tabs .tab").forEach(btn => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  loadIndustries();
  loadStocks();
  showLastUpdate();

  // 支持 #holders 直达重要股东页（可加书签）
  if (location.hash === "#holders") switchTab("holders");
});

/* ---------------- Tab 切换 ---------------- */
function switchTab(tab) {
  document.querySelectorAll("#tabs .tab").forEach(b =>
    b.classList.toggle("active", b.dataset.tab === tab));
  const isPerf = tab === "performance";
  document.getElementById("layout").classList.toggle("hidden", !isPerf);
  document.getElementById("holder-layout").classList.toggle("hidden", isPerf);
  if (!isPerf && !holderGridApi) {
    // 容器可见后再初始化，避免宽度为 0
    holderGridApi = agGrid.createGrid(
      document.getElementById("holder-grid"), holderGridOptions);
    loadHolderList();
    loadHolderStocks();
  } else if (!isPerf) {
    loadHolderList();
    loadHolderStocks();
  }
  // 通知 AG Grid 重新计算尺寸（容器显示/隐藏后）
  setTimeout(() => window.dispatchEvent(new Event("resize")), 30);
}

/* ---------------- 重要股东页数据 ---------------- */
async function loadHolderList() {
  const res = await fetch("/api/important-shareholders");
  const data = await res.json();
  holderListCache = data.shareholders || [];
  holderRegistryCount = data.qfii_registry_count || 0;
  renderHolderList(holderListCache, document.getElementById("holder-filter").value.trim());
}

function renderHolderList(list, keyword) {
  const nav = document.getElementById("holder-list");
  nav.innerHTML = "";
  const all = document.createElement("div");
  all.className = "tree-group" + (currentHolder == null ? " active" : "");
  all.innerHTML = `<span style="flex:1">全部重要股东</span>`;
  all.addEventListener("click", () => selectHolder(null, "全部重要股东", all));
  nav.appendChild(all);

  const kw = (keyword || "").toUpperCase();
  // 只列出「本期有合格加仓（增持/新进≥2000万）」的股东 —— 与主表口径一致：
  // 点任何一个都必有数据，不会出现"有持仓但表里是空的"。
  const hidden = list.filter(h => !h.increases).length;
  const shown = list.filter(h => h.increases > 0 &&
    (!kw || h.group.toUpperCase().includes(kw) ||
     (h.category || "").toUpperCase().includes(kw)));

  // 按类别分组 → 可折叠（点击类别标题展开/收起）
  const cats = [];
  shown.forEach(h => {
    const c = h.category || "其他";
    let g = cats.find(x => x.name === c);
    if (!g) { g = { name: c, items: [] }; cats.push(g); }
    g.items.push(h);
  });

  cats.forEach(cat => {
    const sec = document.createElement("div");
    sec.className = "holder-cat-section";

    const head = document.createElement("div");
    head.className = "holder-cat" + (cat.collapsed ? " collapsed" : "");
    head.innerHTML = `<span class="cat-caret">▾</span>` +
      `<span style="flex:1">${cat.name}</span>` +
      `<span class="tree-count">${cat.items.length}</span>`;
    head.addEventListener("click", () => {
      sec.classList.toggle("collapsed");
      head.classList.toggle("collapsed");
    });
    sec.appendChild(head);

    const box = document.createElement("div");
    box.className = "holder-cat-items";
    cat.items.forEach(h => {
      const el = document.createElement("div");
      el.className = "tree-sub holder-item" + (currentHolder === h.group ? " active" : "");
      // 主数字 = 合格加仓家数（与点击后表格行数一致）
      el.innerHTML = `<span style="flex:1">${h.group}</span>` +
        `<span class="tree-count">${h.increases}</span>`;
      const q = h.qfii
        ? `QFII 名录：${h.qfii.cn}${h.qfii.en ? " | " + h.qfii.en : ""}` +
          `${h.qfii.region ? "（" + h.qfii.region + "）" : ""}`
        : "跨境通道（非 QFII 名录主体）";
      el.title = `${h.group}：持有 ${h.stocks} 只样本股（十大流通股东），` +
        `其中 ${h.increases} 只本期为增持/新进且金额≥2000万，` +
        `合计约 ${h.amount} 亿元\n${q}`;
      el.addEventListener("click", () => selectHolder(h.group, h.group, el));
      box.appendChild(el);
    });
    sec.appendChild(box);
    nav.appendChild(sec);
  });

  // 底部说明：名录规模 / 实际持有样本股 / 本期无加仓被隐藏的家数
  const foot = document.createElement("div");
  foot.className = "holder-foot";
  const inReg = list.filter(h => h.qfii).length;
  const chans = list.length - inReg;
  foot.textContent =
    `QFII 名录 ${holderRegistryCount} 家 → 持有本样本股 ${inReg} 家` +
    (chans ? `（另有 ${chans} 个跨境通道）` : "") +
    (hidden ? `；${hidden} 家本期仅减持/持仓未变，未列出` : "");
  nav.appendChild(foot);
}

function selectHolder(group, label, el) {
  currentHolder = group;
  document.querySelectorAll("#holder-list .active").forEach(n => n.classList.remove("active"));
  el.classList.add("active");
  document.getElementById("holder-view").textContent = label;
  loadHolderStocks();
}

async function loadHolderStocks() {
  // 筛选全部交给服务端，前端直接渲染，避免前后端口径不一致。
  // require_increase=true：只保留存在「合格加仓（增持/新进 ≥2000万）」的公司；
  //   选中某股东时，服务端还会把范围收窄到"该股东自己的加仓记录"，
  //   因此表格里不会出现持仓未变 / 减持 / 金额不足的空行。
  let url = "/api/stocks?require_increase=true";
  if (currentHolder) url += `&holder=${encodeURIComponent(currentHolder)}`;
  const res = await fetch(url);
  const data = await res.json();
  const rows = data.rows || [];
  holderGridApi.setGridOption("rowData", rows);
  document.getElementById("holder-count").textContent = currentHolder
    ? `${rows.length} 家加仓`
    : `${rows.length} 家公司`;
  // 默认按增持金额从高到低排序
  holderGridApi.applyColumnState({
    state: [{ colId: "holder_amount", sort: "desc" }], defaultState: { sort: null },
  });
}

/* ---------------- 数据加载 ---------------- */
async function loadIndustries() {
  const res = await fetch("/api/industries");
  const data = await res.json();
  renderTree(data.tree);
  const total = data.tree.reduce((s, g) => s + (g.count || 0), 0);
  document.getElementById("sidebar-foot").textContent =
    `自定义分类体系 · 可编辑 seed/industries.json`;
}

function renderTree(tree) {
  const nav = document.getElementById("industry-tree");
  nav.innerHTML = "";

  const all = document.createElement("div");
  all.className = "tree-group active";
  all.innerHTML = `<span class="tree-caret" style="visibility:hidden">▼</span><span>全部股票池</span>`;
  all.querySelector(".tree-caret").style.visibility = "hidden";
  all.addEventListener("click", () => selectNode(null, "全部股票池", all));
  nav.appendChild(all);

  tree.forEach(group => {
    const gEl = document.createElement("div");
    gEl.className = "tree-group";
    gEl.innerHTML = `<span class="tree-caret">▼</span><span style="flex:1">${group.name}</span><span class="tree-count">${group.count}</span>`;
    const childrenWrap = document.createElement("div");
    childrenWrap.className = "tree-children";

    gEl.addEventListener("click", e => {
      if (e.target.classList.contains("tree-caret")) {
        gEl.classList.toggle("collapsed");
        childrenWrap.classList.toggle("collapsed");
        return;
      }
      selectNode(group.id, group.name, gEl);
    });
    gEl.addEventListener("dblclick", () => {
      gEl.classList.toggle("collapsed");
      childrenWrap.classList.toggle("collapsed");
    });

    (group.children || []).forEach(sub => {
      const sEl = document.createElement("div");
      sEl.className = "tree-sub";
      sEl.innerHTML = `<span style="flex:1">${sub.name}</span><span class="tree-count">${sub.count}</span>`;
      sEl.addEventListener("click", () => selectNode(sub.id, sub.name, sEl));
      childrenWrap.appendChild(sEl);
    });

    nav.appendChild(gEl);
    nav.appendChild(childrenWrap);
  });
}

function selectNode(id, label, el) {
  currentIndustry = id;
  document.querySelectorAll(".tree-node").forEach(n => n.classList.remove("active"));
  document.querySelectorAll(".tree-group, .tree-sub").forEach(n => n.classList.remove("active"));
  el.classList.add("active");
  document.getElementById("current-view").textContent = label;
  loadStocks();
}

async function loadStocks() {
  let url = "/api/stocks";
  if (currentIndustry != null) url += `?industry_id=${currentIndustry}`;
  const res = await fetch(url);
  const data = await res.json();
  gridApi.setGridOption("rowData", data.rows);
  document.getElementById("view-count").textContent = `${data.count} 家公司`;
}

async function showLastUpdate() {
  try {
    const res = await fetch("/api/update/last");
    const run = await res.json();
    if (run && run.finished_at) {
      document.getElementById("last-updated").textContent = "Last Updated: " + run.finished_at;
    }
  } catch (e) { /* ignore */ }
}

/* ---------------- 更新流程 ---------------- */
let pollTimer = null;

async function triggerUpdate() {
  if (CLOUD) {
    alert("这里是云端的只读副本。\n\n数据抓取在本地工作台执行，"
      + "点本地页面的「更新数据」完成后会自动同步到这里。");
    return;
  }
  const btn = document.getElementById("btn-update");
  try {
    const res = await fetch("/api/update", { method: "POST" });
    if (res.status === 409) { /* 已在运行，直接进入轮询 */ }
    else if (!res.ok) { alert("触发更新失败"); return; }
  } catch (e) { alert("无法连接后端服务"); return; }

  btn.disabled = true;
  btn.classList.add("spinning");
  document.getElementById("update-panel").classList.remove("hidden");
  document.getElementById("update-title").textContent = "正在更新数据...";
  pollTimer = setInterval(pollStatus, 1000);
  pollStatus();
}

async function pollStatus() {
  const res = await fetch("/api/update/status");
  const st = await res.json();
  renderSteps(st);

  if (!st.running) {
    clearInterval(pollTimer);
    pollTimer = null;
    const btn = document.getElementById("btn-update");
    btn.disabled = false;
    btn.classList.remove("spinning");
    const done = st.overall === "done";
    document.getElementById("update-title").textContent =
      done ? "更新完成" : (st.overall === "failed" ? "更新失败" : "更新完成（部分步骤失败）");
    if (st.finished_at) {
      document.getElementById("last-updated").textContent = "Last Updated: " + st.finished_at;
    }
    loadIndustries();
    loadStocks();
    if (holderGridApi) {   // 重要股东页已初始化则同步刷新
      loadHolderList();
      loadHolderStocks();
    }
  }
}

function renderSteps(st) {
  const ul = document.getElementById("update-steps");
  ul.innerHTML = "";
  (st.steps || []).forEach(s => {
    const li = document.createElement("li");
    li.className = s.status === "ok" ? "ok" : s.status === "failed" ? "fail"
      : s.status === "running" ? "run" : "pend";
    const mark = { ok: "✓", failed: "✗", running: "…", pending: "·",
                   skipped: "–" }[s.status] || "·";
    li.innerHTML = `<span class="mark">${mark}</span><span>${s.label}</span>` +
      (s.detail ? `<span class="detail">${s.detail}</span>` : "");
    ul.appendChild(li);
  });
}
