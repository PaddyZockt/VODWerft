"""Verify whole batches on YouTube before releasing their local media."""
import json
import os
import re
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from atomic import atomic_write


BATCH = re.compile(r"(?:se|g[0-9a-f]{8})-[0-9a-f]{20}\Z")
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
# Kanal-ID aus der Umgebung (YOUTUBE_CHANNEL_ID). Ohne Angabe wird die Kanalpruefung uebersprungen;
# die Video-IDs stammen ohnehin aus den eigenen Upload-Belegen.
CHANNEL = os.getenv("YOUTUBE_CHANNEL_ID")


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False), fsync=True)


LEDGER = "uploaded.log"  # ein Protokoll im Statusordner: eine Zeile je hochgeladener Folge


def ledger_entries(notices):
    """Bisher protokollierte Folgen als {part: video_id}; kaputte Zeilen werden uebersprungen."""
    path = notices / LEDGER
    known = {}
    if path.is_file() and not path.is_symlink():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
                known[item["part"]] = item["video_id"]
            except (ValueError, KeyError, TypeError):
                continue
    return known


def ledger_add(notices, entries):
    """Haengt neue Folgen ans Protokoll an (jede Folge nur einmal). Gibt die Zahl neuer Zeilen zurueck."""
    known = ledger_entries(notices)
    fresh = [item for item in entries if known.get(item["part"]) != item["video_id"]]
    if fresh:
        path = notices / LEDGER
        created = not path.exists()
        with path.open("a", encoding="utf-8") as handle:
            for item in fresh:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if created:
            path.chmod(0o644)
    return len(fresh)


def backfill_ledger(notices):
    """Traegt Folgen aus bestaetigten Pruefungen nach, die noch nicht im Protokoll stehen."""
    entries = []
    for proof in sorted(notices.glob("verified-*.json")):
        try:
            data = read(proof)
            key = proof.stem.removeprefix("verified-")
            if data.get("batch") != key or not BATCH.fullmatch(key) or not isinstance(data.get("parts"), dict):
                continue
            for part, video_id in data["parts"].items():
                if re.fullmatch(re.escape(key) + r"-ep\d{2,9}", part) and VIDEO_ID.fullmatch(str(video_id)):
                    entries.append({"part": part, "video_id": video_id, "verified_at": data.get("verified_at")})
        except (OSError, ValueError, TypeError):
            continue
    return ledger_add(notices, entries)


def parts_for(db, config, key):
    with closing(sqlite3.connect(config["state"])) as series:
        row = series.execute("SELECT first_episode, count FROM batches WHERE series=? AND name=?",
                             (config["series"], key)).fetchone()
    if not row or not row[1]:
        return []
    parts = [f"{key}-ep{number:02d}" for number in range(row[0], row[0] + row[1])]
    sent = {episode for episode, in db.execute("SELECT episode FROM handoffs WHERE status='sent'")}
    return parts if set(parts) <= sent else []


def access_token(secrets):
    token = read(secrets / "request.token")
    client = read(secrets / "client_secrets.json")["installed"]
    form = urlencode({"client_id": client["client_id"], "client_secret": client["client_secret"],
                      "refresh_token": token["refresh_token"], "grant_type": "refresh_token"}).encode()
    with urlopen("https://oauth2.googleapis.com/token", data=form, timeout=20) as response:
        return json.load(response)["access_token"]


def youtube(ids, token):
    query = urlencode({"part": "snippet,status,contentDetails,processingDetails", "id": ",".join(ids),
                       "fields": "items(id,snippet(channelId,thumbnails),status(uploadStatus,privacyStatus,publishAt),contentDetails(hasCustomThumbnail),processingDetails(processingStatus))"})
    request = Request("https://www.googleapis.com/youtube/v3/videos?" + query,
                      headers={"Authorization": "Bearer " + token})
    with urlopen(request, timeout=20) as response:
        return {item["id"]: item for item in json.load(response)["items"]}


def confirmed(item, release, now):
    status = item.get("status", {})
    snippet = item.get("snippet", {})
    if ((CHANNEL and snippet.get("channelId") != CHANNEL) or status.get("uploadStatus") != "processed"
            or item.get("processingDetails", {}).get("processingStatus") != "succeeded"
            or item.get("contentDetails", {}).get("hasCustomThumbnail") is not True
            or not any(thumb.get("url", "").startswith("https://")
                       for thumb in snippet.get("thumbnails", {}).values())):
        return False
    if release <= now and status.get("privacyStatus") == "public":
        return True
    return (status.get("privacyStatus") == "private" and bool(status.get("publishAt"))
            and datetime.fromisoformat(status["publishAt"]) == release)


