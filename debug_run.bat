@echo off
cd /d "%~dp0"
echo Starte Claude Usage mit sichtbarer Konsole...
echo Fenster offen lassen und Fehlermeldungen lesen.
echo.
python claude_tray.py
echo.
echo Prozess beendet.
pause
