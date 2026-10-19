@echo off
rem CSI 300 Industry Intelligence Workbench - 手动启动
rem 双击本文件即可：拉起守护进程（隐藏运行），服务若退出会自动恢复
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" watchdog.pyw
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:8310"
echo.
echo   工作台已启动: http://127.0.0.1:8310
echo   服务日志: data\workbench.log
echo   守护日志: data\watchdog.log
echo.
pause
