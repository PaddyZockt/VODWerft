"""Auftragsdaten für das Dashboard: reine Logik ohne Tk (lesen, zusammenfassen, gruppieren).

NightcutDashboard.pyw zeigt nur noch an, was hier ermittelt wird. Dadurch lassen sich Statusregeln,
Gruppierung und Texte ohne Fenster testen.
"""
import json
import logging
import os
import re
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from status_report import log_phase
from release_slots import read_manual
from game_profiles import recording_settings
from job_cleanup import BATCH, policy as cleanup_policy
from episode_approval import approval_path, draft_path

LOG = logging.getLogger("nightcut.oberflaeche")
LOG_NAME = "oberflaeche.log"
DETAILS = "Details stehen im Protokoll."
_reported = {}


def set_log_file(directory):
    """Technische Fehlertexte der Oberfläche landen in `oberflaeche.log` im Datenordner."""
    path = Path(directory) / LOG_NAME
    try:
        if not any(getattr(handler, "baseFilename", None) == str(path) for handler in LOG.handlers):
            handler = logging.FileHandler(path, encoding="utf-8", delay=True)
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
            LOG.addHandler(handler)
            LOG.setLevel(logging.INFO)
            LOG.propagate = False
    except OSError:
        pass
    return path


def problem(sentence, error=None, context=None):
    """Ein deutscher Satz für die Anzeige; der technische Fehlertext geht nur ins Protokoll.

    Wiederholt sich derselbe Fehler (z. B. bei jeder Aktualisierung), wird er nur einmal protokolliert."""
    if error is not None:
        key, text = context or sentence, f"{type(error).__name__}: {error}"
        if _reported.get(key) != text:
            _reported[key] = text
            try:
                LOG.error("%s | %s", key, text)
            except Exception:  # noqa: BLE001 - das Protokoll darf die Anzeige nie stören
                pass
    return f"{sentence} {DETAILS}"


@dataclass(frozen=True)
class JobRow:
    """Eine Aufnahme in der Auftragsliste."""
    key: str
    series: str
    source: Path
    inbox: Path
    folder: Path
    detail: str
    updates: list = field(default_factory=list)   # Meldungen je Folge (Status, Termin, YouTube-ID)
    review: tuple | None = None                   # (Ordner, Folgenplan, Text) einer laufenden Korrektur
    cleanup_supported: bool = False
    cleanup_mode: str = "manual"
    cleanup_verified: bool = False
    clips_retry: bool = False                     # Hochkant-Clips können erneut versucht werden

    @property
    def name(self):
        return self.source.name

    @property
    def work(self):
        return self.folder.parent

    @property
    def bucket(self):
        return bucket_of(self.detail)

    @property
    def awaiting_mission(self):
        return self.detail == AWAITING_MISSION

    @property
    def needs_render_check(self):
        return self.detail == RENDER_CHECK


AWAITING_MISSION = "Wartet auf Missionsbeginn"
RENDER_CHECK = "Bearbeitung prüfen · Protokoll öffnen"
GROUPS = (("work", "In Arbeit", True), ("todo", "Wartet auf dich", True), ("done", "Fertig", False))
EMPTY_TEXT = "Noch keine Aufnahmen. Lege ein Video in den Eingangsordner."


def bucket_of(status):
    """In welche Gruppe gehört ein Auftrag: läuft von selbst ("work"), braucht dich ("todo") oder ist fertig ("done")."""
    if "prüfen" in status or "Wartet auf" in status or "Freigabe" in status:
        return "todo"
    if "bestätigt" in status or "abgeschlossen" in status:
        return "done"
    return "work"


def grouped(rows):
    """Aufträge nach Gruppe: {"work": [...], "todo": [...], "done": [...]} in Listenreihenfolge."""
    buckets = {name: [] for name, _, _ in GROUPS}
    for row in rows:
        buckets[row.bucket].append(row)
    return buckets


