"""Watch completed upload bundles without attempting interactive sign-in."""
import json
import os
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

from bundle import job_name, media_extensions, read_metadata, thumbnail_for
from resumable_upload import UploadError, YouTube, upload


ROOT = Path(os.getenv("UPLOAD_ROOT", "/data"))
# Ordner sind einzeln einstellbar (Direkt-Modus auf dem PC); ohne Angabe gilt das Docker-Layout unter UPLOAD_ROOT.
INCOMING = Path(os.getenv("UPLOAD_INCOMING_DIR", str(ROOT / "incoming")))
UPLOADED = Path(os.getenv("UPLOAD_UPLOADED_DIR", str(ROOT / "uploaded")))
STATE = Path(os.getenv("UPLOAD_STATE_DIR", str(ROOT / "state")))
SECRETS = Path(os.getenv("UPLOAD_SECRETS_DIR", str(ROOT / "secrets")))
TOKEN = SECRETS / "request.token"
CLIENT = SECRETS / "client_secrets.json"
ENABLED = os.getenv("UPLOAD_ENABLED") == "1"
ALLOW_PUBLISH = os.getenv("ALLOW_PUBLISH") == "1"
SCHEDULE_ONLY = os.getenv("SCHEDULE_ONLY") == "1"
POLL = max(5, int(os.getenv("POLL_SECONDS", "20")))
METRICS = Path(os.getenv("METRICS_DIR", "/metrics"))
NOTICES = os.getenv("UPLOAD_NOTICES_DIR")
try:
    SERVER_VERSION = Path(os.getenv("VERSION_FILE", "/opt/uploader/VERSION")).read_text(encoding="utf-8").strip() or None
except OSError:
    SERVER_VERSION = None
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
def log(message):
    print(message, flush=True)


def sync_directory(path):
    if hasattr(os, "O_DIRECTORY"):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic_write(path, data, *, mode=None):
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    if mode is not None:
        temp.chmod(mode)
    for attempt in range(6):
        try:
            temp.replace(path)
            break
        except PermissionError:  # Windows: Datei gerade von einem Leser geoeffnet
            if attempt == 5:
                raise
            time.sleep(0.2)
    sync_directory(path.parent)


def write_json(path, data, *, mode=None):
    atomic_write(path, json.dumps(data, ensure_ascii=False) + "\n", mode=mode)


def publish_notice(stem, status, metadata=None, *, video_id=None, cover=None, reason=None, retry_thumbnail=False):
    if not NOTICES:
        return
    try:
        directory = Path(NOTICES)
        if cover:
            temp = directory / f".{stem}.jpg.partial"
            temp.write_bytes(cover.read_bytes())
            temp.chmod(0o644)
            temp.replace(directory / f"{stem}.jpg")
        metadata = metadata or {}
        notice = directory / f"{stem}.json"
        previous = json.loads(notice.read_text(encoding="utf-8")) if notice.is_file() else {}
        event = {"status": status, "reason": reason}
        events = previous.get("events", [])
        if not events or any(events[-1].get(key) != value for key, value in event.items()):
            events = [*events[-23:], {**event, "time": int(time.time())}]
        write_json(notice, {
            "status": status,
            "title": metadata.get("title", stem),
            "publish_at": metadata.get("publishAt"),
            "video_id": video_id,
            "thumbnail": bool(cover),
            "events": events,
            "reason": reason,
            "retry_thumbnail": retry_thumbnail,
        }, mode=0o644)
    except (OSError, ValueError, TypeError) as error:
        log(f"{stem}: Statusmeldung nicht gespeichert ({type(error).__name__}).")


def token_stamp():
    return [
        [file.stat().st_ino, file.stat().st_mtime_ns, file.stat().st_size]
        if file.is_file() and not file.is_symlink() else None
        for file in (TOKEN, CLIENT)
    ]


def auth_paused():
    stamp = token_stamp()
    if not all(stamp):
        return True
    marker = STATE / "auth-paused.json"
    return marker.exists() and json.loads(marker.read_text(encoding="utf-8")) == stamp


def receipt_id(receipt):
    if receipt.is_file():
        try:
            video_id = json.loads(receipt.read_text(encoding="utf-8")).get("id", "")
            if VIDEO_ID.fullmatch(video_id):
                return video_id
        except (ValueError, TypeError, AttributeError):
            pass
    return None


