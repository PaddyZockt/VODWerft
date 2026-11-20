# Changelog / Änderungen

Versions follow [SemVer](https://semver.org/): `MAJOR.MINOR.PATCH`. While the number starts with `0.`, things may still change. PC and server must share the same MAJOR version, and for `0.x` also the same MINOR version.

Versionen folgen [SemVer](https://semver.org/lang/de/): `MAJOR.MINOR.PATCH`. Solange die Zahl mit `0.` beginnt, kann sich noch etwas ändern. PC und Server müssen dieselbe MAJOR-Version haben, bei `0.x` zusätzlich dieselbe MINOR-Version.

## 0.1.0-beta.6

**English**
- **Updating from beta.5:** quit VODWerft from the tray menu and let running jobs finish before you click "Install now". Beta.5 itself does not check this; from beta.6 on the setup does it for you (it refuses to start while a job is running, closes the running parts and starts VODWerft again).
- **Review the cut plan (optional).** With "Review the cut plan by hand" switched on (per game profile or in the settings, off by default) a job stops after the analysis. A button opens a review window with a smooth preview, a timeline of everything that was removed automatically, and the option to remove more ranges or to keep ranges the automatic cut would remove. After you confirm, episodes, lengths and metadata are recalculated and rendering continues right away. The window zooms its timeline, jumps from one removed place to the next, plays the original directly and leaves nothing running when you close it.
- **Transitions at cuts (optional).** Where a cut sits inside an episode you can choose hard (default), fade to black, blur, white flash, zoom or pixelate, per game profile or as a general default. The length of the episode never changes, so chapters stay correct.
- **YouTube details per game.** *Game profiles → YouTube*: a **playlist** (each episode is added after the upload), **fixed tags** (added to the AI's tags) and **collab partners** (the job details remind you to invite them in YouTube Studio, the API cannot do it). Playlists need an extra permission: tick "Auch Playlists zuordnen" when you sign in to YouTube in the setup assistant. If you are already set up, sign in once more with the playlist permission (see the manual, chapter 5).
- **"Use of AI" for YouTube.** YouTube asks for every video whether AI created or changed content. VODWerft does not declare anything by default, so you answer it in Studio. *Settings → YouTube* can send "No" with every upload instead (VODWerft only cuts and captions, it generates nothing).
- **Stop a job.** The new button "Auftrag stoppen" ends a running job within seconds, including ffmpeg. Finished intermediate results stay; *History → Export erneut versuchen* continues the job later.
- **Remaining time per step.** Steps with a counter (picture and sound, speech, clip rating, rendering) show "noch etwa 12 Min." in the job details. It is calculated from the real progress and appears after about a minute.
- **More progress and chapters.** Analysing picture and sound now shows "(x of 100)", also for one long recording. Recordings handled as one video each (single-video mode) get chapters and AI tags like the other games.
- **Windows notification** when a job waits for you or finishes while the dashboard is not in front (Settings → Appearance switches it off), and a **low disk space warning** before an export starts (about 2.2 times the recording, at least 20 GB; it never stops a job).
- **Library folder (server mode).** New folder `Bibliothek/<game>` next to `Fertig` with a link per uploaded episode (`2026-10-26 Folge 06 – Title.url`). `Fertig` itself stays untouched; the upload relies on it.
- **Updates.** The update button shows "What's new" first and only installs after "Install now". If a job is running, the update can wait for it. It always installs the newest version, and setup files of earlier updates in the temp folder are deleted.
- **Nightcut 0.3.2** (by Nilson). A finished stage whose files are gone is made again; a Short can keep the single audio tracks (off by default).
- **Fixes.** The "Zoom" transition zooms into the centre. Recordings in several files no longer fade to black where one file ends. The preview in the review window cannot hang on a damaged recording.
- **Server.** Playlists need the new server image: `docker compose pull`. An older server still works but does not assign playlists (the AI setting already works with it). In direct mode the new worker comes with the update.

**Deutsch**
- **Update von beta.5:** Beende VODWerft vorher über das Tray-Menü und lass laufende Aufträge fertig werden, bevor du auf „Jetzt installieren“ klickst. Beta.5 prüft das selbst noch nicht; ab beta.6 übernimmt das Setup es (es startet nicht, solange ein Auftrag läuft, beendet die laufenden Teile und startet VODWerft danach wieder).
- **Schnittplan prüfen (optional).** Ist „Plan nach der Analyse von Hand prüfen“ an (pro Spielprofil oder in den Einstellungen, Standard: aus), hält ein Auftrag nach der Analyse an. Ein Knopf öffnet ein Prüffenster mit ruckelfreier Vorschau, einer Zeitleiste der automatisch entfernten Bereiche und der Möglichkeit, weitere Bereiche zu entfernen oder Bereiche zu behalten, die die Automatik entfernen würde. Nach dem Bestätigen werden Folgen, Längen und Metadaten neu berechnet, und das Rendern läuft sofort weiter. Das Fenster zoomt die Zeitleiste, springt von einer entfernten Stelle zur nächsten, spielt das Original direkt ab und lässt beim Schließen nichts weiterlaufen.
- **Übergänge an Schnitten (optional).** Wo ein Schnitt innerhalb einer Folge sitzt, wählst du: hart (Standard), Abblende, Weichzeichner, Weißblitz, Zoom oder Pixel, pro Spielprofil oder als allgemeiner Standard. Die Länge der Folge ändert sich nie, die Kapitel bleiben also richtig.
- **YouTube-Angaben pro Spiel.** *Spielprofile → YouTube*: eine **Playlist** (jede Folge wird nach dem Upload einsortiert), **feste Tags** (kommen zu den Tags der KI) und **Collab-Partner** (die Auftragsdetails erinnern dich, sie in YouTube Studio einzuladen; die API kann das nicht). Playlists brauchen ein zusätzliches Recht: Setze beim Anmelden bei YouTube im Einrichtungsassistenten den Haken „Auch Playlists zuordnen“. Bist du schon eingerichtet, melde dich einmal mit dem Playlist-Recht neu an (siehe Handbuch, Kapitel 5).
- **„Verwendung von KI“ bei YouTube.** YouTube fragt bei jedem Video, ob KI Inhalte erzeugt oder verändert hat. VODWerft gibt standardmäßig nichts an, du beantwortest es also in Studio. *Einstellungen → YouTube* kann stattdessen bei jedem Upload „Nein“ senden (VODWerft schneidet und beschriftet nur, es erzeugt nichts).
- **Auftrag stoppen.** Der neue Knopf „Auftrag stoppen“ beendet einen laufenden Auftrag binnen Sekunden, samt ffmpeg. Fertige Zwischenergebnisse bleiben; *Verlauf → Export erneut versuchen* setzt ihn später fort.
- **Restzeit pro Schritt.** Schritte mit Zähler (Bild und Ton, Sprache, Clip-Bewertung, Rendern) zeigen „noch etwa 12 Min.“ in den Auftragsdetails. Sie wird aus dem echten Fortschritt berechnet und erscheint nach etwa einer Minute.
- **Mehr Fortschritt und Kapitel.** „Bild und Ton werden analysiert“ zeigt „(x von 100)“, auch bei einer einzigen langen Aufnahme. Aufnahmen, die als ein Video je Aufnahme laufen (Einzelvideo-Modus), bekommen Kapitel und KI-Tags wie die anderen Spiele.
- **Windows-Meldung**, wenn ein Auftrag auf dich wartet oder fertig ist und das Dashboard nicht im Vordergrund ist (Einstellungen → Darstellung schaltet sie ab), und eine **Warnung bei wenig Speicherplatz** vor dem Export (etwa das 2,2-Fache der Aufnahme, mindestens 20 GB; ein Auftrag wird nie angehalten).
- **Ordner „Bibliothek“ (Server-Betrieb).** Neuer Ordner `Bibliothek/<Spiel>` neben `Fertig` mit einer Verknüpfung je hochgeladener Folge (`2026-10-26 Folge 06 – Titel.url`). `Fertig` selbst bleibt unverändert, der Upload verlässt sich darauf.
- **Updates.** Der Update-Knopf zeigt zuerst „Was ist neu“ und installiert erst nach „Jetzt installieren“. Läuft ein Auftrag, kann das Update auf ihn warten. Es installiert immer die neueste Version, und Setup-Dateien früherer Updates im Temp-Ordner werden gelöscht.
- **Nightcut 0.3.2** (von Nilson). Eine fertige Stufe, deren Dateien fehlen, wird neu gemacht; ein Short kann die einzelnen Tonspuren behalten (standardmäßig aus).
- **Korrekturen.** Der Übergang „Zoom“ zoomt in die Mitte. Aufnahmen in mehreren Dateien blenden an Dateigrenzen nicht mehr ab. Die Vorschau im Prüffenster bleibt bei einer beschädigten Aufnahme nicht mehr hängen.
- **Server.** Playlists brauchen das neue Server-Image: `docker compose pull`. Ein älterer Server funktioniert weiter, ordnet aber keine Playlists zu (die KI-Einstellung wirkt auch dort). Im Direkt-Modus kommt der neue Worker mit dem Update.

## 0.1.0-beta.5

**English**
- **Automatic updates:** VODWerft checks GitHub for a newer release at start and every six hours, and the new "Check for updates" button does it on demand. When one exists, the button changes to "Update available" and one click downloads and installs it (checksum is verified; nothing is installed without your confirmation). Updating from beta.4 to beta.5 still has to be done by hand because beta.4 does not have this feature yet.
- **Help menu:** "System check" shows at a glance whether ffmpeg, Ollama, graphics card, free disk space, input folder, background services and server are fine. "Create error report" packs version, check result and the latest log lines into one ZIP you can send to someone. Passwords, tokens and your Windows user name are removed.
- **Server:** the example `docker-compose.yml` used an image tag (`0.1`) that does not exist for beta versions, so `docker compose up` failed with "manifest unknown". It now uses `latest`. Tested on ARM64 (Orange Pi, Docker 29).
- Manual: you need your own Google project for automatic uploads (steps in chapter 5).

**Deutsch**
- **Automatische Updates:** VODWerft sucht beim Start und alle sechs Stunden auf GitHub nach einer neueren Version, und der neue Knopf „Nach Updates suchen“ tut das auf Wunsch. Gibt es eine, steht dort „Update verfügbar“, und ein Klick lädt und installiert sie (die Prüfsumme wird kontrolliert, ohne deine Bestätigung wird nichts installiert). Das Update von beta.4 auf beta.5 musst du noch von Hand machen, weil beta.4 die Funktion noch nicht hat.
- **Menü „Hilfe“:** Die „Systemprüfung“ zeigt auf einen Blick, ob ffmpeg, Ollama, Grafikkarte, freier Speicherplatz, Eingangsordner, Hintergrunddienste und Server in Ordnung sind. „Fehlerbericht erstellen“ packt Version, Prüfergebnis und die letzten Protokollzeilen in eine ZIP-Datei, die du weitergeben kannst. Passwörter, Tokens und dein Windows-Benutzername werden entfernt.
- **Server:** Die Beispiel-`docker-compose.yml` nutzte einen Image-Tag (`0.1`), den es bei Beta-Versionen nicht gibt, deshalb scheiterte `docker compose up` mit „manifest unknown“. Jetzt steht dort `latest`. Auf ARM64 getestet (Orange Pi, Docker 29).
- Handbuch: Für den automatischen Upload brauchst du ein eigenes Google-Projekt (Schritte in Kapitel 5).

## 0.1.0-beta.4

**English**
- **Description template per game:** a new "Description" section in the game profile editor lets you edit one description that every episode of that game gets (links, hardware, mod notes). Chapter marks are still added automatically. New games get a starter template right away. Without a template the AI still writes each description.
- The job history window now shows date and time (e.g. "15.11. 18:25:38") instead of a wrongly formatted number.

**Deutsch**
- **Beschreibungsvorlage pro Spiel:** Im Profil-Editor gibt es einen neuen Abschnitt „Beschreibung“. Dort bearbeitest du eine Beschreibung, die jede Folge dieses Spiels bekommt (Links, Hardware, Hinweise zur Mod). Die Kapitelmarken hängt das Programm weiter selbst an. Neue Spiele bekommen sofort eine Startvorlage. Ohne Vorlage schreibt die KI die Beschreibung wie bisher.
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
