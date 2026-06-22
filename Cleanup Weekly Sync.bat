@echo off
title Cleanup Weekly Sync
cd /d "%~dp0"
echo This will clear THIS WEEK's topics, forecast, and notes,
echo and remove completed action items (open ones are kept).
echo.
set /p ok="Type Y then Enter to proceed (anything else cancels): "
if /I not "%ok%"=="Y" (echo Cancelled. & pause & exit /b)
python cleanup_sync.py
echo.
pause
