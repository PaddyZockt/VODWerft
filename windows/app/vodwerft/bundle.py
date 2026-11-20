"""Validate and atomically hand off completed videos and their companion files."""
import argparse
import json
import re
import shutil
from datetime import date, datetime, timezone
from pathlib import Path


media_extensions = (".mp4", ".mkv", ".mov")
image_extensions = (".jpg", ".png")
job_name = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\Z")
obs_prefix = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}-\d{2}-\d{2}(?: - |$)")


def mission_title(source):
    return obs_prefix.sub("", source.stem).strip()[:88]




def read_metadata(path, *, allow_publish=False):
    metadata = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(metadata, dict):
        raise ValueError("Metadata must be a JSON object")
    title = metadata.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > 100:
        raise ValueError("A title with 1–100 characters is required")
    privacy = metadata.setdefault("privacyStatus", "private")
    if privacy not in ("private", "unlisted", "public"):
        raise ValueError("Invalid privacyStatus")
    publish_at = metadata.get("publishAt")
    if not allow_publish and (privacy != "private" or publish_at):
        raise ValueError("The current worker accepts private uploads only")
    if "containsSyntheticMedia" in metadata and not isinstance(metadata["containsSyntheticMedia"], bool):
        raise ValueError("containsSyntheticMedia must be true or false")
    playlist = metadata.get("playlistId")
    if playlist is not None and not (isinstance(playlist, str) and re.fullmatch(r"[A-Za-z0-9_-]{10,64}", playlist)):
        raise ValueError("Invalid playlistId")
    if publish_at:
        if not isinstance(publish_at, str):
            raise ValueError("publishAt must be an ISO date and time")
        stamp = datetime.fromisoformat(publish_at)
        if privacy != "private" or stamp.tzinfo is None or stamp <= datetime.now(timezone.utc):
            raise ValueError("A schedule requires private visibility and a future timestamp with an offset")
    return metadata


def thumbnail_for(video):
    matches = [video.with_suffix(ext) for ext in image_extensions if video.with_suffix(ext).exists()]
    if len(matches) > 1 or any(not p.is_file() or p.is_symlink() for p in matches):
        raise ValueError("Use at most one regular thumbnail per video")
    if matches and not 0 < matches[0].stat().st_size <= 2_000_000:
        raise ValueError("Thumbnail must be at most 2 MB")
    return matches[0] if matches else None


def enqueue(video, metadata, incoming, *, name=None, thumbnail=None):
    if not video.is_file() or not video.stat().st_size or video.suffix.lower() not in media_extensions:
        raise ValueError("Expected a non-empty MP4, MKV or MOV")
    if metadata.suffix.lower() != ".json":
        raise ValueError("Companion metadata must be a JSON file")
    read_metadata(metadata, allow_publish=True)
    if thumbnail and (thumbnail.suffix.lower() not in image_extensions or not thumbnail.is_file()
                      or not 0 < thumbnail.stat().st_size <= 2_000_000):
        raise ValueError("Expected a JPG or PNG thumbnail up to 2 MB")
    stem = name or video.stem
    if not job_name.fullmatch(stem):
        raise ValueError("Use a short file name made up of letters, numbers, dots, hyphens or underscores")
    if not incoming.is_dir():
        raise FileNotFoundError(incoming)
    marker = incoming / (stem + ".ready")
    lock = incoming / ("." + stem + ".enqueue-lock")
    with lock.open("x"):
        pass
    created = []
    try:
        if any((incoming / (stem + ext)).exists()
               for ext in (*media_extensions, *image_extensions, ".json", ".ready")):
            raise FileExistsError(stem)
        sources = [video, metadata] + ([thumbnail] if thumbnail else [])
        for source in sources:
            final = incoming / (stem + source.suffix.lower())
            partial = final.with_name("." + final.name + ".partial")
            with source.open("rb") as src, partial.open("xb") as dst:
                created.append(partial)
                before = source.stat()
                shutil.copyfileobj(src, dst, length=4 * 1024 * 1024)
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise OSError("Source changed during transfer")
            partial.replace(final)
            created[-1] = final
        with marker.open("x"):
            pass
    except (OSError, ValueError):
        for path in created:
            path.unlink(missing_ok=True)
        raise
    finally:
        lock.unlink()
    return marker


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("metadata", type=Path)
    parser.add_argument("--incoming", type=Path, required=True)
    parser.add_argument("--thumbnail", type=Path)
    parser.add_argument("--name")
    args = parser.parse_args()
    print(enqueue(args.video, args.metadata, args.incoming, name=args.name, thumbnail=args.thumbnail))
