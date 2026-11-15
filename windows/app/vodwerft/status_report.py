"""Publish Nightcut phase information without copying transcripts or raw logs."""
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

from atomic import atomic_write
from file_ready import unlocked
from bundle import media_extensions, mission_title
from game_profiles import load_profiles
from version import compatible, read as program_version
from server_status import evaluate as server_state

PHASES = {
    "audio": "Tonspur wird gelesen",
    "scan": "Bild und Ton werden analysiert",
    "transcript": "Sprache wird transkribiert",
    "voices": "Gesprächspassagen werden erkannt",
    "cuts": "Schnittstellen werden ermittelt",
    "episodes": "Folgen werden eingeteilt",
    "metadata": "Titel, Beschreibung und Kapitel werden erstellt",
    "candidates": "Clip-Kandidaten werden gesucht",
    "vision": "Clip-Kandidaten werden gesichtet",
    "edit": "Clips werden ausgewählt",
    "render": "Clips werden gerendert",
    "shorts": "Hochkant-Clips und Untertitel werden gerendert",
    "export": "Schnittlisten werden exportiert",
}
RENDER = re.compile(r"^Folge (\d+), (\d+) von (\d+)$")
PHASE = re.compile(r"^\s*▶\s+(\w+)")
PROGRESS = re.compile(r"^(?:(?:transcript|vision)\s+)?(\d+)/(\d+)$")
ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
CHECKSUM_STATUS = "checksum-status"
# Texte der Eingangs-Meldung. Die Discord-Seite erkennt sie am genauen Wortlaut: nicht umformulieren.
COPY_WAIT = "Datei erkannt. Warte auf den Abschluss des Kopiervorgangs."
QUEUED = "Datei erkannt. Kopie fertig, wartet auf die Verarbeitung des vorherigen Videos."
READY = "Datei erkannt. Kopie fertig, die Verarbeitung startet gleich."
# str(Quelldatei) -> ((Größe, Änderungszeit), monotonic-Zeitpunkt, seit dem die Datei unverändert ist)
_UNCHANGED_SINCE = {}
# str(Arbeitsordner) -> True, wenn dieses Profil gerade verarbeitet. Der Watcher arbeitet alle Profile
# nacheinander in einem Prozess ab: Eine fertig kopierte Datei wartet auch auf Aufnahmen anderer Profile.
_PROFILE_BUSY = {}


def copy_finished(source, signature, minimum, now):
    """True, wenn die Datei seit mindestens `minimum` Sekunden unverändert ist (wie watch_folder.scan)."""
    key = str(source)
    saved = _UNCHANGED_SINCE.get(key)
    if saved is None or saved[0] != signature:
        _UNCHANGED_SINCE[key] = saved = (signature, now)
    return now - saved[1] >= minimum


def checksum_status(work):
    try:
        data = json.loads((work / f"{CHECKSUM_STATUS}.json").read_text(encoding="utf-8"))
        if 0 <= time.time() - data["updated"] < 30:
            return data
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return None


def review_reason(path):
    """Letzte Fehlermeldung aus dem Auftragsprotokoll (z. B. "Unbekannte Mehrspurbelegung. ..."), sonst leer."""
    try:
        with path.open("rb") as handle:
            handle.seek(max(0, path.stat().st_size - 64 * 1024))
            lines = handle.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        found = re.fullmatch(r"\s*[A-Za-z_.]*(?:Error|Exception): (.{3,160})", ANSI.sub("", line))
        if found:
            return found[1].strip()
    return ""


def log_phase(path, fallback):
    if not path.is_file():
        return fallback
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - 256 * 1024))
        lines = handle.read().decode("utf-8", "replace").splitlines()
    progress = None
    for line in reversed(lines):
        line = ANSI.sub("", line).strip()
        counter = PROGRESS.fullmatch(line)
        if counter and progress is None:
            progress = f" ({counter[1]} von {counter[2]})"
        episode = RENDER.fullmatch(line)
        if episode:
            number, current, total = episode.groups()
            return f"Folge {number} wird gerendert ({current} von {total})"
        stage = PHASE.match(line)
        if stage and stage[1] in PHASES:
            detail = PHASES[stage[1]]
            if progress and stage[1] in ("transcript", "vision", "cuts"):
                detail += progress
            return detail
    return fallback


