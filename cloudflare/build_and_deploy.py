# -*- coding: utf-8 -*-
"""构建云端站点并发布到 Cloudflare Pages。

1) 把 web/ 复制成 cloudflare/public/
2) 注入构建戳(__BUILD__) 与 运行模式(__MODE__=cloud)
3) 把同一个构建戳写进 D1 sync_meta.build（保证 /api/version 与页面一致，不会误触发自动刷新）
4) 用 wrangler 直传发布

用法：python cloudflare/build_and_deploy.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import io
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import cf_api as cf                                                  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CF_DIR = os.path.join(ROOT, "cloudflare")
WEB = os.path.join(ROOT, "web")
PUBLIC = os.path.join(CF_DIR, "public")
WS = r"C:\Users\RKBL\.workbuddy\binaries\node\workspace"
NODE = r"C:\Users\RKBL\.workbuddy\binaries\node\versions\22.22.2-6\node.exe"
WRANGLER = os.path.join(WS, "node_modules", "wrangler", "bin", "wrangler.js")

conf = cf.load_conf()
STAMP = time.strftime("%Y%m%d%H%M%S")
print("构建戳:", STAMP)

# ---------- 1) 复制静态资源 ----------
# 本地 FastAPI 是把 web/ 整个目录挂在 /assets 下的，所以 index.html 里引用的是
# /assets/app.js、/assets/style.css。Cloudflare Pages 里必须真实存在这个层级，
# 否则 /assets/* 会 404 并被 SPA 回退成 index.html（MIME text/html → 样式和脚本全挂）。
if os.path.exists(PUBLIC):
    shutil.rmtree(PUBLIC)
os.makedirs(PUBLIC)
shutil.copy2(os.path.join(WEB, "index.html"), os.path.join(PUBLIC, "index.html"))
shutil.copytree(WEB, os.path.join(PUBLIC, "assets"),
                ignore=shutil.ignore_patterns("*.map", "index.html"))
n = sum(len(f) for _, _, f in os.walk(PUBLIC))
print(f"已复制 {n} 个静态文件 -> cloudflare/public（index.html + assets/）")

# ---------- 2) 注入构建戳与模式 ----------
idx = os.path.join(PUBLIC, "index.html")
html = open(idx, encoding="utf-8").read()
html = html.replace("__BUILD__", STAMP).replace("__MODE__", "cloud")
open(idx, "w", encoding="utf-8").write(html)
print("已注入 __BUILD__ / __MODE__=cloud")

# ---------- 3) 写 D1 构建戳 ----------
r = cf.d1_query(
    "INSERT INTO sync_meta (k,v) VALUES ('build',?)"
    " ON CONFLICT(k) DO UPDATE SET v=excluded.v", [STAMP], conf=conf)
print("写 D1 sync_meta.build:", r.get("success"))

# ---------- 4) wrangler 直传 ----------
env = dict(os.environ)
env["CLOUDFLARE_API_TOKEN"] = conf["token"]
env["CLOUDFLARE_ACCOUNT_ID"] = conf["account_id"]
env["WRANGLER_SEND_METRICS"] = "false"
cmd = [NODE, WRANGLER, "pages", "deploy", PUBLIC,
       "--project-name", conf["project"], "--branch", "main",
       "--commit-dirty=true"]
print("\n执行:", " ".join(cmd[1:]))
p = subprocess.run(cmd, cwd=CF_DIR, env=env, capture_output=True, text=True)
print("exit:", p.returncode)
print((p.stdout or "")[-3000:])
if p.stderr:
    print("stderr:", (p.stderr or "")[-2000:])
