# Changelog / Änderungen

Versions follow [SemVer](https://semver.org/): `MAJOR.MINOR.PATCH`. While the number starts with `0.`, things may still change. PC and server must share the same MAJOR version, and for `0.x` also the same MINOR version.

Versionen folgen [SemVer](https://semver.org/lang/de/): `MAJOR.MINOR.PATCH`. Solange die Zahl mit `0.` beginnt, kann sich noch etwas ändern. PC und Server müssen dieselbe MAJOR-Version haben, bei `0.x` zusätzlich dieselbe MINOR-Version.

## Unreleased / Noch nicht veröffentlicht

**English**
- The job history window now shows date and time (e.g. "15.11. 18:25:38") instead of a wrongly formatted number.

**Deutsch**
- Das Verlaufsfenster zeigt jetzt Datum und Uhrzeit (z. B. „15.11. 18:25:38“) statt einer falsch formatierten Zahl.

## 0.1.0-beta.3

**English**
- **Retry export** now uses the game's current settings. Before, the settings frozen at the first start applied, so a retry failed again with the same error.
- The "Retry export" button in the history window is always visible and only greyed out while no export is waiting for a check.
- When a job waits for a check, the tray now names the reason from the log and says what to do. It no longer shows "Waiting for new file".
- README with a button row at the top: Download, User guide, Support and Feedback.

**Deutsch**
- **Export erneut versuchen** übernimmt jetzt die aktuellen Einstellungen des Spiels. Vorher galten die beim ersten Start eingefrorenen Einstellungen, ein Wiederholen scheiterte deshalb wieder am selben Fehler.
- Im Verlaufsfenster ist der Knopf „Export erneut versuchen“ immer sichtbar und nur ausgegraut, solange kein Export auf eine Prüfung wartet.
- Wartet ein Auftrag auf eine Prüfung, nennt der Tray jetzt den Grund aus dem Protokoll und sagt, was zu tun ist. Er zeigt dann nicht mehr „Wartet auf neue Datei“.
- README mit Knopfleiste oben: Download, Handbuch, Support und Feedback.

## 0.1.0-beta.2

**English**
- **Upload by hand:** an operating mode without a Google project. VODWerft prepares video, title, description and thumbnail, and you upload in YouTube Studio yourself (tray entry "Upload by hand").
- The installer now offers "Upload by hand" as the first operating mode; the manual and README explain the steps.

**Deutsch**
- **Manuell hochladen:** Betriebsart ohne Google-Projekt. VODWerft bereitet Video, Titel, Beschreibung und Vorschaubild vor, der Upload geschieht von Hand in YouTube Studio (Tray-Eintrag „Manuell hochladen“).
- Im Installer steht „Von Hand hochladen“ jetzt als erste Betriebsart zur Auswahl, Handbuch und README erklären den Ablauf.

## 0.1.0-beta.1

**English**
- First preview: setup assistant, tray program, 64-bit installer with prerequisite check, step list and progress bar (also for the model download), game library, upload server (Docker).
- Known: the installer is not signed yet, so Windows shows a warning. Tested on Windows 11 with an NVIDIA GPU; fresh machines without ffmpeg, uv and Ollama have had little testing.
- Upload straight from the PC (no server) with YouTube sign-in in the assistant.
- Upload server as a ready-made Docker image (`ghcr.io`), update with `docker compose pull`.
- Tray and dashboard work like Steam: one window only, a click on the tray icon opens it or brings it to the front, the X hides it in the tray, "Exit" in the tray menu closes both.
- Manual in German and English.

**Deutsch**
- Erste Vorabversion: Einrichtungsassistent, Tray-Programm, 64-Bit-Installer mit Voraussetzungsprüfung, Schrittliste und Fortschrittsanzeige (auch für den Modell-Download), Spiele-Bibliothek, Upload-Server (Docker).
- Bekannt: Der Installer ist noch nicht signiert, Windows zeigt deshalb eine Warnung. Getestet auf Windows 11 mit NVIDIA-Grafikkarte; frische Rechner ohne ffmpeg, uv und Ollama sind noch wenig getestet.
- Upload direkt vom PC (ohne Server) mit YouTube-Anmeldung im Assistenten.
- Upload-Server als fertiges Docker-Image (`ghcr.io`), Update mit `docker compose pull`.
- Tray und Dashboard wie bei Steam: nur ein Fenster, ein Klick auf das Tray-Symbol öffnet es oder holt es nach vorn, das X versteckt es in den Tray, "Beenden" im Tray-Menü beendet beides.
- Handbuch auf Deutsch und Englisch.
