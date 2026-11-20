"""Update fuer die oeffentliche Version ueber GitHub-Releases.

Das Programm fragt die Release-Liste des Repositorys ab, nimmt die hoechste Version (SemVer, Betas zaehlen mit) und
vergleicht sie mit der eigenen Version (Datei VERSION). Ist sie neuer, laedt `prepare` das Setup-Programm
(`VODWerft-Setup.exe`) nach TEMP, prueft Groesse und Pruefsumme und `start` fuehrt es aus. Das Setup fragt selbst nach
Administratorrechten und schliesst/startet das Programm neu.

Gleiche Schnittstelle wie self_update.py (private Version): UpdateError, installed(), check(), prepare(), start().
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import patch_notes
import update_cleanup
import version

DEFAULT_REPO = "PaddyZockt/VODWerft"
ASSET = "VODWerft-Setup.exe"
PACKAGE_PREFIX = "vodwerft-update-"   # Ordner im Temp-Verzeichnis, in den `prepare` das Setup lädt
KEEP_SECONDS = 3600                  # jünger als eine Stunde: könnte ein Setup sein, das gerade noch läuft
API = "https://api.github.com/repos/{repo}/releases?per_page=20"
TIMEOUT = 20
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class UpdateError(Exception):
    """Fehler mit einer Meldung, die man dem Nutzer zeigen kann."""


def installed():
    value = version.read()
    return "" if value == "unbekannt" else value


def sort_key(text):
    """Sortierschluessel nach SemVer: 0.1.0-beta.10 > 0.1.0-beta.9, und 0.1.0 > 0.1.0-beta.x."""
    parsed = version.parse(text)
    if not parsed:
        return None
    major, minor, patch, pre = parsed
    if pre is None:
        return (major, minor, patch, 1, ())
    parts = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))
    return (major, minor, patch, 0, parts)


def _request(url):
    return urllib.request.Request(url, headers={"User-Agent": "VODWerft-Updater", "Accept": "application/vnd.github+json"})


def releases(repo=DEFAULT_REPO):
    try:
        with urllib.request.urlopen(_request(API.format(repo=repo)), timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise UpdateError(f"GitHub nicht erreichbar: {error}") from None


def newest(items):
    """Neuestes veroeffentlichtes Release mit Setup-Programm als (Version, Release) oder ('', None)."""
    best = None
    for item in items:
        tag = str(item.get("tag_name", "")).lstrip("v")
        key = sort_key(tag)
        if item.get("draft") or key is None or not any(a.get("name") == ASSET for a in item.get("assets", [])):
            continue
        if best is None or key > best[0]:
            best = (key, tag, item)
    return (best[1], best[2]) if best else ("", None)


def cleanup(temp=None, *, now=None, keep=()):
    """Löscht Setup-Pakete früherer Updates (`vodwerft-update-*` im Temp-Ordner, älter als eine Stunde). Bisher blieb nach
    jedem Update eine Setup-Datei von mehreren MB liegen. Nie ein Fehler: Das Aufräumen darf kein Update verhindern."""
    now = time.time() if now is None else now
    protected = {Path(k).resolve() for k in keep}
    try:
        folders = update_cleanup._folders(temp or tempfile.gettempdir())
    except OSError:
        return
    for folder in folders:
        try:
            if (folder.name.startswith(PACKAGE_PREFIX) and folder.resolve() not in protected
                    and now - folder.stat().st_mtime > KEEP_SECONDS):
                update_cleanup.rmtree(folder)
        except OSError:
            continue  # gesperrt (läuft noch?): die übrigen kommen trotzdem dran


def check(repo=DEFAULT_REPO):
    """Gibt (installiert, neueste, verfuegbar) zurueck."""
    cleanup()
    current = installed()
    latest, _ = newest(releases(repo))
    available = bool(latest) and (not current or (sort_key(latest) or ()) > (sort_key(current) or ()))
    return current, latest, available


def resolve(label, repo=DEFAULT_REPO):
    """Gleiche Schnittstelle wie self_update.resolve: beim Einspielen den neuesten Stand nehmen. Ohne Verbindung
    bleibt es beim gemerkten Stand."""
    try:
        latest, _ = newest(releases(repo))
    except UpdateError:
        return label
    return latest if latest and (sort_key(latest) or ()) > (sort_key(label) or ()) else label


def notes(label, repo=DEFAULT_REPO):
    """Patch Notes für das Update `label`: die Beschreibungen aller Releases, die neuer sind als die installierte
    Version (bis einschließlich `label`). Nie ein Fehler: ohne Verbindung kommt ein leerer Text."""
    try:
        return patch_notes.from_releases(releases(repo), installed(), label)
    except UpdateError:
        return ""


def prepare(latest, repo=DEFAULT_REPO):
    """Laedt das Setup-Programm der angegebenen Version und gibt den Dateipfad zurueck."""
    tag, release = newest(releases(repo))
    if release is None or tag != latest:
        raise UpdateError("Diese Version ist nicht mehr verfuegbar. Bitte erneut nach Updates suchen.")
    asset = next(a for a in release["assets"] if a.get("name") == ASSET)
    cleanup()
    target = Path(tempfile.mkdtemp(prefix=PACKAGE_PREFIX)) / ASSET
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(_request(asset["browser_download_url"]), timeout=TIMEOUT) as response, \
                open(target, "wb") as output:
            while True:
                block = response.read(1024 * 256)
                if not block:
                    break
                output.write(block)
                digest.update(block)
    except (urllib.error.URLError, OSError) as error:
        raise UpdateError(f"Der Download ist fehlgeschlagen: {error}") from None
    if asset.get("size") and target.stat().st_size != asset["size"]:
        raise UpdateError("Der Download ist unvollstaendig. Bitte erneut versuchen.")
    expected = str(asset.get("digest") or "")
    if expected.startswith("sha256:") and expected[7:].lower() != digest.hexdigest():
        raise UpdateError("Die Pruefsumme des Downloads stimmt nicht. Es wird nichts installiert.")
    return target


def start(package):
    """Startet das Setup-Programm; es fragt selbst nach Administratorrechten, beendet laufende Teile von VODWerft (nicht,
    solange ein Auftrag läuft) und startet das Programm danach mit den Rechten des Nutzers wieder."""
    if sys.platform != "win32":
        raise UpdateError("Das Einspielen funktioniert nur unter Windows.")
    subprocess.Popen([str(package), "/SILENT"], cwd=str(Path(package).parent))
