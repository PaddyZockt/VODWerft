"""Bind a release approval to a particular local export and thumbnail."""
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone

from release_slots import replace_unpublished_slot
from retention import write


def file_identity(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Die Exportdatei ist nicht verfügbar.")
    stat = path.stat()
    return [stat.st_size, stat.st_mtime_ns, stat.st_ino]


def draft_path(video):
    return video.parent / "approval" / f"{video.stem}.draft.json"


def approval_path(video):
    return draft_path(video).with_suffix(".approved")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def prepare_draft(video, metadata):
    path = draft_path(video)
    path.parent.mkdir(exist_ok=True)
    draft = {"file": file_identity(video), "metadata": metadata}
    if not path.is_file() or read_json(path) != draft:
        write(path, draft)


def approve(video, cover, expected_file, metadata, state, blocked=()):
    from PIL import Image

    path = draft_path(video)
    draft = read_json(path)
    if (draft["file"] != expected_file or file_identity(video) != expected_file
            or not video.with_suffix(".exported").is_file()):
        raise ValueError("Der Export hat sich geändert. Bitte die Vorschau erneut öffnen.")
    if approval_path(video).exists():
        raise ValueError("Diese Folge wurde bereits freigegeben.")
    title = metadata.get("title", "").strip()
    description = metadata.get("description", "")
    if not title or len(title) > 100 or len(description.encode("utf-8")) > 5000:
        raise ValueError("Titel (1–100 Zeichen) und Beschreibung (bis 5.000 UTF-8-Bytes) prüfen.")
    stamp = metadata.get("publishAt")
    if stamp:
        slot = datetime.fromisoformat(stamp)
        if slot.tzinfo is None or slot <= datetime.now(timezone.utc):
            raise ValueError("Wähle einen künftigen Veröffentlichungstermin.")
        if stamp != draft["metadata"].get("publishAt") and slot < datetime.now(timezone.utc) + timedelta(hours=24):
            raise ValueError("Ein neuer Termin muss mindestens 24 Stunden in der Zukunft liegen.")
        stamp = slot.astimezone(timezone.utc).isoformat()
    elif draft["metadata"].get("_requires_date"):
        raise ValueError("Wähle einen Veröffentlichungstermin.")
    data = {**draft["metadata"], "title": title, "description": description, "_vodwerft_approved": True}
    data.pop("_requires_date", None)
    if stamp:
        data["publishAt"] = stamp
    with Image.open(cover) as image:
        if image.format not in ("JPEG", "PNG") or image.width * image.height > 24_000_000:
            raise ValueError("Bitte ein JPG oder PNG mit höchstens 24 Megapixeln auswählen.")
        image.verify()
    if not 0 < cover.stat().st_size <= 2_000_000:
        raise ValueError("Das Thumbnail darf höchstens 2 MB groß sein.")
    image_bytes = cover.read_bytes()
    if not 0 < len(image_bytes) <= 2_000_000:
        raise ValueError("Das Thumbnail hat sich geändert.")
    digest = hashlib.sha256(image_bytes).hexdigest()
    suffix = ".png" if image_bytes.startswith(b"\x89PNG\r\n\x1a\n") else ".jpg"
    asset = path.parent / f"{video.stem}-{digest}{suffix}"
    lock = path.with_suffix(".lock")
    with lock.open("x"):
        pass
    try:
        if approval_path(video).exists():
            raise ValueError("Diese Folge wurde bereits freigegeben.")
        if not asset.exists():
            with tempfile.NamedTemporaryFile(dir=asset.parent, delete=False) as handle:
                pending = asset.parent / os.path.basename(handle.name)
                handle.write(image_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            pending.replace(asset)
        if stamp:
            replace_unpublished_slot(state, video.stem, stamp, blocked)
        write(approval_path(video), {"file": expected_file, "metadata": data,
                                     "thumbnail": asset.name, "sha256": digest})
    finally:
        lock.unlink(missing_ok=True)


def approved_export(video):
    path = approval_path(video)
    if not path.is_file():
        return None
    approval = read_json(path)
    if file_identity(video) != approval["file"]:
        raise ValueError("Die gerenderte Folge entspricht nicht mehr der Freigabe.")
    name, digest = approval["thumbnail"], approval["sha256"]
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or name not in (
            f"{video.stem}-{digest}.jpg", f"{video.stem}-{digest}.png"):
        raise ValueError("Das freigegebene Thumbnail ist ungültig.")
    cover = path.parent / name
    if (not 0 < file_identity(cover)[0] <= 2_000_000
            or hashlib.sha256(cover.read_bytes()).hexdigest() != digest):
        raise ValueError("Das Thumbnail entspricht nicht mehr der Freigabe.")
    return approval["metadata"], cover


def mission_seconds(text):
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        seconds = float(text)
        if seconds < 86400:
            return seconds
    elif re.fullmatch(r"(?:\d{1,2}:)?\d{1,3}:[0-5]\d", text):
        parts = list(map(int, text.split(":")))
        if len(parts) == 2 or parts[1] < 60:
            seconds = sum(value * 60 ** index for index, value in enumerate(reversed(parts)))
            if seconds < 86400:
                return seconds
    raise ValueError("Missionsbeginn als MM:SS oder HH:MM:SS eingeben.")
