@echo off
rem Station Review launcher - double-click to start, then open http://localhost:8780/
rem To let other PCs on the network use it, change --host 127.0.0.1 to --host 0.0.0.0
setlocal
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% -c "import docx" 2>nul
if errorlevel 1 (
  echo Installing required Python packages...
  %PY% -m pip install -r "%~dp0requirements.txt"
)
%PY% -m station_review --host 127.0.0.1 --port 8780 --data "%~dp0data"
pause
