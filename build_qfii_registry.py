# -*- coding: utf-8 -*-
"""把证监会《合格境外投资者名录》xls 转成结构化 JSON：seed/qfii_registry.json"""
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import pandas as pd

SRC = r'C:\Users\RKBL\Desktop\合格境外投资者名录（2026年7月).xls'
OUT = r'C:\Users\RKBL\WorkBuddy\股票看板工作台\csi300_workbench\seed\qfii_registry.json'

df = pd.read_excel(SRC, header=1)
df = df[pd.to_numeric(df['序号'], errors='coerce').notna()].copy()

items = []
seen = set()
for _, r in df.iterrows():
    cn = str(r['中文名称']).strip()
    en = str(r['英文名称']).strip()
    if cn in ('nan', '') and en in ('nan', ''):
        continue
    key = (cn, en)
    if key in seen:
        continue
    seen.add(key)
    ad = r['批准日期']
    items.append({
        "seq": int(r['序号']),
        "cn": cn,
        "en": en,
        "region": str(r['注册地']).strip(),
        "approved": ad.strftime('%Y-%m-%d') if hasattr(ad, 'strftime') else str(ad),
        "trustee": str(r['主托管行']).strip(),
    })

doc = {
    "source": "中国证监会《合格境外投资者名录》(2026年7月)",
    "note": "QFII/RQFII 白名单。重要股东识别以本名录为基准；"
            "香港中央结算(北向)与 HKSCC(港股托管) 属跨境通道，非 QFII，单列。",
    "count": len(items),
    "items": items,
}
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(doc, f, ensure_ascii=False, indent=1)
print('写入', OUT, '条数', len(items))
print('样例:')
for it in items[:3]:
    print('  ', it)