def schedule_confirmed(receipt, expected):
    if not expected:
        return True
    try:
        status = json.loads(receipt.read_text(encoding="utf-8"))["status"]
        return (status["privacyStatus"] == "private"
                and datetime.fromisoformat(status["publishAt"]) == datetime.fromisoformat(expected))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def archive(paths, folder, stem, result):
    target = folder / stem
    staging = folder / ("." + stem + ".partial")
    if not target.exists():
        staging.mkdir(exist_ok=True)
        for path in paths[1:]:
            copy = staging / path.name
            shutil.copy2(path, copy)
            if path.stat().st_size != copy.stat().st_size:
                raise OSError("Archive size differs from input")
            copy.chmod(0o644)
        write_json(staging / "result.json", result, mode=0o644)
        staging.chmod(0o755)
        staging.rename(target)
        sync_directory(folder)
    archived = json.loads((target / "result.json").read_text(encoding="utf-8"))
    if archived["video_id"] != result["video_id"]:
        raise ValueError("Archive belongs to a different upload")
    for path in paths[1:]:
        if path.exists() and path.stat().st_size != (target / path.name).stat().st_size:
            raise OSError("Archive size differs from input")
    for path in paths[1:]:
        path.unlink(missing_ok=True)

from string import Template

FOOTER_FILE = Path(os.environ.get("FOOTER_FILE", "/opt/uploader/description-footer.txt"))


def load_footer():
    """Beschreibungs-Fuss aus einer Datei (Platzhalter ${game} und ${developer}). Fehlt sie, wird nichts angehaengt."""
    try:
        return FOOTER_FILE.read_text(encoding="utf-8")
    except OSError:
        return ""


def with_footer(description, game, developer):
    template = load_footer()
    if not game or not developer or not template:
        return description
    footer = Template(template).substitute(game=game, developer=developer)
    body = description.replace("\r\n", "\n").replace(footer, "").strip()
    available = 5000 - len(footer.encode("utf-8")) - 2
    if available < 0:
        raise ValueError("The shared description footer is too long")
    body = body.encode("utf-8")[:available].decode("utf-8", errors="ignore").rstrip()
    return f"{body}\n\n{footer}" if body else footer


