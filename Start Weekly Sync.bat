@echo off
title Weekly Sync - Events Team
cd /d "%~dp0"

echo ============================================
echo   Weekly Sync - Events Team
echo ============================================
echo.
echo Checking dependencies (first run may take a moment)...
python -m pip install -q -r requirements.txt

echo.
echo Starting the page... a browser tab will open shortly.
echo KEEP THIS WINDOW OPEN while you use the page.
echo Close this window to stop the server.
echo.

start "" cmd /c "timeout /t 2 >nul & start http://localhost:5000"
python app.py

echo.
echo Server stopped.
pause
