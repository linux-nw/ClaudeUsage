@echo off
cd /d "%~dp0"
echo Installing dependencies...
pip install --no-index --find-links "wheels" pystray Pillow playwright
if %errorlevel% neq 0 (
    echo.
    echo FAILED. Run as Administrator if pip is blocked.
    pause
    exit /b 1
)
echo.
echo Setup complete. Run run.bat to start.
pause
