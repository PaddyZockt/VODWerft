# VODWerft – Benutzerhandbuch

VODWerft verwandelt deine Spielaufnahmen automatisch in fertige Folgen: Es schneidet, vergibt Titel und Beschreibung, erstellt Vorschaubilder und lädt die Videos zeitgesteuert zu YouTube hoch. Die Verarbeitung läuft auf deinem Windows-PC. Der Upload läuft **von Hand** (am einfachsten, kein Google-Projekt nötig), **direkt vom PC** oder über einen kleinen **Server mit Docker** (für Dauerbetrieb).

> **Einsteiger:** Wähle im Installer „Von Hand hochladen“. Dann brauchst du kein Google-Projekt, VODWerft bereitet jede Folge vor (siehe [Manuell hochladen](#manuell-hochladen-ohne-youtube-projekt)).

> **Wichtig vorab (nur für automatischen Upload):** Neue YouTube-Zugänge werden von YouTube zunächst so behandelt, dass per Programm hochgeladene Videos **privat bleiben**, bis dein Google-Projekt ein Prüfverfahren („Audit“) bestanden hat. Lies dazu den Abschnitt [YouTube-Freigabe](#5-youtube-anmeldung-und-freigabe) bevor du viel Zeit in die Einrichtung steckst.

## 1. Was du brauchst

| Was | Wofür |
|---|---|
| Windows-PC mit NVIDIA-Grafikkarte, **16 GB Grafikspeicher** empfohlen | Verarbeitung der Videos mit lokalen KI-Modellen |
| ca. 30 GB freier Speicher | Modelle und Zwischendateien |
| *Optional:* ein Linux-Server (oder NAS) mit **Docker** und eine Netzwerkfreigabe | Upload rund um die Uhr, ohne dass der PC dafür laufen muss |
| Ein YouTube-Kanal und ein Google-Konto | Ziel der Uploads |

Der Installer prüft **uv**, **ffmpeg** und **Ollama** und bietet an, fehlende Programme mit `winget` zu installieren. Es wird nichts ohne deine Zustimmung installiert. Für die KI-Modelle brauchst du eine Internetverbindung (rund 25 GB Download).

## 2. Installation auf dem PC

1. **`VODWerft-Setup.exe`** von der Release-Seite herunterladen und doppelt anklicken.
2. **Windows warnt:** Der Installer ist noch nicht digital signiert. Edge oder SmartScreen zeigen deshalb „Windows hat den PC geschützt“ oder „wird nicht häufig heruntergeladen“. Das ist bei einer Beta normal. Klicke auf **Weitere Informationen** und dann auf **Trotzdem ausführen** (in Edge: die drei Punkte beim Download, **Beibehalten**, dann **Trotzdem beibehalten**). Bestätige danach die Administrator-Rückfrage.
3. **Fragen im Installer:** Zielordner, Betriebsart (nur dieser PC oder mit Server), Datenordner und welche fehlenden Programme (uv, ffmpeg, Ollama) installiert werden sollen. Es wird nichts ohne Haken installiert.
4. **Fortschritt:** Auf der Installationsseite siehst du eine Liste der Schritte (wartet, läuft, fertig) und einen Fortschrittsbalken. Der Balken zeigt beim Laden der KI-Modelle den echten Fortschritt in Prozent.
5. **Dauer:** Ohne Modelle dauert es wenige Minuten. Die KI-Modelle sind rund **25 GB** groß. Je nach Internetleitung sind das **30 Minuten bis mehrere Stunden**. Das Fenster kann dabei offen bleiben, der Rechner darf nicht in den Ruhezustand gehen.
6. Am Ende öffnet sich der **Einrichtungsassistent** (Kapitel 3). Es gibt ein Symbol **VODWerft** im Startmenü, auf Wunsch auch auf dem Desktop (Haken im Installer) und im Autostart.

**Bricht etwas ab?** Am Ende zeigt der Installer eine Meldung, was nicht geklappt hat. Die Einzelheiten stehen im Protokoll `%TEMP%\vodwerft-setup.log` (Windows-Taste + R, Pfad eingeben). Fehlende KI-Modelle werden beim ersten Start nachgeladen. Du kannst den Installer jederzeit erneut starten.

## Deinstallation

1. **Einstellungen → Apps → Installierte Apps → VODWerft → Deinstallieren**.
2. Im Fenster kannst du zusätzlich **uv, ffmpeg, Ollama** und **die KI-Modelle von VODWerft** mit entfernen. Standardmäßig ist nichts angehakt. Lass den Haken weg, wenn du die Programme noch für etwas anderes brauchst.
3. **Deine Daten bleiben immer erhalten** (Videos, Einstellungen, YouTube-Anmeldung) im Datenordner unter `%LOCALAPPDATA%\VODWerft`. Wenn du sie ebenfalls loswerden willst, lösche diesen Ordner von Hand.

## 3. Erste Einrichtung (Assistent)

Beim ersten Start öffnet sich der Einrichtungsassistent von selbst. Du kannst ihn später im Tray-Menü (Symbol unten rechts neben der Uhr, Rechtsklick) über **Einrichtung öffnen** erneut starten.

0. **Upload-Art wählen:** „Von Hand hochladen“ (empfohlen für den Start, ohne YouTube-Projekt), „Direkt von diesem PC“ (automatisch, braucht ein Google-Projekt) oder „Über einen Server“.
1. **Rechner prüfen:** zeigt, ob ffmpeg, Ollama und die Grafikkarte gefunden wurden.
2. **Ordner:** Datenordner (Standard ist in Ordnung), die **Server-Freigabe** (der Ordner, in dem der Upload-Server arbeitet; darin müssen `.upload`, `Fertig` und `Pruefen` liegen, siehe Abschnitt 4), der Oberordner deiner Aufnahmen, ffmpeg-Ordner, Ollama und der Link zu deinem Kanal.
3. **Spiele:** Wähle Spiele aus der Bibliothek oder tippe einen eigenen Namen (ohne `: / \ ? * " < > |`). Pro Spiel stellst du die Folgenlänge und die Veröffentlichungstage ein. Für jedes Spiel entsteht ein Aufnahmeordner unter deinem Aufnahmen-Oberordner; lege dort deine Videodateien ab.
4. **Speichern:** Die Dienste starten sofort.

**Sicher voreingestellt:** Jede Folge wartet vor dem Upload auf deine Freigabe, und der Upload ist gesperrt, bis die Datei `upload-freigabe.flag` im Datenordner liegt. So geht nichts versehentlich online.

## 4. Der Upload-Server (Docker, optional)

Dieses Kapitel brauchst du nur, wenn du im Assistenten „Über einen Server“ gewählt hast. Im Direkt-Modus kannst du direkt bei Kapitel 5 weitermachen.

Im Paket liegt der Ordner `server`. Das fertige Server-Image wird automatisch bei jedem Release gebaut und von GitHub geladen; du musst nichts selbst bauen.

1. Lege auf dem Server einen Ordner an und kopiere `docker-compose.yml` und `.env.example` hinein. Benenne `.env.example` in `.env` um und trage deine Pfade ein.
2. Lege im Ordner für die Freigabe die Unterordner `.upload`, `Fertig`, `Pruefen` und `.status` an und gib die Freigabe im Netzwerk für deinen PC frei.
3. Kopiere `config-example/description-footer.txt` als `description-footer.txt` in den Programmordner des Servers (`UPLOADER_DIR`) und passe den Text an (Platzhalter `${game}` und `${developer}` sind möglich).
4. Starte mit `docker compose up -d`. Aktualisieren: `docker compose pull && docker compose up -d`.

Der Server meldet seine Version an den PC; passen beide nicht zusammen, warnt das Tray-Symbol.

## Manuell hochladen (ohne YouTube-Projekt)

Das ist der einfachste Weg und braucht **keine** Anmeldung und **kein** Google-Projekt. VODWerft schneidet, vergibt Titel und Beschreibung und erstellt das Vorschaubild. Den Upload machst du selbst in YouTube Studio, das dauert etwa eine Minute pro Folge. Dein Video wird dabei nicht auf „privat“ gezwungen.

1. Rechtsklick auf das Tray-Symbol → **Manuell hochladen**. (Der Eintrag erscheint nur in dieser Betriebsart.)
2. Links wählst du eine fertige Folge. Nur freigegebene und fertige Folgen stehen in der Liste.
3. **YouTube Studio öffnen** und das Video hineinziehen. Mit **Video im Ordner zeigen** findest du die Datei.
4. **Titel kopieren** und in YouTube einfügen, danach **Beschreibung kopieren** und **Tags**.
5. Als Miniaturansicht das Vorschaubild hochladen (**Vorschaubild zeigen**).
6. Steht dort ein **geplanter Termin**, stellst du ihn in YouTube unter Sichtbarkeit → Planen ein.
7. Zum Schluss **Als hochgeladen markieren**. Die Folge wandert in den Ordner „Fertig“ und verschwindet aus der Liste.

Du kannst später in den Einrichtungsassistenten wechseln („Einrichtung öffnen“) und auf automatischen Upload umstellen.

## 5. YouTube-Anmeldung und Freigabe

Dieses Kapitel brauchst du **nur für den automatischen Upload** (direkt vom PC oder über den Server). Beim manuellen Upload kannst du es überspringen.

Die Anmeldung machst du einmalig und selbst; dein Google-Passwort gibst du nirgends in VODWerft ein.

**Direkt-Modus:** Im Assistenten wählst du nach den Schritten 1 bis 4 unten die Zugangsdatei (`client_secrets.json`) aus und klickst auf „Bei YouTube anmelden“. Der Browser öffnet die Google-Anmeldung, danach ist alles fertig. Du kannst das auch später über das Tray-Menü („Einrichtung öffnen“) nachholen. Der Upload bleibt gesperrt, bis die Anmeldung steht.

**Server-Modus:** Folge den Schritten 5 und 6 unten.

**Wichtig: Du brauchst ein eigenes Google-Projekt.** Der Autor von VODWerft teilt sein eigenes Projekt nicht, und die Zugangsdatei (`client_secrets.json`) ist an ein Projekt gebunden. Jede Person legt sich also ihr eigenes Projekt an (kostenlos, die Schritte unten). Das Kontingent und die oben genannten Einschränkungen von YouTube gelten dann für dein Projekt. Wenn dir das zu aufwendig ist, nimm den Weg „Von Hand hochladen“.

Zuerst in beiden Modi:

1. In der Google Cloud Console ein **neues Projekt** anlegen.
2. **YouTube Data API v3** aktivieren.
3. **OAuth-Zustimmungsbildschirm** einrichten; dich selbst als Testnutzer eintragen.
4. Einen **OAuth-Client** vom Typ „Desktop-App“ erstellen und die Datei `client_secrets.json` herunterladen.
5. *(Server-Modus)* Die Datei in den Ordner für Zugangsdaten legen (`SECRETS_DIR` aus der `.env`). **Niemals** in ein Repository oder eine Freigabe legen.
6. *(Server-Modus)* Die Anmeldung im Browser einmal bestätigen. Dabei entsteht die Token-Datei `request.token`.

**Playlist-Recht nachholen:** Wenn du Videos automatisch einer Playlist zuordnen willst, braucht die Anmeldung ein zusätzliches Recht. Neu eingerichtet: Haken „Auch Playlists zuordnen“ im Assistenten. Schon eingerichtet: Öffne eine Eingabeaufforderung im Programmordner (`C:\Program Files\VODWerft`) und führe aus: `venv\Scripts\python.exe vodwerft\youtube_login.py "%LOCALAPPDATA%\VODWerft\uploader\secrets" --playlists`, dann im Browser bestätigen. Beim Server-Betrieb dasselbe in dem Ordner, in dem `client_secrets.json` liegt. (Der Haken im Assistenten ersetzt beim Speichern deine ganze Einrichtung, deshalb ist dieser Weg sicherer.)

**Zwei Einschränkungen von YouTube, die du kennen musst:**

- Videos, die ein **ungeprüftes** API-Projekt (erstellt nach dem 28.07.2020) hochlädt, werden von YouTube auf **privat** gesetzt. Um das aufzuheben, muss das Projekt eine Prüfung (Compliance Audit) bestehen. Bis dahin kannst du VODWerft nutzen, um fertige Videos vorzubereiten, musst sie aber selbst in YouTube Studio veröffentlichen oder manuell hochladen. Bereits gesperrte Videos lassen sich nicht per Einspruch freigeben.
- Im Teststatus des Zustimmungsbildschirms laufen Anmeldungen nach etwa sieben Tagen ab, dann musst du dich neu anmelden.

## 6. Alltag

- **Aufnehmen und ablegen:** Videos in den Aufnahmeordner des Spiels legen. Der Watcher erkennt neue Dateien, wartet bis sie fertig geschrieben sind und verarbeitet sie in Reihenfolge der Dateinamen.
- **Tray-Symbol:** zeigt den Status (z. B. „Bild und Ton werden analysiert“). Doppelklick öffnet das Dashboard.
- **Freigeben:** Fertige Folgen prüfst du und gibst sie frei. Für automatische Uploads legst du `upload-freigabe.flag` im Datenordner an.
- **Was bei Fehlern passiert:** Dateien, die der Server nicht hochladen kann, landen im Ordner `Pruefen`.

### Weitere Funktionen

- **Plan prüfen (optional):** Unter *Einstellungen → Schnitt* oder pro Spielprofil einschalten. Der Auftrag hält nach der Analyse an („Wartet auf dich“). „Plan prüfen öffnen“ zeigt, was automatisch entfernt wurde; du kannst weitere Bereiche entfernen oder welche behalten und bestätigst dann. Erst danach wird gerendert.
- **YouTube-Angaben pro Spiel:** *Spielprofile → YouTube*: Playlist, feste Tags und Collab-Partner. Für die Playlist braucht die Anmeldung ein zusätzliches Recht: Setze beim Anmelden im Assistenten den Haken „Auch Playlists zuordnen“. Bist du schon eingerichtet, melde dich einmal neu an, siehe Kapitel 5 („Playlist-Recht nachholen“). Die Einladung eines Collab-Partners und der „Titel des Spiels“ lassen sich nur in YouTube Studio setzen; die Auftragsdetails erinnern dich daran.
- **Verwendung von KI:** YouTube fragt bei jedem Video, ob KI Inhalte erzeugt oder verändert hat. VODWerft gibt dazu standardmäßig nichts an, du beantwortest es in Studio. Unter *Einstellungen → YouTube* lässt sich bei jedem Upload „Nein“ senden.
- **Übergänge an Schnitten:** *Einstellungen* oder Spielprofil: hart (Standard), Abblende, Weichzeichner, Weißblitz, Zoom, Pixel. Die Länge der Folge bleibt gleich.
- **Auftrag stoppen und Restzeit:** Der Knopf „Auftrag stoppen“ in der Auftragsliste beendet einen laufenden Auftrag; „Verlauf → Export erneut versuchen“ setzt ihn fort. Bei Schritten mit Zähler steht „noch etwa 12 Min.“ in den Auftragsdetails.
- **Bibliothek (Server-Betrieb):** Neben `Fertig` entsteht `Bibliothek\<Spiel>` mit einer Verknüpfung je hochgeladener Folge (Doppelklick öffnet das Video auf YouTube).
- **Meldungen und Speicherplatz:** Windows meldet, wenn ein Auftrag auf dich wartet oder fertig ist (*Einstellungen → Darstellung* schaltet das ab). Reicht der Platz auf dem Arbeitslaufwerk nicht, warnt das Dashboard und der Verlauf des Auftrags.

## 7. Häufige Probleme

| Problem | Lösung |
|---|---|
| Der Assistent meldet, `.upload` fehle | Freigabe prüfen: Laufwerk verbunden? Ordner auf dem Server angelegt? |
| Es passiert nichts | Im Tray-Menü Status ansehen; Datenordner öffnen, dort `production\watcher.log` lesen |
| Videos bleiben privat | Siehe Abschnitt 5, erste Einschränkung. Mit „Von Hand hochladen“ tritt das nicht auf |
| „Manuell hochladen“ fehlt im Tray-Menü | Der Eintrag erscheint nur in der Betriebsart „Von Hand“. Im Assistenten („Einrichtung öffnen“) prüfen |
| Die Liste unter „Manuell hochladen“ ist leer | Es erscheinen nur freigegebene, fertig bearbeitete Folgen. Mit „Aktualisieren“ neu laden |
| Die Playlist-Zuordnung schlägt fehl | Die Anmeldung hat das Recht „Playlists verwalten“ nicht. Erneut mit dem Playlist-Recht anmelden (Kapitel 5, „Playlist-Recht nachholen“) |
| Anmeldung abgelaufen | `request.token` neu erzeugen (Abschnitt 5, Punkt 6) |
| Zu wenig Grafikspeicher | Kleinere Modelle wählen oder anderen Rechner nutzen |
| Windows warnt beim Installer | Normal, der Installer ist noch nicht signiert. „Weitere Informationen“, „Trotzdem ausführen“ (Kapitel 2) |
| Der Installer meldet, Ollama oder ein Modell fehle | Ollama von ollama.com installieren und den Installer noch einmal starten. Fehlende Modelle lädt VODWerft beim ersten Start nach |
| Der Download der Modelle bricht ab oder ist sehr langsam | Verbindung prüfen, Installer erneut starten. Ollama setzt begonnene Downloads in der Regel fort |
| Das Tray-Symbol fehlt | Im Startmenü „VODWerft“ starten. Bei „Ausgeblendete Symbole“ neben der Uhr nachsehen |
| Der Einrichtungsassistent öffnet sich nicht | Im Tray-Menü „Einrichtung öffnen“ |
| Es läuft nichts, obwohl installiert | Datenordner öffnen (Tray-Menü), `production\watcher.log` lesen und im öffentlichen Repo als Issue melden, ohne Pfade oder Zugangsdaten |

## 8. Aktualisieren

VODWerft sucht beim Start und alle sechs Stunden auf GitHub nach einer neuen Version. Gibt es eine, steht im Dashboard „Update verfügbar“. Ein Klick zeigt zuerst, was neu ist; erst „Jetzt installieren“ lädt und installiert (die Prüfsumme wird kontrolliert). Läuft gerade ein Auftrag, kann das Update auf sein Ende warten. Du kannst den Installer auch von Hand starten: Den neuen `VODWerft-Setup.exe` einfach über die bestehende Installation laufen lassen. Die Einrichtung und deine Daten bleiben erhalten. Beende VODWerft vorher über das Tray-Menü („Beenden“).
