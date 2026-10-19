@echo off
rem 一键：把本地最新数据同步到 Cloudflare D1，并重新发布前端
cd /d "%~dp0"
echo ============================================
echo  1/2  同步数据到 Cloudflare D1 ...
echo ============================================
".venv\Scripts\python.exe" "cloudflare\sync_to_d1.py"
echo.
echo ============================================
echo  2/2  构建并发布前端到 rkstock.pages.dev ...
echo ============================================
".venv\Scripts\python.exe" "cloudflare\build_and_deploy.py"
echo.
echo 完成。线上地址: https://rkstock.pages.dev
pause