def process(marker):
    stem = marker.stem
    if not job_name.fullmatch(stem):
        return
    incoming = marker.parent
    if (incoming / (stem + ".cancelled")).exists():
        return
    job = STATE / stem
    version = job / "resumable"
    result_path = job / "result.json"
    retry_marker = incoming / (stem + ".retry-thumbnail")
    old = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
    retry_thumbnail = (retry_marker.is_file() and not retry_marker.is_symlink()
                       and old.get("retry_thumbnail") is True)
    if job.exists() and not version.is_file():
        return  # Preserve legacy jobs and their ambiguous upload outcomes.
    if old.get("state") == "uploaded":
        marker.unlink(missing_ok=True)
        return
    if old.get("state") == "review" and not retry_thumbnail:
        return
    if old.get("retry_after", 0) > time.time() and not retry_thumbnail:
        return
    if not job.exists():
        job.mkdir()
        sync_directory(STATE)
    if not version.exists():
        atomic_write(version, "1")
    metadata = incoming / (stem + ".json")
    receipt = job / "receipt.json"
    effective = job / "metadata.json"
    meta = {}
    setting_thumbnail = False
    started_with = token_stamp()

    def status(state, *, reason=None, video_id=None, cover=None, retry=False):
        item = {"state": state, "video_id": video_id, "time": int(time.time())}
        if reason:
            item["reason"] = reason
        if retry:
            item["retry_after"] = item["time"] + 90
        if setting_thumbnail and state == "review" and video_id:
            item["retry_thumbnail"] = True
        write_json(result_path, item)
        publish_notice(stem, state, meta, video_id=video_id, cover=cover, reason=reason,
                       retry_thumbnail=item.get("retry_thumbnail", False))

    try:
        completed = UPLOADED / stem
        if completed.is_dir():
            archived = json.loads((completed / "result.json").read_text(encoding="utf-8"))
            meta = json.loads(effective.read_text(encoding="utf-8"))
            if archived["video_id"] != receipt_id(receipt) or not archived["video_id"]:
                raise ValueError("Archive and YouTube receipt do not match")
            copies = [p for p in completed.iterdir() if p.name.startswith(stem + ".")]
            archive([marker, *(incoming / p.name for p in copies)], completed.parent, stem, archived)
            cover = next((p for p in copies if p.suffix in (".jpg", ".png")), None)
            status("uploaded", video_id=archived["video_id"], cover=cover)
            marker.unlink(missing_ok=True)
            return
        videos = [incoming / (stem + ext) for ext in media_extensions]
        videos = [p for p in videos if p.is_file() and not p.is_symlink()]
        if len(videos) != 1 or not metadata.is_file() or metadata.is_symlink():
            raise ValueError("Ready marker has no complete video and JSON")
        video = videos[0]
        if effective.is_file():
            meta = json.loads(effective.read_text(encoding="utf-8"))
        else:
            meta = read_metadata(metadata, allow_publish=ALLOW_PUBLISH)
            game = meta.pop("_vodwerft_game", None)
            developer = meta.pop("_vodwerft_developer", None)
            approved = meta.pop("_vodwerft_approved", False)
            if game and developer and approved is not True and re.fullmatch(r"[a-z0-9]+-[0-9a-f]{20}-ep[0-9]+", stem):
                meta["description"] = with_footer(meta.get("description", ""), str(game), str(developer))
            if SCHEDULE_ONLY and not meta.get("publishAt"):
                raise ValueError("Production episodes must have a scheduled publication")
            write_json(effective, meta)
        cover = thumbnail_for(video)
        if retry_thumbnail:
            status("uploading", reason="thumbnail_retry", video_id=receipt_id(receipt))
            retry_marker.unlink(missing_ok=True)
        else:
            publish_notice(stem, "uploading", meta, video_id=receipt_id(receipt))

        def progress(offset, total):
            if (incoming / (stem + ".cancelled")).exists():
                raise UploadError("cancelled")

        api = YouTube(TOKEN, CLIENT)
        if not receipt.is_file() and not (job / "session.json").is_file() and meta.get("publishAt"):
            if datetime.fromisoformat(meta["publishAt"]) <= datetime.now().astimezone():
                raise UploadError("publication_date_passed")
        confirmation = upload(api, video, meta, job, write_json, progress)
        video_id = confirmation["id"]
        if not schedule_confirmed(receipt, meta.get("publishAt")):
            raise UploadError("youtube_schedule_not_confirmed")
        thumbnail_done = job / "thumbnail-done"
        if cover and not thumbnail_done.is_file():
            setting_thumbnail = True
            api.thumbnail(video_id, cover)
            atomic_write(thumbnail_done, "1")
            setting_thumbnail = False
        # Playlist: nie ein Grund, ein fertiges Video als "Prüfung nötig" zu melden. Klappt es nicht (z. B. fehlendes
        # YouTube-Recht), steht der Grund im Protokoll und in result.json.
        playlist_note = None
        playlist = meta.get("playlistId")
        if playlist and not (job / "playlist-done").is_file():
            for attempt in range(4):  # vorübergehende Fehler (Netz, 429, 5xx): kurz warten und noch einmal
                try:
                    api.add_to_playlist(video_id, playlist)
                    atomic_write(job / "playlist-done", "1")
                    playlist_note = None
                    break
                except UploadError as error:
                    playlist_note = error.reason
                    if not error.retry or error.auth or attempt == 3:
                        break
                except (OSError, ValueError, KeyError, TypeError) as error:
                    playlist_note = type(error).__name__
                    break
                time.sleep(5 * 3 ** attempt)  # 5, 15, 45 Sekunden
            if playlist_note:
                log(f"{stem}: Playlist-Zuordnung nicht möglich ({playlist_note}).")
        files = [marker, video, metadata] + ([cover] if cover else [])
        result = {"state": "uploaded", "video_id": video_id, "time": int(time.time()), "exit_code": 0}
        if playlist_note:
            result["playlist_failed"] = playlist_note
        archive(files, UPLOADED, stem, result)
        # Bei fehlgeschlagener Playlist-Zuordnung steht der Grund in der Statusmeldung: Das Dashboard zeigt es an
        status("uploaded", video_id=video_id, cover=(UPLOADED / stem / cover.name) if cover else None,
               reason="playlist_failed" if playlist_note else None)
        marker.unlink(missing_ok=True)
        log(f"{stem}: uploaded ({video_id})")
    except UploadError as error:
        known = receipt_id(receipt)
        if error.auth:
            write_json(STATE / "auth-paused.json", started_with)
            status("auth", reason=error.reason, video_id=known)
        elif error.retry:
            status("uploading", reason=error.reason, video_id=known, retry=True)
        else:
            status("review" if error.reason != "cancelled" else "cancelled", reason=error.reason, video_id=known)
        log(f"{stem}: {error.reason}")
    except (OSError, ValueError, KeyError, TypeError) as error:
        status("review", reason=type(error).__name__, video_id=receipt_id(receipt))
        log(f"{stem}: Prüfung nötig ({type(error).__name__}).")



