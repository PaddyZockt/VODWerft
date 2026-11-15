# VODWerft – Datenschutz (ENTWURF, rechtlich noch nicht geprüft)

> Dies ist ein Textentwurf. Vor der Veröffentlichung sollte ihn eine fachkundige Person prüfen. Platzhalter in `[eckigen Klammern]` ausfüllen.

## Wer ist verantwortlich?
[Name, Anschrift, E-Mail der verantwortlichen Person]

## Was VODWerft ist
VODWerft ist ein Programm, das auf **deinem eigenen Rechner und Server** läuft. Es gibt keine Cloud von uns: Wir betreiben keinen Server, auf dem deine Videos, Texte oder Zugangsdaten landen.

## Welche Daten verarbeitet das Programm?
- **Deine Videos und Tonspuren:** werden lokal auf deinem PC mit lokalen KI-Modellen (Ollama) analysiert. Sie verlassen deinen PC nur beim Upload zu YouTube.
- **Erzeugte Texte** (Titel, Beschreibung, Kapitel) und Vorschaubilder: lokal erzeugt.
- **YouTube-Zugangsdaten** (`client_secrets.json`, `request.token`): bleiben auf deinem Server. Sie werden nur verwendet, um Videos in deinem Namen hochzuladen und deren Daten zu ändern.
- **Protokolle:** lokale Logdateien auf deinem PC und Server.

## Weitergabe
VODWerft sendet von sich aus **keine Daten an uns oder Dritte**. Die einzige Verbindung nach außen ist die zu den Google-/YouTube-Diensten, die du selbst einrichtest. Dabei gelten die Datenschutzbestimmungen von Google. Du kannst den Zugriff jederzeit in deinem Google-Konto unter „Sicherheit → Apps mit Zugriff auf dein Konto“ widerrufen.

Modelle für Ollama werden beim ersten Start aus dem Internet geladen; dabei wird deine IP-Adresse an den Anbieter übermittelt.

## Genutzte YouTube-Berechtigungen
Hochladen von Videos und Verwalten von Videodaten (Titel, Beschreibung, Vorschaubild, Veröffentlichungszeit) für deinen eigenen Kanal.

## Deine Rechte
Da wir keine Daten von dir erhalten, gibt es bei uns nichts zu löschen. Deine Daten löschst du, indem du den Datenordner und die Server-Ordner entfernst und den Zugriff im Google-Konto widerrufst.

## Kontakt
[E-Mail]
