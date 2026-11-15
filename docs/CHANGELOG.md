# Änderungen / Changelog

Versionen folgen [SemVer](https://semver.org/lang/de/): `MAJOR.MINOR.PATCH`. Solange die Zahl mit `0.` beginnt, kann sich noch etwas ändern. PC und Server müssen dieselbe MAJOR-Version haben, bei `0.x` zusätzlich dieselbe MINOR-Version.

## 0.1.0-beta.1 (noch nicht veröffentlicht)
- Erste Vorabversion: Einrichtungsassistent, Tray-Programm, 64-Bit-Installer mit Voraussetzungsprüfung, Schrittliste und Fortschrittsanzeige (auch für den Modell-Download), Spiele-Bibliothek, Upload-Server (Docker).
- Bekannt: Der Installer ist noch nicht signiert, Windows zeigt deshalb eine Warnung. Getestet auf Windows 11 mit NVIDIA-Grafikkarte; frische Rechner ohne ffmpeg, uv und Ollama sind noch wenig getestet.
- **Manuell hochladen:** Betriebsart ohne Google-Projekt. VODWerft bereitet Video, Titel, Beschreibung und Vorschaubild vor, der Upload geschieht von Hand in YouTube Studio (Tray-Eintrag „Manuell hochladen“).
- Upload direkt vom PC (ohne Server) mit YouTube-Anmeldung im Assistenten.
- Upload-Server als fertiges Docker-Image (`ghcr.io`), Update mit `docker compose pull`.
- Tray und Dashboard wie bei Steam: nur ein Fenster, ein Klick auf das Tray-Symbol öffnet es oder holt es nach vorn, das X versteckt es in den Tray, "Beenden" im Tray-Menü beendet beides.
- Handbuch auf Deutsch und Englisch.