def metric_lines(now):
    """Prometheus lines for the textfile collector. One unreadable job must not stop the heartbeat."""
    values = [
        f"youtube_uploader_heartbeat_timestamp_seconds {now}",
        f"youtube_uploader_enabled {int(ENABLED)}",
    ]
    try:
        values.append(f"youtube_uploader_auth_required {int(ENABLED and auth_paused())}")
    except (OSError, ValueError, TypeError):
        values.append(f"youtube_uploader_auth_required {int(ENABLED)}")  # unreadable marker: assume login needed
    reviews = 0
    for path in STATE.iterdir():
        result = path / "result.json"
        try:
            if not path.is_dir() or not result.is_file():
                continue
            item = json.loads(result.read_text(encoding="utf-8"))
            state, video_id, stamp = item["state"], item.get("video_id"), int(item.get("time", 0))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            reviews += 1  # broken receipt: count it as a job that needs a look instead of hiding it
            continue
        reviews += state == "review"
        if (state == "uploaded" and isinstance(video_id, str) and VIDEO_ID.fullmatch(video_id)
                and now - stamp < 900):
            values.append(f'youtube_uploader_success_timestamp_seconds{{video_id="{video_id}"}} {stamp}')
    values.append(f"youtube_uploader_review_jobs {reviews}")
    return values


def publish_server_version(directory, now):
    """Alive marker first (works even when SMB shows the JSON as 0 bytes), then the legacy version file."""
    alive = directory / f"server-{SERVER_VERSION}.alive"
    alive.touch(exist_ok=True)
    os.utime(alive, None)
    alive.chmod(0o644)
    for other in directory.glob("server-*.alive"):
        if other != alive:
            other.unlink(missing_ok=True)
    atomic_write(directory / "server-version.json",
                 json.dumps({"version": SERVER_VERSION, "updated": now}) + "\n", mode=0o644)


def publish_metrics():
    last_notice = 0
    last_problem = None
    while True:
        problem = None
        try:
            now = int(time.time())
            atomic_write(METRICS / "youtube_uploader.prom", "\n".join(metric_lines(now)) + "\n", mode=0o644)
            if SERVER_VERSION and NOTICES and now - last_notice >= 60:  # PC: Version vergleichen und Lebenszeichen pruefen
                publish_server_version(Path(NOTICES), now)
                last_notice = now
        except Exception as error:  # the heartbeat thread must never die, or every alert turns into "unavailable"
            problem = type(error).__name__
        if problem and problem != last_problem:
            log(f"Monitoring-Datei konnte nicht aktualisiert werden ({problem}).")
        last_problem = problem
        time.sleep(15)


def lock_exclusive(handle):
    """Nur eine Warteschlange gleichzeitig (Linux: flock, Windows: msvcrt)."""
    try:
        import fcntl
    except ImportError:
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)


def run_queue(problems):
    """One pass over the ready markers. A job that fails unexpectedly is logged once and skipped,
    instead of crashing the container and restarting it in a loop."""
    try:
        if not ENABLED or auth_paused():
            return
        markers = sorted(INCOMING.glob("*.ready"))
    except Exception as error:
        report_problem(problems, "", error)
        return
    report_problem(problems, "", None)
    for marker in markers:
        try:
            if marker.is_file() and not marker.is_symlink() and not auth_paused():
                process(marker)
        except Exception as error:
            report_problem(problems, marker.stem, error)
        else:
            report_problem(problems, marker.stem, None)


def report_problem(problems, stem, error):
    """Log an unexpected error only when it changes, so a broken job does not flood the log every poll."""
    text = f"{type(error).__name__}: {error}"[:300] if error else None
    if text and problems.get(stem) != text:
        log(f"{stem or 'Warteschlange'}: unerwarteter Fehler, wird beim naechsten Durchlauf erneut versucht ({text}).")
    if text:
        problems[stem] = text
    else:
        problems.pop(stem, None)


def main():
    os.umask(0o077)
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / "worker.lock").open("a") as lock:
        try:
            lock_exclusive(lock)
        except OSError:
            log("Eine andere Upload-Warteschlange laeuft schon.")
            return
        for job in STATE.iterdir():
            if job.is_dir() and not (job / "resumable").exists() and not (job / "result.json").exists():
                write_json(job / "result.json", {
                    "state": "review", "video_id": receipt_id(job / "receipt.json"),
                    "time": int(time.time()), "error_type": "interrupted",
                })
        if METRICS.is_dir():
            threading.Thread(target=publish_metrics, daemon=True).start()
        log("YouTube-Warteschlange aktiv." if ENABLED else "YouTube-Warteschlange im Prüfmodus.")
        problems = {}
        while True:
            run_queue(problems)
            time.sleep(POLL)


if __name__ == "__main__":
    main()
