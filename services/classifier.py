# -*- coding: utf-8 -*-
"""行业分类服务。

分类体系定义在 seed/industries.json（用户可随时编辑，点击“更新数据”后重新应用）：

{
  "groups": [
    {"name": "AI产业链", "children": [
      {"name": "光模块", "sw_names": ["通信设备", "光学光电子"]},
      ...
    ]}
  ]
}

sw_names 是申万 2021 行业（L1/L2/L3）名称匹配规则，一只股票可命中多个节点
（多重分类是本系统的核心设计）。规则未覆盖的股票进入“未分类 / 待归类”。
"""
import json

from config import SEED_DIR
import db

UNCATEGORIZED_GROUP = "未分类"
UNCATEGORIZED_SUB = "待归类"


def _norm(name) -> str:
    """规范申万行业名：去掉罗马数字后缀（白酒Ⅱ -> 白酒）。"""
    if not name:
        return ""
    return name.rstrip("ⅠⅡⅢ")


def load_seed() -> dict:
    path = SEED_DIR / "industries.json"
    if not path.exists():
        return {"groups": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def ensure_industries(conn) -> dict:
    """把 seed 中的分类树写入 industries 表（幂等）。

    返回键值映射：
      "g/分组名" -> 分组节点 id
      "s/分组名/子行业名" -> 子节点 id
      "uncategorized" -> 待归类节点 id
    """
    seed = load_seed()
    node_ids = {}

    def ensure(name, parent_id, node_type, sort_order):
        row = conn.execute(
            "SELECT id FROM industries WHERE name=? AND parent_id IS ?",
            (name, parent_id)).fetchone()
        if row:
            return row["id"]
        cur = conn.execute(
            "INSERT INTO industries (name, parent_id, node_type, sort_order)"
            " VALUES (?,?,?,?)", (name, parent_id, node_type, sort_order))
        return cur.lastrowid

    for gi, group in enumerate(seed.get("groups", [])):
        gid = ensure(group["name"], None, "group", gi)
        node_ids[f"g/{group['name']}"] = gid
        for si, child in enumerate(group.get("children", [])):
            sid = ensure(child["name"], gid, "sub", si)
            node_ids[f"s/{group['name']}/{child['name']}"] = sid
    # 未分类兜底节点
    ugid = ensure(UNCATEGORIZED_GROUP, None, "group", 999)
    node_ids["uncategorized"] = ensure(UNCATEGORIZED_SUB, ugid, "sub", 0)
    conn.commit()
    return node_ids


def classify_stocks(provider, conn) -> dict:
    """依据 seed 规则 + 申万行业映射，重建全部股票的行业关联。

    V1 策略：分类完全由 industries.json 规则驱动，每次更新时全量重建
    stock_industries（确定性结果）。未来加入手动调整 UI 后改为增量。
    """
    node_ids = ensure_industries(conn)
    seed = load_seed()

    # 规则引用的全部申万名称
    rule_names = set()
    flat_rules = []  # [(child_dict, node_id)]
    order = 0
    for group in seed.get("groups", []):
        for child in group.get("children", []):
            nid = node_ids.get(f"s/{group['name']}/{child['name']}")
            if nid:
                # 预处理白名单/黑名单为 set，避免逐股重复构建
                child["_codes"] = set(child.get("codes", []))
                child["_exclude"] = set(child.get("exclude_codes", []))
                # 唯一归属优先级：priority 显式指定优先，否则按声明顺序
                child["_order"] = (child.get("priority", 999), order)
                order += 1
                flat_rules.append((child, nid))
                rule_names.update(child.get("sw_names", []))
    # 优先级排序：数值越小越优先（一家公司只归入命中的最高优先级节点）
    flat_rules.sort(key=lambda x: x[0]["_order"])

    # 申万数据已全部入库时跳过远程拉取（首次或成分股调整后才会拉取）
    missing = conn.execute(
        "SELECT COUNT(*) c FROM stocks WHERE in_csi300=1 AND sw_l1 IS NULL"
    ).fetchone()["c"]
    sw_map = {}
    known_names = set()
    need_l3 = bool(rule_names)
    if missing:
        # 先只拉 L1+L2；若规则中存在未覆盖名称，再补拉 L3
        sw_map = provider.get_sw_industry_map(levels=(2,))
        known_names = {_norm(v) for m in sw_map.values() for v in m.values()}
        if rule_names - known_names:
            need_l3 = True
            sw_map = provider.get_sw_industry_map(levels=(2, 3))
    else:
        # DB 中已有申万层级，检查 L3 规则是否可满足
        l3_covered = conn.execute(
            "SELECT COUNT(*) c FROM stocks WHERE in_csi300=1 AND sw_l3 IS NOT NULL"
        ).fetchone()["c"]
        need_l3 = bool(rule_names - {_norm(v) for m in
                       conn.execute("SELECT sw_l1 a, sw_l2 b, sw_l3 c FROM stocks"
                                    " WHERE in_csi300=1").fetchall()
                       for v in (m["a"], m["b"], m["c"]) if v}) and not l3_covered

    stocks = conn.execute(
        "SELECT stock_code, stock_name, sw_l1, sw_l2, sw_l3 FROM stocks"
        " WHERE in_csi300=1").fetchall()

    conn.execute("DELETE FROM stock_industries")
    uncategorized_id = node_ids.get("uncategorized")

    matched, unmatched = 0, 0
    for s in stocks:
        code = s["stock_code"]
        levels = {_norm(x) for x in (s["sw_l1"], s["sw_l2"], s["sw_l3"])} - {""}
        # DB 中没有申万信息时尝试用拉取结果补
        if not levels and code in sw_map:
            m = sw_map[code]
            levels = {_norm(x) for x in (m.get("l1"), m.get("l2"), m.get("l3"))} - {""}
            if m:
                conn.execute(
                    "UPDATE stocks SET sw_l1=?, sw_l2=?, sw_l3=? WHERE stock_code=?",
                    (m.get("l1"), m.get("l2"), m.get("l3"), code))
        # 唯一归属：命中规则中取优先级最高（声明顺序）的一个节点。
        # 命中 = 申万名称命中 或 个股白名单命中；黑名单强制排除。
        primary = None
        for child, nid in flat_rules:
            hit = bool(set(child.get("sw_names", [])) & levels)
            if not hit and code in child["_codes"]:
                hit = True
            if hit and code in child["_exclude"]:
                hit = False
            if hit:
                primary = nid
                break
        if primary is not None:
            matched += 1
            conn.execute("INSERT OR IGNORE INTO stock_industries VALUES (?,?)",
                         (code, primary))
        else:
            unmatched += 1
            if uncategorized_id:
                conn.execute("INSERT OR IGNORE INTO stock_industries VALUES (?,?)",
                             (code, uncategorized_id))
    conn.commit()
    return {"matched": matched, "unmatched": unmatched,
            "need_l3": need_l3, "rules": len(flat_rules)}