def done_by_game(rows):
    """Fertige Aufträge je Spiel, Spiele alphabetisch, neueste Aufnahme zuerst."""
    return [(game, sorted((row for row in rows if row.series == game), key=lambda row: row.name, reverse=True))
            for game in sorted({row.series for row in rows})]


def counts_text(buckets):
    return "   ·   ".join((f"{len(buckets['work'])} in Arbeit", f"{len(buckets['todo'])} warten auf dich",
                           f"{len(buckets['done'])} fertig"))


def preferred(rows, previous=None):
    """Welcher Auftrag soll ausgewählt sein: der bisherige, sonst der erste, der nicht fertig ist."""
    keys = [row.key for row in rows]
    if previous in keys:
        return previous
    return next((row.key for row in rows if row.bucket != "done"), keys[0] if keys else None)


def percent(detail):
    """Renderfortschritt aus dem Statustext (0-100) oder None."""
    match = re.search(r" · (\d+) % · ", detail)
    return int(match[1]) if match else None


UPLOAD = {
    "uploading": "Upload läuft", "uploaded": "Upload bestätigt",
    "review": "Upload prüfen", "auth": "YouTube-Anmeldung erforderlich",
    "transfer": "Übertragung an den Server", "queued": "Wartet auf Server-Uploader",
    "awaiting_date": "Wartet auf Veröffentlichungstermin",
    "local_ready": "Export fertig · Übergabe ausstehend", "planned": "Export ausstehend",
    "approval": "Wartet auf Freigabe", "cancelled": "Abgebrochen",
}
UPLOAD_REASON = {
    "network_interrupted": "Netzwerk unterbrochen. Der Upload setzt automatisch fort.",
    "youtube_temporarily_unavailable": "YouTube antwortet vorübergehend nicht. Der Upload setzt automatisch fort.",
    "youtube_auth_required": "YouTube erneut anmelden. Die Upload-Sitzung bleibt gespeichert.",
    "youtube_session_expired_or_unknown": "Upload-Sitzung abgelaufen. Bitte in YouTube Studio prüfen.",
    "youtube_schedule_not_confirmed": "YouTube hat den Termin nicht bestätigt.",
    "publication_date_passed": "Der Veröffentlichungstermin ist verstrichen.",
    "thumbnail_retry": "Thumbnail wird für das vorhandene YouTube-Video erneut übertragen.",
}
CUTS = {
    "silence": "Sprechpause", "menu": "Menü", "loading": "Ladebildschirm",
    "pause": "Pause", "black": "Schwarzbild", "afk": "Standbild / AFK",
}


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def timestamp(seconds):
    hours, rest = divmod(round(seconds), 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{seconds:02}"


def clock_time(epoch):
    """Datum und Uhrzeit (Ortszeit) eines Zeitstempels, z. B. 15.11. 18:25:38. Leer bei ungültigem Wert."""
    from datetime import datetime
    try:
        return datetime.fromtimestamp(float(epoch)).strftime("%d.%m. %H:%M:%S")
    except (OverflowError, OSError, ValueError, TypeError):
        return ""


def phase_engine(detail):
    phase = detail.casefold()
    if "transkrib" in phase or "gesprächspassagen" in phase:
        return "Whisper Large V3 Turbo · lokale Spracherkennung"
    if "schnittstellen" in phase or "gesichtet" in phase:
        return "Nightcut · Qwen 2.5 VL 7B für die Bildprüfung"
    if "beschreibung" in phase or "clips werden ausgewählt" in phase:
        return "Qwen3 14B · Text und Auswahl"
    if "render" in phase:
        return "FFmpeg · NVIDIA-Hardware-Encoder"
    if "upload" in phase or "server" in phase or "unraid" in phase:  # leak-ok: aeltere Verlaufseintraege
        return "Server · YouTube-Uploader"
    return "Nightcut · Auftragssteuerung"


def progress_detail(folder):
    for status_file in folder.glob("episode-*/render-state.json"):
        state = read_json(status_file, {})
        if not state:
            continue
        try:
            report = status_file.with_name("render-progress.txt").read_text(encoding="ascii")
        except OSError:
            report = ""
        ticks = re.findall(r"(?m)^out_time_us=(\d+)$", report)
        elapsed = min(state["segment_seconds"], int(ticks[-1]) / 1_000_000) if ticks else 0
        total_done = state["finished_seconds"] + elapsed
        percentage = int(100 * total_done / state["total_seconds"])
        return (f"Rendern · Abschnitt {state['segment']} von {state['segments']} · "
                f"{min(100, percentage)} % · {timestamp(total_done)} von {timestamp(state['total_seconds'])}")
    return ""


def file_activity(path, samples):
    try:
        with path.open("rb") as handle:
            size = os.fstat(handle.fileno()).st_size
    except OSError:
        return ""
    now = time.monotonic()
    previous, observed, changed = samples.get(path, (size, now, now))
    if size > previous and now > observed:
        samples[path] = (size, now, now)
        return f" · Datei wächst ({(size - previous) / (now - observed) / 1_000_000:.1f} MB/s)"
    samples[path] = (size, now, changed)
    if now - changed >= 30:
        return f" · seit {int(now - changed)} s kein Schreibfortschritt beobachtet"
    return ""


def correction(folder, samples):
    for plan in sorted(folder.glob("korrektur-*/episodes.json"), reverse=True):
        review = plan.parent
        episodes = read_json(plan, [])
        if not episodes or not episodes[0]["pieces"]:
            continue
        final = next(review.glob("*.mp4"), None)
        if final:
            return review, episodes, "Korrektur gerendert"
        segments = sorted(review.glob("episode-*/segment-*.mp4"))
        errors = [p for p in review.glob("render-*.stderr.log") if p.stat().st_size]
        if errors:
            return review, episodes, "Korrektur prüfen · Renderprotokoll"
        live = progress_detail(review)
        if live:
            return review, episodes, "Korrektur · " + live
        if segments:
            segment = max(segments, key=lambda p: p.name)
            number = int(segment.stem.split("-")[-1])
            total = len(episodes[0]["pieces"])
            detail = f"Korrektur · zuletzt Renderabschnitt {number} von {total}"
            return review, episodes, detail + file_activity(segment, samples)
        return review, episodes, "Korrektur vorbereitet"
    return None


def episode_updates(folder, key, batch, handoffs, remote, manual):
    first, count = batch or (None, None)
    if not count:
        return [{**notice, "job_id": stem} for stem, notice in sorted(remote.items()) if stem.startswith(key + "-ep")]
    result = []
    for number in range(first, first + count):
        stem = f"{key}-ep{number:02d}"
        transfer = handoffs.get(stem)
        if transfer == "sending":
            status = "transfer"
        elif transfer == "sent":
            status = "queued"
        elif draft_path(folder / f"{stem}.mp4").is_file() and not approval_path(folder / f"{stem}.mp4").is_file():
            status = "approval"
        elif all((folder / f"{stem}{ext}").is_file() for ext in (".mp4", ".jpg", ".json")):
            status = "awaiting_date" if manual is not None and stem not in manual else "local_ready"
        else:
            status = "planned"
        result.append({"episode": number, "status": status, "publish_at": (manual or {}).get(stem),
                       **remote.get(stem, {}), "job_id": stem})
    return result


def snapshot(profiles, samples=None):
    rows, warnings = [], []
    if samples is None:
        samples = {}
    for config in profiles:
        work, inbox = Path(config["work"]), Path(config["input"])
        notices = Path(config["upload_incoming"]).parent / ".status"
        try:
            with closing(sqlite3.connect(f"{(work / 'jobs.sqlite3').as_uri()}?mode=ro", uri=True, timeout=2)) as db:
                jobs = db.execute(
                    "SELECT key, source, recordings.status, clips.status FROM recordings "
                    "LEFT JOIN clips USING (key) ORDER BY recordings.rowid DESC LIMIT 40"
                ).fetchall()
                handoffs = dict(db.execute("SELECT episode, status FROM handoffs"))
        except sqlite3.Error as error:
            problem("Auftragsdaten nicht erreichbar.", error, f"{config['series']}: Auftragsdaten")
            warnings.append(f"{config['series']}: Auftragsdaten sind gerade nicht erreichbar")
            continue
        batches, manual = {}, {}
        if config.get("state") and (series_db := Path(config["state"])).is_file():
            try:
                with closing(sqlite3.connect(series_db.as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
                    batches = {name: (first, count) for name, first, count in db.execute(
                        "SELECT name, first_episode, count FROM batches WHERE series=?", (config["series"],))}
                    manual = read_manual(db)
            except sqlite3.Error as error:
                problem("Folgenplanung nicht erreichbar.", error, f"{config['series']}: Folgenplanung")
                warnings.append(f"{config['series']}: Folgenplanung ist gerade nicht erreichbar")
        try:
            remote = {p.stem: read_json(p, {}) for p in notices.glob(f"{config.get('job_prefix', 'se')}-*-ep*.json")}
            if not notices.is_dir():
                warnings.append(f"{config['series']}: Server nicht erreichbar")
        except OSError:
            remote = {}
            warnings.append(f"{config['series']}: Server nicht erreichbar")
        processed = read_json(work / "processed-inputs.json", {})
        known_inputs = processed.get("jobs", {}) if 0 <= time.time() - processed.get("updated", 0) < 45 else {}
        for key, source, state, clips in jobs:
            folder = work / key
            job_config = recording_settings(config, key)
            updates = episode_updates(folder, key, batches.get(key), handoffs, remote,
                                      manual if job_config.get("manual_release") else None)
            if state == "processing":
                detail = progress_detail(folder) or log_phase(work / f"{key}.log", "Nightcut bearbeitet die Aufnahme")
            elif state == "review":
                detail = RENDER_CHECK
            elif state == "retry":
                detail = "Export-Wiederholung angefordert"
            elif state == "awaiting_start":
                detail = AWAITING_MISSION
            elif config.get("clips_config") and clips is None:
                detail = log_phase(work / f"{key}.clips.log", "Hochkant-Clips werden vorbereitet")
            elif clips == "review":
                detail = "Hochkant-Clips prüfen · Protokoll öffnen"
            elif clips == "retry":
                detail = "Hochkant-Clips · wartet auf neuen Versuch"
            elif clips == "retrying":
                detail = "Hochkant-Clips werden erneut erstellt"
            elif any(k.startswith(key + "-ep") and v == "sending" for k, v in handoffs.items()):
                detail = "Übertragung an den Server"
            elif any(n.get("status") in {"review", "auth"} for n in updates):
                detail = "Upload prüfen"
            elif any(n.get("status") == "uploading" for n in updates):
                detail = "YouTube-Upload läuft"
            elif updates and all(n.get("status") == "uploaded" for n in updates):
                detail = "Upload bestätigt"
            elif any(n.get("status") == "approval" for n in updates):
                detail = "Folgen warten auf Freigabe"
            else:
                detail = "Bearbeitung abgeschlossen"
            review = correction(folder, samples)
            if review:
                detail = review[2]
                replacement = read_json(review[0] / "upload-job.json", {}).get("key")
                if replacement and replacement in remote:
                    updates = [{**remote[replacement], "job_id": replacement}]
                    detail = UPLOAD.get(updates[0].get("status"), detail)
            if key in known_inputs and detail in ("Upload bestätigt", "Bearbeitung abgeschlossen"):
                detail += " · Bereits verarbeitet"
            supported = bool(BATCH.fullmatch(key) and not review and key not in config.get("retention_hold", ()))
            mode = cleanup_policy(notices, key)["mode"] if supported else "manual"
            verified = supported and (notices / f"verified-{key}.json").is_file()
            rows.append(JobRow(key=key, series=config["series"], source=Path(source), inbox=inbox, folder=folder,
                               detail=detail, updates=updates, review=review, cleanup_supported=supported,
                               cleanup_mode=mode, cleanup_verified=bool(verified),
                               clips_retry=bool(state == "ready" and clips == "review" and Path(source).is_file())))
    return rows, warnings


def describe(row):
    """Text der Detailansicht: Titelzeile, Status, Folgen und Schnittplan."""
    folder, notices, review = row.folder, row.updates, row.review
    lines = [f"{row.series}  ·  {row.name}", row.detail, f"Werkzeug dieser Phase: {phase_engine(row.detail)}"]
    if notices:
        lines.append("FOLGEN")
    for index, notice in enumerate(notices, 1):
        stamp = notice.get("publish_at")
        date = f" · {datetime.fromisoformat(stamp).astimezone():%d.%m.%Y %H:%M}" if stamp else ""
        label = f"Folge {notice['episode']:02d}" if "episode" in notice else f"Upload {index}"
        lines.append(f"{label} · {UPLOAD.get(notice.get('status'), 'Status unbekannt')}{date}")
    lines.append("SCHNITTPLAN · Startzeit anklicken, um das Original in VLC zu öffnen")
    if review:
        pieces = review[1][0]["pieces"]
        start = pieces[0]["start"]
        if start:
            lines.append(f"0:00:00 bis {timestamp(start)}   ·   Vorspann entfernt")
        for previous, current in zip(pieces, pieces[1:]):
            lines.append(f"{timestamp(previous['end'])} bis {timestamp(current['start'])}   ·   entfernt")
        lines.append(f"Geplante Dauer: {timestamp(sum(p['end'] - p['start'] for p in pieces))}")
    else:
        cuts = read_json(folder / "nightcut" / "cuts.json", [])
        for recording in cuts if len(cuts) <= 1 else ():
            for cut in recording.get("removals", []):
                why = " + ".join(CUTS.get(label, label) for label in cut["label"].split("+"))
                lines.append(f"{timestamp(cut['start'])} bis {timestamp(cut['end'])}   ·   {why}")
        if not cuts:
            lines.append("Schnittplan ist noch nicht vorhanden.")
        elif len(cuts) > 1:
            lines.append("Auftrag mit mehreren Quelldateien. Die Einzelzeiten stehen im Schnittprotokoll.")
    return "\n".join(lines)


# --- Bereinigung, Folgen, Eingaben -------------------------------------------------------------

CLEANUP_LABELS = {"done": "Exportdateien bereinigt", "now": "Bereinigung angefordert",
                  "auto": "Automatische Bereinigung aktiv"}


def cleanup_view(row):
    """Anzeige der Bereinigung für einen Auftrag (oder None): Text, Text/Zustand der beiden Knöpfe."""
    supported = bool(row and row.cleanup_supported)
    mode = row.cleanup_mode if row else "manual"
    verified = bool(row and row.cleanup_verified)
    if not row:
        label = "Wähle einen Auftrag, um die Bereinigung zu sehen."
    elif not supported:
        label = "Bereinigung für diesen Auftrag nicht verfügbar"
    else:
        label = CLEANUP_LABELS.get(mode, "YouTube-Prüfung bestätigt" if verified
                                   else "Bereinigung nach vollständiger YouTube-Prüfung")
    return {
        "label": label,
        "auto_text": "Automatik ausschalten" if mode == "auto" else "Automatisch bereinigen",
        "auto_mode": "manual" if mode == "auto" else "auto",
        "auto_enabled": supported and mode not in ("now", "done"),
        "now_enabled": supported and verified and mode not in ("now", "done"),
    }


def episode_number(path):
    match = re.search(r"-ep(\d+)$", Path(path).stem)
    return int(match[1]) if match else None


def parse_local_date(text):
    """Termin „TT.MM.JJJJ HH:MM“ -> datetime oder None (leer). Fehler als verständlicher Satz."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%d.%m.%Y %H:%M")
    except ValueError:
        raise ValueError("Bitte den Termin als TT.MM.JJJJ HH:MM eingeben, zum Beispiel 24.12.2026 19:00.") from None

