# CSI 300 股票看板工作台

面向投研的 A 股看板：把「沪深300 + 创业板指 + 科创50」成分股的**行情估值、业绩变化、重要股东（QFII）动向**汇到一张表里，支持本地运行与云端只读副本。

## 功能

- **股票主表**：市值、收盘价、自算 PE、归母净利同比、业绩变化（改善/放缓）、YTD，可按行业/股东筛选
- **重要股东监控**：抓取十大流通股东，按证监会《合格境外投资者名录》核验，聚合增持（含新进）金额
- **业绩变化**：最新累计期同比 vs 前一期累计同比，边际加速判定为「改善」
- **云端副本**：本地更新后一键同步到 Cloudflare D1，`Pages` 提供免登录的只读页面

## 目录结构

```
main.py                 启动入口（FastAPI，127.0.0.1:8310）
api.py                  HTTP 接口 + 静态资源托管
db.py                   SQLite 数据访问层
config.py               全局配置
providers/              数据源实现（当前为 FTShare）
services/
  updater.py            更新流程编排（成分→行情→财务→估值→YTD→股东→分类→同步）
  holders.py            十大流通股东抓取 + QFII 名录匹配
  classifier.py         申万行业分类
seed/                   QFII 名录、重要股东别名、行业规则
web/                    前端（原生 JS + AG Grid）
cloudflare/             Pages Functions + D1 建表/同步/部署脚本
watchdog.pyw            Windows 保活守护（每 30s 探测 8310 端口）
```

## 本地运行

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

python main.py
# 浏览器打开 http://127.0.0.1:8310
```

首次启动会自动创建 `data/workbench.db`。点击页面上的「更新数据」才会真正抓取行情与财报。

### Windows 常驻（可选）

```bash
setup_autostart.py     # 写入启动项
start_workbench.bat    # 手动启动（含 watchdog）
```

`watchdog.pyw` 会每 30 秒探测端口，服务异常退出时自动拉起。

## 数据来源

通过 [ftshare-python-sdk](https://github.com/ftshare-lab/ftshare-python-sdk) 调用，零凭据可用的公开接口：

| 用途 | 接口 |
|---|---|
| 指数成分 | `index_weight_list` |
| 行情估值 | `eastmoney_stock_valuation`（注意 `trade_date` 必须 `YYYYMMDD`） |
| 财务报表 | `income` |
| 十大流通股东 | `stock_float_holders` |
| 申万行业 | `sw_industry_overview` / `sw_industry_constituent_history` |

## 两个关键数据口径（踩过坑）

1. **净利润同比一律自算**：数据源的 `parcomp_n_profit_yoy` 在「去年同期净利为负」时符号会翻转（其余公式等价于 `(今-去)/去`，分母带符号）。标准应为 `(今-去)/|去|`，因此本项目用两期累计净利自行计算。典型：扭亏为盈股实际 +3273%，数据源给 -3273%。
2. **最新报告期按报告期先后取**：`np_yoy` 多期并存，不能按披露日或行 id 取「最新」——旧报告期的更正公告日期可能更晚。排序键为 `年份*10 + (Q1=1/H1=2/Q3=3/FY=4)`。

## 云端部署（可选）

```bash
# 1) 准备配置：复制模板并填入自己的值
copy cloudflare\cloudflare.example.json data\cloudflare.json

# 2) 建 D1 表结构
python cloudflare/provision.py

# 3) 构建并发布 Pages（含 Functions）
python cloudflare/build_and_deploy.py
```

`data/cloudflare.json` 含令牌，已被 `.gitignore` 排除，**不要提交**。
