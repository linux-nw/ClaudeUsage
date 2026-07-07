@echo off
cd /d "%~dp0"

:: Pruefen ob Python vorhanden
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Python nicht gefunden!
    echo Installiere Python 3 von https://python.org
    pause & exit /b 1
)

:: Abhaengigkeiten installieren wenn noetig
python -c "import pystray, PIL, playwright" >nul 2>&1
if %errorlevel% neq 0 (
    echo Installiere Abhaengigkeiten...
    pip install --quiet --no-index --find-links "wheels" pystray Pillow playwright >nul 2>&1
    python -c "import pystray, PIL, playwright" >nul 2>&1
    if %errorlevel% neq 0 (
        echo Lokale Wheels nicht kompatibel, installiere von PyPI...
        pip install pystray Pillow playwright
        if %errorlevel% neq 0 (
            echo FEHLER: Installation fehlgeschlagen!
            pause & exit /b 1
        )
    )
)

:: Alle alten Instanzen beenden
taskkill /F /FI "IMAGENAME eq pythonw.exe" /FI "WINDOWTITLE eq Claude*" >nul 2>&1

:: App starten
where pythonw >nul 2>&1
if %errorlevel% equ 0 (
    start "" pythonw "%~dp0claude_tray.py"
) else (
    for /f "delims=" %%P in ('where python') do (
        if exist "%%~dpPpythonw.exe" (
            start "" "%%~dpPpythonw.exe" "%~dp0claude_tray.py"
            goto :launched
        )
    )
    start "" python "%~dp0claude_tray.py"
)
:launched

echo.
echo ================================================
echo  Claude Usage gestartet!
echo.
echo  Das Icon erscheint im SYSTEM-TRAY (rechts
echo  unten in der Taskleiste). Falls nicht sichtbar:
echo  Klicke auf den Pfeil  ^   neben der Uhr.
echo.
echo  Ein Popup bestaetigt den Start.
echo ================================================
echo.
timeout /t 8 /nobreak >nul
