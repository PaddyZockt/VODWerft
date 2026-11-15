"""Remove generated files for one fully verified Nightcut job."""
import re
import shutil
from pathlib import Path

from retention import BATCH, VIDEO_ID, parts_for, read, write


def policy_path(notices, key):
    if not BATCH.fullmatch(key):
        raise ValueError("Unknown recording ID")
    return notices / f"cleanup-{key}.json"


def policy(notices, key):
    path = policy_path(notices, key)
    if (notices / f"cleanup-done-{key}.json").is_file():
        return {"mode": "done"}
    return read(path) if path.is_file() else {"mode": "manual"}


def request(notices, key, mode):
    if mode not in ("manual", "auto", "now"):
        raise ValueError("Unknown cleanup mode")
    write(policy_path(notices, key), {"mode": mode})


def verified_parts(notices, key, parts):
    proof_path = notices / f"verified-{key}.json"
    if not parts or not proof_path.is_file() or proof_path.is_symlink():
        return {}
    proof = read(proof_path)
    ids = proof.get("parts")
    if (proof.get("batch") == key and isinstance(ids, dict) and set(ids) == set(parts)
            and all(isinstance(value, str) and VIDEO_ID.fullmatch(value) for value in ids.values())
            and len(set(ids.values())) == len(parts)):
        return ids
    return {}


def clean_generated(work, key, parts):
    folder = work / key
    directories = [folder / item for item in (
        "nightcut/cache", "nightcut/media", "highlights/cache", "highlights/media",
    )]
    files = [folder / f"{part}{suffix}" for part in parts for suffix in (".mp4", ".jpg")]
    for part in parts:
        files.extend(path for path in (folder / "approval").glob(f"{part}-*")
                     if re.fullmatch(re.escape(part) + r"-[0-9a-f]{64}\.(jpg|png)", path.name))
    for path in directories + files:
        if path.resolve() != path:
            raise ValueError(f"Unexpected linked cleanup path: {path.name}")
    for path in directories:
        if path.is_dir():
            shutil.rmtree(path)
    for path in files:
        path.unlink(missing_ok=True)


def reconcile(config, db):
    if config.get("upload_private_only") or not config.get("upload_incoming"):
        return
    share = Path(config["upload_incoming"]).parent
    notices = share / ".status"
    work = Path(config["work"]).resolve(strict=True)
    jobs = db.execute("SELECT key FROM recordings LEFT JOIN clips USING (key) "
                      "WHERE recordings.status='ready' AND (? OR clips.status='ready')",
                      (not config.get("clips_config"),)).fetchall()
    for key, in jobs:
        if not BATCH.fullmatch(key) or key in config.get("retention_hold", ()):
            continue
        parts = parts_for(db, config, key)
        if not parts:
            continue
        manifest = notices / f"retention-{key}.json"
        if not manifest.exists():
            write(manifest, {"batch": key, "parts": parts, "verify_only": True})
        if (notices / f"cleanup-done-{key}.json").is_file():
            continue
        ids = verified_parts(notices, key, parts)
        if not ids:
            continue
        # pc_cleanup="auto": nur den PC aufraeumen, sobald YouTube die Parts bestaetigt hat.
        # Die Archivkopie auf dem Server bleibt unberuehrt (kein cleanup-Auftrag wird geschrieben).
        if config.get("pc_cleanup") != "auto":
            receipt = notices / f"archive-cleaned-{key}.json"
            if (not receipt.is_file() or receipt.is_symlink()
                    or read(receipt) != {"batch": key, "parts": ids}):
                continue
        clean_generated(work, key, parts)
        write(notices / f"cleanup-done-{key}.json", {"parts": parts})
        print(f"{key}: Exportdateien auf dem PC bereinigt" + ("" if config.get("pc_cleanup") == "auto" else " und Server"), flush=True)
