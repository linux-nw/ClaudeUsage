# Claude Usage

**Status:** 🟢 Aktiv

Kleine Windows-Tray-App, die deine Claude-Nutzung (Wochenlimit und Sitzungslimit) und den Countdown bis zum Reset als Symbole in der Taskleiste zeigt. Danach braucht sie kein Browserfenster mehr.

**Name:** Der Name sagt, was sie tut: Claude-Nutzung im Blick.

---

## Nutzung

Voraussetzung: Windows 10 oder 11 mit Python 3.8 oder neuer.

1. `start.bat` ausführen. Das Skript installiert die Abhängigkeiten (aus `wheels/` oder von PyPI), beendet alte Instanzen und startet die App im Hintergrund.
2. Beim ersten Start öffnet sich ein Browserfenster für den Login bei claude.ai. Danach läuft alles ohne Fenster.
3. Rechtsklick auf das Tray-Symbol: Aktualisieren, Claude öffnen, erneut einloggen, Debug-Datei, Beenden.

Manuell: `pip install pystray Pillow playwright` und einmal `python -m playwright install chromium`, dann `run.bat` (oder `debug_run.bat` mit sichtbarer Konsole).

---

## Repo-Struktur

```
claude_tray.py     die ganze App
requirements.txt   Python-Abhängigkeiten
start.bat          startet und installiert bei Bedarf
setup.bat          installiert aus wheels/
run.bat            startet ohne Installation
debug_run.bat      startet mit Konsole
wheels/            Pakete für die Offline-Installation
```

---

## Datenschutz

Die App ruft deine Nutzungsdaten von claude.ai ab. Login-Daten und Einstellungen liegen als Dateien in deinem Benutzerordner (`~/.claude_tray_*`).

---

## Lizenz

Noch offen.
