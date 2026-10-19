# -*- coding: utf-8 -*-
"""细化分类规则：
- 收窄宽泛 L2 规则到 L3（PCB 不用"元件"、光模块不用"光学光电子"）
- 引入个股白名单 codes / 黑名单 exclude_codes（解决同一申万行业下业务不同的问题）
- 新增节点：面板与LED、被动元件、安防设备、其他电子、通信设备、IDC与算力
"""
import json

path = r'C:\Users\RKBL\WorkBuddy\股票看板工作台\csi300_workbench\seed\industries.json'
d = json.load(open(path, encoding='utf-8'))


def node(group, child):
    for g in d['groups']:
        if g['name'] == group:
            for c in g['children']:
                if c['name'] == child:
                    return c
    raise KeyError(group + '/' + child)


def group(name):
    for g in d['groups']:
        if g['name'] == name:
            return g
    raise KeyError(name)


# ---------- 1) AI产业链：光模块 / AI服务器 / PCB 精确化 ----------
# 光模块：申万"通信设备"下同时含网络设备(中兴/锐捷)、终端(亿联/华测导航/国盾量子)、
# 线缆(中天科技)，无法用行业名区分，改用个股白名单
node('AI产业链', '光模块')['sw_names'] = []
node('AI产业链', '光模块')['codes'] = [
    '300308',  # 中际旭创
    '300502',  # 新易盛
    '300394',  # 天孚通信
    '300620',  # 光库科技（光纤器件）
    '300548',  # 长芯博创（光通信）
    '688498',  # 源杰科技（光芯片，同时保留半导体归属）
]

# AI服务器：L3"其他计算机设备"含柏楚电子(激光控制系统)，加黑名单；
# 工业富联/华勤技术按申万归"消费电子"，但主营服务器代工，按业务白名单纳入（多重分类）
node('AI产业链', 'AI服务器')['sw_names'] = ['其他计算机设备']
node('AI产业链', 'AI服务器')['codes'] = ['000977', '603019', '601138', '603296']
node('AI产业链', 'AI服务器')['exclude_codes'] = ['688188']

# PCB：只认 L3"印制电路板"（原含 L2"元件"，会误吸三环集团等被动元件）
node('AI产业链', 'PCB')['sw_names'] = ['印制电路板']

# ---------- 2) 电子制造：新增 面板与LED / 被动元件 / 安防设备 / 其他电子 ----------
em = group('电子制造')
existing = {c['name'] for c in em['children']}
em['children'] += [
    {'name': '面板与LED', 'sw_names': ['面板', 'LED']},          # 京东方A、TCL科技、和辉光电
    {'name': '被动元件', 'sw_names': ['被动元件']},                # 三环集团(MLCC)
    {'name': '安防设备', 'sw_names': ['安防设备']},                # 海康威视、大华股份
    {'name': '其他电子', 'sw_names': ['其他电子']},                # 香农芯创(元器件分销)
]

# ---------- 3) 通信：拆出 通信设备 与 IDC与算力 ----------
tx = group('通信')
tx['children'] = [
    {'name': '电信运营', 'sw_names': ['电信运营商']},               # 移动/电信/联通
    {'name': '通信设备', 'sw_names': ['通信设备']},                 # 中兴/锐捷/中天科技/终端类
    {'name': 'IDC与算力', 'sw_names': ['通信应用增值服务']},        # 光环新网、润泽科技
]

# ---------- 4) 装备制造：柏楚电子（激光控制系统）归自动化装备 ----------
node('装备制造', '自动化装备')['codes'] = ['688188']

json.dump(d, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
n_child = sum(len(g['children']) for g in d['groups'])
print('groups:', len(d['groups']), '| children:', n_child)
