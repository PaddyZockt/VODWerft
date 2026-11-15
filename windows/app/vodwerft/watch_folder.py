"""Process completed recordings from a folder on the Windows editing PC."""
import argparse
import ctypes
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import ExitStack, closing
from datetime import date, datetime
from pathlib import Path
from string import Template

import yaml

from atomic import atomic_write
from bundle import enqueue, media_extensions, mission_title
from clip_retry import PENDING
from description_footer import with_footer
from game_library import developer as game_developer
from episode_approval import approved_export, mission_seconds, prepare_draft
from game_profiles import load_profiles, recording_settings
from job_history import record
from export_episode import video_info
from release_slots import read_manual, reserve
from obs_audio import split_audio
from job_cleanup import reconcile as reconcile_cleanup
from run_letsplay import lock_output
from series_numbers import initialize
from status_report import CHECKSUM_STATUS, publish
from file_ready import unlocked
from thumbnail_theme import sanitize_theme
import settings as user_settings


def digest(path, expected, work):
    checksum = hashlib.sha256()
    read = 0
    next_update = 0
    try:
        with path.open("rb") as source:
            while True:
                now = time.monotonic()
                if now >= next_update:
                    percent = min(100, read * 100 // expected[0])
                    try:
                        publish(work, CHECKSUM_STATUS, {"source": path.name,
                                "detail": f"Gleiche Prüfsumme ab · {percent} %", "updated": int(time.time())})
                    except OSError:
                        pass
                    next_update = now + 5
                block = source.read(8 * 1024 * 1024)
                if not block:
                    break
                checksum.update(block)
                read += len(block)
    finally:
        try:
            (work / f"{CHECKSUM_STATUS}.json").unlink(missing_ok=True)
        except OSError:
            pass
    file = path.stat()
    return checksum.hexdigest() if (file.st_size, file.st_mtime_ns) == expected else None


def models_present(names):
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as response:
            found = {item["name"] for item in json.load(response)["models"]}
        return set(names) <= found
    except (OSError, ValueError, KeyError):
        return False


def ensure_ollama(config):
    names = config.get("ollama_models", [])
    if not names or models_present(names):
        return
    with open(config["ollama_log"], "ab") as output:
        subprocess.Popen([config["ollama"], "serve"], stdin=subprocess.DEVNULL, stdout=output,
                         stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                         env={**os.environ, "OLLAMA_HOST": "127.0.0.1:11434"})
    for _ in range(15):
        time.sleep(2)
        if models_present(names):
            return
    raise RuntimeError("Ollama or a required local model is unavailable")


# Großzügiges Gesamt-Limit pro Unterprozess. Hängt ffmpeg, Ollama oder ein Modell, bliebe der Job sonst
# für immer auf "processing" und alle späteren Aufnahmen warteten mit.
DEFAULT_JOB_TIMEOUT_HOURS = 12


def job_timeout(config):
    try:
        hours = float(config.get("job_timeout_hours", DEFAULT_JOB_TIMEOUT_HOURS))
    except (TypeError, ValueError):
        hours = DEFAULT_JOB_TIMEOUT_HOURS
    return hours * 3600 if hours > 0 else DEFAULT_JOB_TIMEOUT_HOURS * 3600


def open_jobs_db(path):
    """Öffnet jobs.sqlite3. WAL: Dashboard und Statusdienst lesen, während der Watcher schreibt."""
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA journal_mode=WAL").fetchone()
    except sqlite3.Error:
        pass  # z. B. Netzlaufwerk ohne WAL-Unterstützung: bisheriges Journal weiterverwenden
    return db


def effective_clips_config(config, clips_config, output):
    """Schreibt <output>/clips-effective.yaml: Clips-YAML plus Clip-Stil des (eingefrorenen) Spielprofils.

    Hinweis: Die Nightcut-Stufe `shorts` wird zwischengespeichert. Eine Stiländerung an einem bereits
    fertigen Job wirkt erst mit `--force shorts`."""
    data = yaml.safe_load(Path(clips_config).read_text(encoding="utf-8-sig")) or {}
    if not isinstance(data, dict):
        raise ValueError("Die Clips-Konfiguration muss ein YAML-Objekt sein")
    if not isinstance(data.get("shorts"), dict):
        data["shorts"] = {}
    style = config.get("caption_style")
    data["shorts"].update(style if isinstance(style, dict) else {})
    theme = config.get("thumbnail_theme")
    if isinstance(theme, dict) and theme:
        data.setdefault("thumbnails", {})
        if isinstance(data["thumbnails"], dict):
            data["thumbnails"].update(sanitize_theme(theme))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    return atomic_write(output / "clips-effective.yaml", yaml.safe_dump(data, allow_unicode=True, sort_keys=False))


def python_executable():
    executable = Path(sys.executable)
    return executable.with_name("python.exe") if executable.name.lower() == "pythonw.exe" else executable


def run_job(config, source, key, db):
    output = Path(config["work"]) / key
    ensure_ollama(config)
    command = [
        str(python_executable()), "-X", "utf8", "-B", "-u",
        str(Path(__file__).with_name("run_letsplay.py")), str(source),
        "--profile", config["profile"], "--config", config["nightcut_config"],
        "--output", str(output), "--series", config["series"], "--series-state", config["state"],
        "--job-name", key, "--audio-track", str(config["audio_track"]),
        "--auto-thumbnail",
        "--thumbnail-style", config.get("thumbnail_style", "numbered"),
        "--encoder", config.get("encoder", "h264_nvenc"),
    ]
    if isinstance(config.get("thumbnail_theme"), dict) and config["thumbnail_theme"]:
        command.extend(["--thumbnail-theme", json.dumps(config["thumbnail_theme"])])
    if config.get("description"):
        command.extend(["--description-template", config["description"]])
    if config.get("obs_split_audio"):
        command.append("--obs-split-audio")
    if config.get("mission_export"):
        mission = mission_title(source)
        command.extend(["--mission", mission])
        trim = source.with_suffix(".start.txt")
        if trim.is_file():
            command.extend(["--trim-start", str(mission_seconds(trim.read_text(encoding="utf-8-sig").strip()))])
    log = output.with_suffix(".log")
    with log.open("ab") as handle:
        with subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as child:
            attempted = set()
            limit = job_timeout(config)
            deadline = time.monotonic() + limit
            while True:
                try:
                    code = child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if time.monotonic() >= deadline:
                        child.kill()
                        child.wait()
                        raise subprocess.TimeoutExpired(command, limit) from None
                    dispatch_rendered(db, config, output, attempted)
                else:
                    if code:
                        raise subprocess.CalledProcessError(code, command)
                    break
            dispatch_rendered(db, config, output, attempted)
    if config.get("mission_export") and not config.get("upload_incoming"):
        target = Path(config["mission_export"]) / key
        if not target.is_dir():
            pending = target.with_suffix(".partial")
            pending.mkdir(exist_ok=True)
            video, = output.glob("*.mp4")
            for extension in (".mp4", ".jpg", ".json"):
                shutil.copyfile(video.with_suffix(extension), pending / (source.stem + extension))
            pending.rename(target)


def run_clips(config, source, key):
    output = Path(config["work"]) / key
    split_export = bool(config.get("obs_split_audio"))
    known_layout = split_audio(source, require_known_layout=split_export)
    use_stems = known_layout and split_export
    clips_config = config["split_clips_config"] if use_stems else config["clips_config"]
    command = [
        str(python_executable()), "-X", "utf8", "-B", "-u", str(Path(__file__).with_name("clip_run.py")),
        "run", str(source), "--mode", "highlights", "--no-fill", "--gpus", "1",
        "--profile", config["profile"], "--config", str(effective_clips_config(config, clips_config, output)),
        "--output", str(output), "--name", "highlights",
    ]
    log = output.with_suffix(".clips.log")
    caption_audio = "stems" if use_stems else "mixed" if known_layout else "default"
    with log.open("ab") as handle:
        subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                       env={**os.environ, "NIGHTCUT_SHORTS_CAPTION_AUDIO": caption_audio},
                       check=True, timeout=job_timeout(config),
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    clips = sorted((output / "highlights" / "shorts").glob("*.mp4"))
    if clips and config.get("clips_output"):
        target = Path(config["clips_output"]) / key
        target.mkdir(parents=True, exist_ok=True)
        for clip in clips:
            final = target / clip.name
            partial = final.with_suffix(".partial")
            shutil.copyfile(clip, partial)
            partial.replace(final)
    print(f"{source.name}: {len(clips)} Hochkant-Clips", flush=True)


def apply_series_metadata(metadata, config, source, video):
    suffix = config.get("title_suffix")
    if suffix:
        number = int(video.stem.rsplit("-ep", 1)[1])
        headline = metadata["title"].partition(" – ")[2]
        prefix = f"{config['series']} | Folge {number}"
        if headline and headline != f"Folge {number}":
            maximum = 100 - len(prefix) - len(suffix) - len(" –  ")
            shortened = headline[:maximum].rstrip()
            if len(shortened) < len(headline) and " " in shortened:
                shortened = shortened.rsplit(" ", 1)[0].rstrip(" –-,")
            prefix += f" – {shortened}"
        metadata["title"] = f"{prefix} {suffix}"
    filename_date = re.match(r"\d{4}-\d{2}-\d{2}(?=[ T_.-]|$)", Path(source).stem)
    if config.get("recording_date") or filename_date:
        try:
            stamp = date.fromisoformat(config.get("recording_date") or filename_date[0])
        except ValueError:
            stamp = None
        if stamp and stamp <= date.today():
            metadata["recordingDate"] = stamp.isoformat()


def resume_handoff(db, target, episode):
    accepted = (
        target / f"{episode}.ready",
        target / f"{episode}.cancelled",
        target.parent / ".status" / f"{episode}.json",
        target.parent / "Fertig" / episode / "result.json",
        target.parent / "Pruefen" / episode / "result.json",
    )
    if any(path.is_file() for path in accepted):
        with db:
            db.execute("UPDATE handoffs SET status='sent' WHERE episode=?", (episode,))
        return
    # The watcher holds its exclusive lock. Without a ready marker, the uploader
    # cannot pick up these leftovers from our interrupted copy.
    for suffix in (".mp4", ".json", ".jpg"):
        name = episode + suffix
        (target / f".{name}.partial").unlink(missing_ok=True)
        (target / name).unlink(missing_ok=True)
    (target / f".{episode}.enqueue-lock").unlink(missing_ok=True)
    with db:
        db.execute("DELETE FROM handoffs WHERE episode=? AND status='sending'", (episode,))


DISPATCH_ERRORS = {}


def dispatch(db, profile, early_episode=None):
    if not profile.get("upload_incoming"):
        return
    target = Path(profile["upload_incoming"])
    if not target.is_dir():
        return
    if early_episode:
        recording = early_episode.rsplit("-ep", 1)[0]
        jobs = db.execute("SELECT key, source FROM recordings WHERE key=? AND status IN ('processing', 'ready')",
                          (recording,)).fetchall()
    else:
        jobs = db.execute("SELECT key, source FROM recordings WHERE status='ready' ORDER BY rowid").fetchall()
    for key, source in jobs:
        config = recording_settings(profile, key)
        manual = {}
        if config.get("manual_release"):
            with closing(sqlite3.connect(config["state"])) as series_db:
                manual = read_manual(series_db)
            if not manual and not config.get("require_approval"):
                continue
        elif config.get("upload_gate") and not Path(config["upload_gate"]).is_file():
            continue
        def handle(video, config=config, manual=manual, key=key, source=source):
            if early_episode and video.stem != early_episode:
                return
            gated = config.get("require_approval", False)
            if config.get("manual_release") and video.stem not in manual and not gated:
                return
            state = db.execute("SELECT status FROM handoffs WHERE episode=?", (video.stem,)).fetchone()
            if state and state[0] == "sending":
                resume_handoff(db, target, video.stem)
                state = db.execute("SELECT status FROM handoffs WHERE episode=?", (video.stem,)).fetchone()
            if state:
                return
            if gated and not video.with_suffix(".exported").is_file():
                return
            metadata = json.loads(video.with_suffix(".json").read_text(encoding="utf-8"))
            cover = video.with_suffix(".jpg")
            if not cover.is_file():
                if early_episode:
                    return
                raise ValueError("Expected a generated thumbnail before the upload")
            metadata["privacyStatus"] = "private"
            if config.get("upload_private_only"):
                metadata.pop("publishAt", None)
                metadata["title"] = "Nightcut Test – " + metadata["title"]
            else:
                apply_series_metadata(metadata, config, source, video)
                slot = manual.get(video.stem)
                if not config.get("manual_release"):
                    slot = reserve(config["state"], video.stem, blocked=config.get("blocked_utc_slots", []),
                                   after_date=config.get("publish_after_date"), weekdays=config.get("publish_weekdays", (0, 3)))
                if slot and datetime.fromisoformat(slot) <= datetime.now().astimezone() and not gated:
                    raise ValueError("A reserved date has passed and needs review")
                if slot:
                    metadata["publishAt"] = slot
            developer = game_developer(config["series"], config.get("developer"))
            if developer:
                # Der Server haengt damit den Beschreibungs-Fuss an (bei freigegebenen Folgen schon geschehen).
                metadata["_vodwerft_game"] = config["series"]
                metadata["_vodwerft_developer"] = developer
            if gated:
                metadata["_requires_date"] = not config.get("upload_private_only")
                metadata["description"] = with_footer(metadata.get("description", ""), config["series"], developer)
                approved = approved_export(video)
                if approved is None:
                    prepare_draft(video, metadata)
                    return
                metadata, cover = approved
            outbox = video.parent / "upload"
            outbox.mkdir(exist_ok=True)
            companion = outbox / (video.stem + ".json")
            companion.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            with db:
                claimed = db.execute("INSERT OR IGNORE INTO handoffs VALUES (?, 'sending')", (video.stem,))
            if not claimed.rowcount:
                return
            enqueue(video, companion, target, thumbnail=cover)
            with db:
                db.execute("UPDATE handoffs SET status='sent' WHERE episode=?", (video.stem,))
            release = metadata.get("publishAt", "privat")
            record(db, key, "An den Server übergeben", f"{video.stem.rsplit('-ep', 1)[-1]} · {release}")
            print(f"{video.stem}: für {release} an den Uploader übergeben", flush=True)
        for video in sorted((Path(config["work"]) / key).glob("*.mp4")):
            try:
                handle(video)
            except Exception as error:
                if early_episode:
                    raise
                message = f"{type(error).__name__}: {str(error)[:160]}"
                if DISPATCH_ERRORS.get(video.stem) != message:
                    DISPATCH_ERRORS[video.stem] = message
                    print(f"{video.stem}: Übergabe übersprungen ({message})", flush=True)


def dispatch_rendered(db, config, folder, attempted):
    if not config.get("upload_incoming"):
        return
    expected = re.compile(re.escape(folder.name) + r"-ep\d{2,9}\Z")
    markers = (path for path in folder.glob("*.exported") if expected.fullmatch(path.stem))
    markers = sorted(markers, key=lambda path: int(path.stem.rsplit("-ep", 1)[1]))
    for marker in markers:
        episode = marker.stem
        if episode in attempted or marker.is_symlink():
            continue
        try:
            if db.execute("SELECT 1 FROM handoffs WHERE episode=? AND status='sent'", (episode,)).fetchone():
                attempted.add(episode)
                continue
            dispatch(db, config, early_episode=episode)
        except (OSError, ValueError, sqlite3.Error) as error:
            attempted.add(episode)
            print(f"{episode}: Frühe Übergabe wird später geprüft ({type(error).__name__})", flush=True)


_held_back = None


def hold_back(source):
    """Meldet einmal, dass die Verarbeitung auf diese Datei wartet (neuere Dateien warten mit)."""
    global _held_back
    if _held_back != source:
        _held_back = source
        print(f"{source.name}: Noch nicht fertig - neuere Aufnahmen warten, damit die Folgen in Reihenfolge nummeriert werden", flush=True)


def scan(config, db, observations):
    minimum = config.get("stable_seconds", 90)
    input_files = sorted(Path(config["input"]).iterdir(), key=lambda path: path.name.casefold())
    initial = config.get("initial_recording")
    if initial:
        finished = db.execute("SELECT 1 FROM recordings WHERE source=? AND status='review'", (initial,)).fetchone()
        completed = db.execute(
            "SELECT 1 FROM recordings LEFT JOIN clips USING (key) "
            "WHERE source=? AND recordings.status='ready' AND (? OR clips.key IS NOT NULL)",
            (initial, not config.get("clips_config")),
        ).fetchone()
        if not (finished or completed):
            input_files.insert(0, Path(initial))
    # Alle Dateien zuerst beobachten: Die Wartezeit laeuft fuer alle gleichzeitig. Sonst wuerde jede Datei einzeln
    # erst warten, wenn sie an der Reihe ist, und nach einem Neustart dauerte es Dateien x 90 Sekunden.
    for source in input_files:
        if source.suffix.lower() in media_extensions and source.is_file() and not source.is_symlink():
            try:
                stat = source.stat()
            except OSError:
                continue
            signature = (stat.st_size, stat.st_mtime_ns)
            saved = observations.get(source)
            if saved is None or saved[0] != signature:
                observations[source] = (signature, time.monotonic(), False)
    for source in input_files:
        if source.suffix.lower() not in media_extensions or not source.is_file() or source.is_symlink():
            continue
        try:
            stat = source.stat()
        except OSError:
            continue  # zwischen den beiden Durchläufen verschoben oder gelöscht
        signature = (stat.st_size, stat.st_mtime_ns)
        saved = observations.get(source)
        if saved is None or saved[0] != signature:
            observations[source] = (signature, time.monotonic(), False)
        _, since, handled = observations[source]
        if handled:
            continue
        if (stat.st_size == 0 or time.monotonic() - since < minimum
                or time.time() - stat.st_mtime < minimum or not unlocked(source)):
            # Eine aeltere Aufnahme, die noch nicht fertig ist, haelt die neueren zurueck:
            # Folgennummern werden beim Start vergeben und muessen der Dateireihenfolge folgen.
            hold_back(source)
            break
        if config.get("mission_export") and not mission_title(source):
            print(f"{source.name}: Bitte Missionsname zum Dateinamen hinzufügen", flush=True)
            observations[source] = (signature, since, True)
            continue
        fingerprint = (str(source), *signature, stat.st_ino)
        known = db.execute("SELECT key FROM fingerprints WHERE path=? AND size=? AND modified=? AND inode=?",
                           fingerprint).fetchone()
        if known:
            key = known[0]
        else:
            value = digest(source, signature, Path(config["work"]))
            if value is None:
                hold_back(source)
                break
            key = config.get("job_prefix", "se") + "-" + value[:20]
            with db:
                db.execute("INSERT OR REPLACE INTO fingerprints VALUES (?,?,?,?,?)", (*fingerprint, key))
        old = db.execute("SELECT status FROM recordings WHERE key=?", (key,)).fetchone()
        if old and old[0] not in ("processing", "retry", "awaiting_start"):
            if old[0] == "ready":
                process_clips(recording_settings(config, key), db, source, key)
            observations[source] = (signature, since, True)
            continue
        if old and old[0] == "retry":
            # Bei „Export erneut versuchen“ gelten die aktuellen Einstellungen des Spiels, nicht die beim ersten Start eingefrorenen.
            (Path(config["work"]) / f"{key}.profile.json").unlink(missing_ok=True)
        job_config = recording_settings(config, key, save=True)
        trim = source.with_suffix(".start.txt")
        waiting = job_config.get("mission_export") and job_config.get("require_mission_start") and not trim.is_file()
        with db:
            db.execute("INSERT INTO recordings VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET status=excluded.status",
                       (key, str(source), "awaiting_start" if waiting else "processing"))
        if waiting:
            if not old or old[0] != "awaiting_start":
                record(db, key, "Wartet auf Missionsbeginn")
            continue
        record(db, key, "Export gestartet" if not old else "Export aufgenommen")
        print(f"Verarbeite {source.name}", flush=True)
        try:
            run_job(job_config, source, key, db)
        except Exception as error:  # auch KeyError/sqlite3.Error: sonst bliebe der Job endlos auf "processing"
            status = "review"
            record(db, key, "Export fehlgeschlagen", f"{type(error).__name__} · {key}.log")
            print(f"{source.name}: Prüfung nötig ({type(error).__name__}), siehe {key}.log", flush=True)
        else:
            status = "ready"
            record(db, key, "Export abgeschlossen")
            print(f"{source.name}: fertig im lokalen Ausgabeordner", flush=True)
        with db:
            db.execute("UPDATE recordings SET status=? WHERE key=?", (status, key))
        if status == "ready":
            process_clips(job_config, db, source, key)
        observations[source] = (signature, since, True)


def process_clips(config, db, source, key, *, retry=False):
    if not config.get("clips_config"):
        return
    current = db.execute("SELECT status FROM clips WHERE key=?", (key,)).fetchone()
    if current and (not retry or current[0] not in PENDING):
        return
    if retry:
        with db:
            db.execute("UPDATE clips SET status='retrying' WHERE key=?", (key,))
    print(f"{source.name}: suche Hochkant-Clips", flush=True)
    record(db, key, "Clips erneut gestartet" if retry else "Clips gestartet")
    try:
        if retry:
            expected = db.execute(
                "SELECT size, modified, inode FROM fingerprints WHERE path=? AND key=?",
                (str(source), key),
            ).fetchone()
            info = source.stat()
            if (source.is_symlink() or not source.is_file() or not unlocked(source)
                    or expected != (info.st_size, info.st_mtime_ns, info.st_ino)):
                raise ValueError("Originalaufnahme fehlt, ist geöffnet oder hat sich geändert")
        ensure_ollama(config)
        run_clips(config, source, key)
    except Exception as error:  # auch KeyError/sqlite3.Error: Status "review" statt Dauerschleife
        status = "review"
        record(db, key, "Clips fehlgeschlagen", f"{type(error).__name__} · {key}.clips.log")
        print(f"{source.name}: Clips prüfen ({type(error).__name__}), siehe {key}.clips.log", flush=True)
    else:
        status = "ready"
        record(db, key, "Clips abgeschlossen")
    with db:
        db.execute("INSERT INTO clips VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET status=excluded.status",
                   (key, status))


def retry_clips(config, db):
    jobs = db.execute(
        "SELECT key, source FROM recordings JOIN clips USING (key) "
        "WHERE recordings.status='ready' AND clips.status IN (?, ?) ORDER BY recordings.rowid",
        PENDING,
    ).fetchall()
    for key, source in jobs:
        process_clips(recording_settings(config, key), db, Path(source), key, retry=True)


def fullscreen_app_active():
    """True, wenn ein Vollbild-Programm (meist ein Spiel) im Vordergrund ist. Nur Windows."""
    if sys.platform != "win32":
        return False
    try:
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        window = user32.GetForegroundWindow()
        if not window or window == user32.GetDesktopWindow() or window == user32.GetShellWindow():
            return False
        rect = wintypes.RECT()
        user32.GetWindowRect(window, ctypes.byref(rect))
        return (rect.left <= 0 and rect.top <= 0 and rect.right >= user32.GetSystemMetrics(0)
                and rect.bottom >= user32.GetSystemMetrics(1))
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()
    if args.log:
        sys.stdout = sys.stderr = args.log.open("a", encoding="utf-8", buffering=1)
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    os.environ["PATH"] = config["ffmpeg_directory"] + os.pathsep + os.environ["PATH"]
    if config.get("model_cache"):
        os.environ.update(HF_HOME=config["model_cache"], HF_HUB_OFFLINE="1")
    with ExitStack() as stack:
        workers = {}

        def worker_for(profile):
            work = Path(profile["work"])
            if work in workers:
                return workers[work]
            work.mkdir(parents=True, exist_ok=True)
            lock_output(work / "watcher")
            initialize(profile["state"], profile["series"], profile["first_episode"])
            db = stack.enter_context(closing(open_jobs_db(work / "jobs.sqlite3")))
            db.executescript("""
            CREATE TABLE IF NOT EXISTS recordings (key TEXT PRIMARY KEY, source TEXT NOT NULL, status TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS handoffs (episode TEXT PRIMARY KEY, status TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS clips (key TEXT PRIMARY KEY, status TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS fingerprints (path TEXT PRIMARY KEY, size INTEGER NOT NULL,
                modified INTEGER NOT NULL, inode INTEGER NOT NULL, key TEXT NOT NULL);
            """)
            workers[work] = (db, {})
            print(f"Warte auf Aufnahmen in {profile['input']}", flush=True)
            return workers[work]

        while True:
            prefs = user_settings.load(args.config.parent)
            chosen = user_settings.stored(args.config.parent)
            if prefs["pause_while_gaming"] and not args.once and fullscreen_app_active():
                time.sleep(config.get("poll_seconds", 15))
                continue
            for profile in load_profiles(args.config):
                profile = user_settings.apply_to_profile(profile, chosen)
                db, observations = worker_for(profile)
                def retry_marks():
                    for (source,) in db.execute("SELECT source FROM recordings WHERE status='retry'"):
                        path = Path(source)
                        if path in observations:
                            signature, since, _ = observations[path]
                            observations[path] = (signature, since, False)

                steps = (("Aufräumen", lambda: reconcile_cleanup(profile, db)),
                         ("Wiederholungen", retry_marks),
                         ("Aufnahmen suchen", lambda: scan(profile, db, observations)),
                         ("Übergabe", lambda: dispatch(db, profile)),
                         ("Clips", lambda: retry_clips(profile, db)))
                for label, step in steps:
                    try:
                        step()
                    except Exception as error:
                        print(f"{profile['series']} {label}: {type(error).__name__}: {str(error)[:160]}", flush=True)
                        if args.once:
                            raise
            if args.once:
                break
            time.sleep(config.get("poll_seconds", 15))


if __name__ == "__main__":
    main()