def verify_batch(manifest, archive, secrets, notices, dry_run=False):
    key = manifest.stem.removeprefix("retention-")
    proof = notices / f"verified-{key}.json"
    if not BATCH.fullmatch(key) or proof.exists() or manifest.is_symlink():
        return
    batch = read(manifest)
    parts = batch["parts"]
    if (batch.get("batch") != key or not isinstance(parts, list) or not parts or len(parts) > 300
            or len(set(parts)) != len(parts)
            or not all(re.fullmatch(re.escape(key) + r"-ep\d{2,9}", part) for part in parts)):
        raise ValueError("Invalid retention manifest")
    expected = {}
    for part in parts:
        folder = archive / part
        if folder.is_symlink() or not (folder / "result.json").is_file():
            return
        result = read(folder / "result.json")
        video_id = result.get("video_id")
        if result.get("state") != "uploaded" or not isinstance(video_id, str) or not VIDEO_ID.fullmatch(video_id):
            return
        metadata = read(folder / f"{part}.json")
        expected[part] = (video_id, datetime.fromisoformat(metadata["publishAt"]))
    ids = [video_id for video_id, _ in expected.values()]
    if len(set(ids)) != len(parts):
        return
    token = access_token(secrets)
    items = {}
    for start in range(0, len(ids), 50):
        items.update(youtube(ids[start:start + 50], token))
    now = datetime.now(timezone.utc)
    if not all(confirmed(items.get(video_id, {}), release, now) for video_id, release in expected.values()):
        print(f"{key}: YouTube-Prüfung noch offen", flush=True)
        return
    print(f"{key}: {len(parts)} Parts und benutzerdefinierte Thumbnails bestätigt", flush=True)
    if dry_run:
        return
    write(proof, {"batch": key, "parts": dict(zip(parts, ids)), "verified_at": now.isoformat()})


def clean_archive(manifest, archive, notices):
    key = manifest.stem.removeprefix("retention-")
    selection = notices / f"cleanup-{key}.json"
    proof_path = notices / f"verified-{key}.json"
    done = notices / f"archive-cleaned-{key}.json"
    if (not BATCH.fullmatch(key) or done.exists() or manifest.is_symlink()
            or not selection.is_file() or selection.is_symlink()
            or not proof_path.is_file() or proof_path.is_symlink()):
        return
    if read(selection).get("mode") not in ("auto", "now"):
        return
    batch = read(manifest)
    proof = read(proof_path)
    parts = batch["parts"]
    ids = proof["parts"]
    if (batch.get("batch") != key or proof.get("batch") != key or not parts
            or not isinstance(ids, dict) or set(ids) != set(parts)):
        return
    files, entries, folders = [], [], []
    for part in parts:
        if not re.fullmatch(re.escape(key) + r"-ep\d{2,9}", part):
            return
        folder = archive / part
        receipt = folder / "result.json"
        if folder.resolve() != folder or receipt.is_symlink() or not receipt.is_file():
            return
        result = read(receipt)
        video_id = ids[part]
        if (not isinstance(video_id, str) or not VIDEO_ID.fullmatch(video_id)
                or result.get("state") != "uploaded" or result.get("video_id") != video_id):
            return
        try:
            publish_at = read(folder / f"{part}.json").get("publishAt")
        except (OSError, ValueError, TypeError):
            publish_at = None
        entries.append({"part": part, "video_id": video_id, "publish_at": publish_at,
                        "uploaded_at": result.get("time"), "verified_at": proof.get("verified_at")})
        files.extend(folder / f"{part}{suffix}" for suffix in (".mp4", ".jpg", ".png", ".json"))
        files.append(receipt)
        folders.append(folder)
    if any(path.resolve() != path or (path.exists() and not path.is_file()) for path in files):
        raise ValueError("Unexpected archive file")
    ledger_add(notices, entries)  # erst protokollieren, dann loeschen
    for path in files:
        path.unlink(missing_ok=True)
    for folder in folders:  # der Ordner geht nur weg, wenn er leer ist; fremde Dateien bleiben unberuehrt
        try:
            folder.rmdir()
        except OSError:
            pass
    write(done, {"batch": key, "parts": ids})
    print(f"{key}: Upload-Exporte im Archiv bereinigt und protokolliert", flush=True)


if __name__ == "__main__":
    notices = Path("/notices")
    archive = Path("/data/uploaded").resolve()
    dry_run = "--dry-run" in sys.argv
    if not dry_run:
        try:
            backfill_ledger(notices)
        except OSError as error:
            print(f"Upload-Protokoll nicht aktualisiert ({type(error).__name__})", flush=True)
    for manifest in sorted(notices.glob("retention-*.json")):
        try:
            verify_batch(manifest, archive, Path("/data/secrets"), notices, dry_run=dry_run)
            if not dry_run:
                clean_archive(manifest, archive, notices)
        except (OSError, ValueError, TypeError, KeyError) as error:
            print(f"{manifest.stem}: Prüfung zurückgestellt ({type(error).__name__})", flush=True)
