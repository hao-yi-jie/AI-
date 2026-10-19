@echo off
rem CSI300 Workbench autostart launcher (ASCII ONLY - cmd parses .bat as GBK,
rem so non-ASCII here would be mojibake; keep this file pure ASCII).
rem
rem 1) Append a line to data\autostart.log so we can later tell whether the
rem    logon hook actually fired (this is how we found the 9/17-9/18 gap).
rem 2) Start the watchdog (hidden), which keeps the web service alive forever.
cd /d "%~dp0"
if not exist "data" mkdir "data"
>> "data\autostart.log" echo %DATE% %TIME% autostart.bat fired
start "" ".venv\Scripts\pythonw.exe" watchdog.pyw
