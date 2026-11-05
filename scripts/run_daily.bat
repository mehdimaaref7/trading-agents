@echo off
REM Routine quotidienne du duel (Windows). A planifier apres la cloture de New York.
cd /d "%~dp0\.."
if not exist logs mkdir logs
call .venv\Scripts\activate.bat
echo ===== %date% %time% ===== >> logs\run_daily.log
trading-agents run-daily >> logs\run_daily.log 2>&1