def render_percent(job_dir):
    """Fortschritt des laufenden Folgen-Renders in Prozent (in 5er-Schritten) oder None.

    Quelle sind dieselben Dateien wie im Dashboard: render-state.json und render-progress.txt des Render-Ordners."""
    try:
        for state_file in Path(job_dir).glob("episode-*/render-state.json"):
            state = json.loads(state_file.read_text(encoding="utf-8"))
            total = float(state["total_seconds"])
            if total <= 0:
                continue
            try:
                report = state_file.with_name("render-progress.txt").read_text(encoding="ascii", errors="replace")
            except OSError:
                report = ""
            ticks = re.findall(r"(?m)^out_time_us=(\d+)$", report)
            elapsed = min(float(state["segment_seconds"]), int(ticks[-1]) / 1_000_000) if ticks else 0.0
            percent = int(100 * (float(state["finished_seconds"]) + elapsed) / total)
            return max(0, min(100, percent // 5 * 5))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def intake_key(source, prefix):
    return f"{prefix}-in-" + hashlib.sha256(str(source).casefold().encode()).hexdigest()[:20]


def publish(directory, key, data):
    payload = json.dumps(data, ensure_ascii=False)
    target = directory / f"{key}.json"
    if target.is_file() and target.read_text(encoding="utf-8") == payload:
        return
    atomic_write(target, payload)


def publish_status(config, directory, *, clock=time.monotonic):
    work = Path(config["work"])
    checksum = checksum_status(work)
    prefix = config.get("job_prefix", "se")
    series = {"series": config["series"]} if prefix != "se" else {}
    jobs = []
    transfers = {}
    pending = []
    fingerprints = {}
    processed = {}
    if (work / "jobs.sqlite3").is_file():
        with closing(sqlite3.connect(work / "jobs.sqlite3", timeout=2)) as db:
            jobs = db.execute(
                "SELECT key, source, recordings.status, clips.status FROM recordings "
                "LEFT JOIN clips USING (key) ORDER BY recordings.rowid DESC"
            ).fetchall()
            fingerprints = {path: (key, size, modified, inode)
                            for path, key, size, modified, inode in db.execute(
                                "SELECT path, key, size, modified, inode FROM fingerprints "
                                "JOIN recordings USING (key) WHERE recordings.status='ready'")}
            for (episode,) in db.execute("SELECT episode FROM handoffs WHERE status='sending'"):
                batch, _, number = episode.rpartition("-ep")
                if number.isdecimal():
                    transfers[batch] = number
    known_names = {Path(source).name.casefold() for _, source, _, _ in jobs}
    inbox = Path(config["input"])
    clips_enabled = bool(config.get("clips_config"))
    own_busy = any(status == "processing"
                   or (clips_enabled and status == "ready" and clips in (None, "retrying"))
                   for _, _, status, clips in jobs)
    own_work = str(config["work"])
    _PROFILE_BUSY[own_work] = own_busy
    busy = own_busy or any(value for work, value in _PROFILE_BUSY.items() if work != own_work)
    minimum = config.get("stable_seconds", 90)
    seen = set()
    earlier_waiting = False
    # Reihenfolge nach Dateiname wie im Watcher: eine frühere Datei wird zuerst verarbeitet.
    for source in sorted(inbox.iterdir(), key=lambda path: path.name.casefold()):
        if source.suffix.lower() not in media_extensions or source.is_symlink() or not source.is_file():
            continue
        seen.add(str(source))
        saved = fingerprints.get(str(source))
        if saved:
            stat = source.stat()
            if saved[1:] == (stat.st_size, stat.st_mtime_ns, stat.st_ino):
                processed.setdefault(saved[0], source.name)
                continue
        if source.name.casefold() not in known_names or saved:
            needs_title = config.get("mission_export") and not mission_title(source)
            title_hint = "Datei erkannt. Bitte den Namen der Aufnahme im Dateinamen prüfen."
            try:
                stat = source.stat()
            except OSError:
                continue  # gerade verschoben oder gelöscht
            # Eine Datei, die noch zum Schreiben offen ist, wird gerade kopiert, auch wenn Größe und Zeit stillstehen.
            finished = copy_finished(source, (stat.st_size, stat.st_mtime_ns), minimum, clock()) and unlocked(source)
            if needs_title:
                detail = title_hint
            elif checksum and checksum.get("source") == source.name:
                percent = re.search(r"(\d+) %$", checksum.get("detail", ""))
                detail = f"Prüfsumme wird abgeglichen ({percent[1]} von 100)" if percent else "Prüfsumme wird abgeglichen"
            elif finished:
                # Kopie fertig: Die Datei wartet nur noch, bis sie an der Reihe ist.
                detail = QUEUED if busy or checksum or earlier_waiting else READY
            else:
                detail = COPY_WAIT
            if not needs_title:
                earlier_waiting = True
            pending.append({"source": source.name, "detail": "Dateiname prüfen" if needs_title else
                            "Datei erkannt · wartet auf Verarbeitung"})
            publish(directory, intake_key(source, prefix), {
                "source": source.name, "detail": detail, **series,
            })
    for name in [name for name in _UNCHANGED_SINCE if Path(name).parent == inbox and name not in seen]:
        del _UNCHANGED_SINCE[name]  # Datei ist aus dem Eingang verschwunden
    active = []
    for key, source, status, clips in jobs[:50]:
        if not re.fullmatch(rf"{re.escape(prefix)}-[0-9a-f]{{20}}", key):
            continue
        approval = Path(work) / key / "approval"
        awaiting_approval = status == "ready" and any(
            not path.with_suffix(".approved").is_file() and path.is_file()
            for path in approval.glob(f"{key}-ep*.draft.json"))
        if status == "awaiting_start":
            detail = "Aufnahme erkannt. Wartet auf Missionsbeginn"
        elif status == "retry":
            detail = "Aufnahme erkannt. Wartet auf Export-Wiederholung"
        elif status == "processing":
            detail = log_phase(work / f"{key}.log", "Aufnahme erkannt, Bearbeitung wird vorbereitet")
        elif status == "review":
            reason = review_reason(Path(work) / f"{key}.log")
            detail = "Bearbeitung braucht eine Prüfung" + (f": {reason} Dashboard, Verlauf, Export erneut versuchen." if reason else "")
        elif clips is None and config.get("clips_config"):
            detail = log_phase(work / f"{key}.clips.log", "Folgen fertig, Hochkant-Clips werden vorbereitet")
        elif clips == "review":
            detail = "Folgen fertig, Hochkant-Clips brauchen eine Prüfung"
        elif clips == "retry":
            detail = "Hochkant-Clips · wartet auf neuen Versuch"
        elif clips == "retrying":
            detail = "Hochkant-Clips werden erneut erstellt"
        elif key in transfers:
            detail = f"Folge {transfers[key]} wird an den Server übertragen"
        elif awaiting_approval:
            detail = "Aufnahme erkannt. Folgen warten auf Upload-Freigabe"
        elif (directory / f"verified-{key}.json").is_file():
            detail = "YouTube-Prüfung abgeschlossen"
        else:
            detail = "Bearbeitung abgeschlossen"
        payload = {"source": Path(source).name, "detail": detail,
                   "intake": intake_key(source, prefix), **series}
        if status == "processing":
            payload["run"] = "long"
            if detail.startswith("Folge ") and " wird gerendert" in detail:
                percent = render_percent(Path(work) / key)
                if percent is not None:
                    payload["percent"] = percent
        elif status == "ready" and clips in (None, "retrying") and config.get("clips_config"):
            payload["run"] = "clips"
        publish(directory, key, payload)
        if (status == "processing" or key in transfers
                or (status == "ready" and clips in (None, "retrying") and config.get("clips_config"))):
            active.append({"source": Path(source).name, "detail": detail})
        elif status in ("awaiting_start", "retry", "review") or awaiting_approval:
            pending.append({"source": Path(source).name, "detail": detail.removeprefix("Aufnahme erkannt. ")})
    publish(work, "processed-inputs", {"jobs": processed, "updated": int(time.time())})
    return active, pending, list(processed.values())


if __name__ == "__main__":
    config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
    directory = Path(config["upload_incoming"]).parent / ".status"
    local = Path(config["work"])
    last_server = None
    while True:
        active, pending, processed, errors = [], [], [], []
        for profile in load_profiles(Path(sys.argv[1])):
            checksum = checksum_status(Path(profile["work"]))
            if checksum:
                active.append(checksum)
            try:
                processing, waiting, known = publish_status(profile, directory)
                active.extend(processing)
                pending.extend(waiting)
                processed.extend(known)  # bereits erledigte Aufnahmen sind kein Status: im Tray steht dann "Wartet auf neue Datei"
            except (OSError, sqlite3.Error) as error:
                errors.append(profile["series"])
                print(f"Status konnte nicht gespeichert werden ({type(error).__name__}).", flush=True)
        status = (active or pending or [{"detail": "Wartet auf neue Datei"}])[0]
        if errors and not active:
            status = {"detail": "Status prüfen · " + ", ".join(errors)}
        try:
            server = json.loads((directory / "server-version.json").read_text(encoding="utf-8")).get("version")
        except (OSError, ValueError, AttributeError):
            server = None  # aelterer Server meldet keine Version: kein Hinweis
        if server and not compatible(program_version(), server) and not active:
            status = {"detail": f"Server-Version {server} passt nicht zu {program_version()}: bitte Server aktualisieren"}
        try:
            state = server_state(directory, program_version(), direct=config.get("upload_mode") in ("direct", "manual"))
            if state["state"] == "offline" and last_server and time.time() - last_server[0] < 90:
                state = last_server[1]  # kurzer Aussetzer der Netzwerkfreigabe: erst nach 90 s als nicht erreichbar melden
            elif state["state"] != "offline":
                last_server = (time.time(), state)
            publish(local, "server-status", {**state, "updated": int(time.time())})
        except OSError:
            pass
        try:
            status = {**status, "updated": int(time.time())}
            publish(local, "tray-status", status)
            publish(directory, "windows-status", status)
        except OSError:
            pass
        time.sleep(10)
