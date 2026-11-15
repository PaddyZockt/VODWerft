# Änderungen / Changelog

Versionen folgen [SemVer](https://semver.org/lang/de/): `MAJOR.MINOR.PATCH`. Solange die Zahl mit `0.` beginnt, kann sich noch etwas ändern. PC und Server müssen dieselbe MAJOR-Version haben, bei `0.x` zusätzlich dieselbe MINOR-Version.

## 0.1.0-beta.3
- **Export erneut versuchen** übernimmt jetzt die aktuellen Einstellungen des Spiels. Vorher galten die beim ersten Start eingefrorenen Einstellungen, ein Wiederholen scheiterte deshalb wieder am selben Fehler.
- Im Verlaufsfenster ist der Knopf „Export erneut versuchen“ immer sichtbar und nur ausgegraut, solange kein Export auf eine Prüfung wartet.
- Wartet ein Auftrag auf eine Prüfung, nennt der Tray jetzt den Grund aus dem Protokoll und sagt, was zu tun ist. Er zeigt dann nicht mehr „Wartet auf neue Datei“.

## 0.1.0-beta.2
- **Manuell hochladen:** Betriebsart ohne Google-Projekt. VODWerft bereitet Video, Titel, Beschreibung und Vorschaubild vor, der Upload geschieht von Hand in YouTube Studio (Tray-Eintrag „Manuell hochladen“).
- Im Installer steht „Von Hand hochladen“ jetzt als erste Betriebsart zur Auswahl, Handbuch und README erklären den Ablauf.

## 0.1.0-beta.1
- Erste Vorabversion: Einrichtungsassistent, Tray-Programm, 64-Bit-Installer mit Voraussetzungsprüfung, Schrittliste und Fortschrittsanzeige (auch für den Modell-Download), Spiele-Bibliothek, Upload-Server (Docker).
- Bekannt: Der Installer ist noch nicht signiert, Windows zeigt deshalb eine Warnung. Getestet auf Windows 11 mit NVIDIA-Grafikkarte; frische Rechner ohne ffmpeg, uv und Ollama sind noch wenig getestet.
- Upload direkt vom PC (ohne Server) mit YouTube-Anmeldung im Assistenten.
- Upload-Server als fertiges Docker-Image (`ghcr.io`), Update mit `docker compose pull`.
- Tray und Dashboard wie bei Steam: nur ein Fenster, ein Klick auf das Tray-Symbol öffnet es oder holt es nach vorn, das X versteckt es in den Tray, "Beenden" im Tray-Menü beendet beides.
- Handbuch auf Deutsch und Englisch.
