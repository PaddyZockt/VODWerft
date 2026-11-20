"""Run Nightcut and optionally enqueue complete rendered episodes."""
import argparse
import atexit
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path

import yaml

from bundle import enqueue, job_name, read_metadata, thumbnail_for
from export_episode import ENCODERS, TRANSITIONS, render
from obs_audio import OBS_TRACKS, split_audio
from plan_status import PENDING_EXIT_CODE
from proxy import remove_proxies
from series_numbers import save_episode_count, start_batch
from youtube_fields import shift_chapters, trim_offset


def title_words(value, series):
    headline = re.sub(rf"^{re.escape(series)}\s*(?:#\d+|[|–-]\s*Folge\s+\d+)\s*(?:[–:|-]\s*)?",
                      "", value, flags=re.IGNORECASE)
    words = re.findall(r"[^\W_]+", headline.casefold())
    return ["schleuse" if word in {"airlock", "airlocks", "luftschleuse", "luftschleusen", "schleusen"}
            else word for word in words]


def select_episode_title(titles, series, number, recent_titles):
    fallback = f"{series} – Folge {number:02d}"
    candidates = [title.strip()[:100] for title in titles if isinstance(title, str) and title.strip()]
    recent = [title_words(title, series) for title in recent_titles[-2:]]
    previous_words = {word for words in recent for word in words if len(word) >= 5}
    alternatives = []
    for title in candidates:
        words = title_words(title, series)
        if not words or any(SequenceMatcher(None, " ".join(old), " ".join(words)).ratio() >= .82 for old in recent):
            continue
        if title == candidates[0] or previous_words.isdisjoint(words):
            return title
        alternatives.append(title)
    return alternatives[0] if alternatives else fallback


def upload_metadata(draft, series, number, description_template=None, *, recent_titles=()):
    chapters = [f'{entry["at"]} {entry["title"]}' for entry in draft.get("chapters", [])]
    description = description_template if description_template is not None else draft.get("description", "").strip()
    if chapters:
        description += "\n\n" + "\n".join(chapters)
    title = select_episode_title(draft.get("titles", []), series, number, recent_titles)
    return {
        "title": title.strip()[:100],
        "description": description.strip()[:5000],
        "tags": draft.get("tags", []),
        "privacyStatus": "private",
        "categoryId": "20",
        "language": "de",
    }


# Etwas kürzer als das Gesamt-Limit des Watchers (12 h), damit Nightcut zuerst sauber beendet wird.
NIGHTCUT_TIMEOUT = 12 * 3600 - 600


def lock_output(output):
    lock = output.with_name(output.name + ".nightcut-lock").open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        raise
    atexit.register(lock.close)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, nargs="+")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--series", required=True)
    parser.add_argument("--job-name", required=True, help="Unique prefix for this batch")
    parser.add_argument("--first-episode", type=int, help="Initial episode when setting up a new series")
    parser.add_argument("--series-state", type=Path, default=Path(__file__).with_name("series-state.sqlite3"))
    parser.add_argument("--audio-track", type=int, required=True)
    parser.add_argument("--obs-split-audio", action="store_true")
    parser.add_argument("--encoder", choices=ENCODERS, default="h264_nvenc")
    parser.add_argument("--trim-start", type=float, default=0, help="Start of the mission in source seconds")
    parser.add_argument("--incoming", type=Path)
    parser.add_argument("--thumbnail-dir", type=Path, help="Directory with prepared <job-name>-epNN.jpg or .png")
    parser.add_argument("--auto-thumbnail", action="store_true", help="Generate a thumbnail with the draft layout")
    parser.add_argument("--thumbnail-style", choices=("numbered", "project"), default="numbered")
    parser.add_argument("--thumbnail-theme", help="Thumbnail-Stil als JSON (Farben, Schrift); leer = Vorgaben")
    parser.add_argument("--description-template", type=Path)
    parser.add_argument("--mission", help="Fixed mission name for a one-video recording")
    parser.add_argument("--transition", choices=TRANSITIONS, default="hart",
                        help="Übergang an den Schnitten innerhalb einer Folge (Standard: hart)")
    parser.add_argument("--no-chapters", action="store_true",
                        help="Im Missionsmodus keine Kapitel und keine KI-Metadaten erzeugen")
    parser.add_argument("--review-plan", action="store_true",
                        help="Nach der Analyse anhalten, damit der Schnittplan von Hand geprüft werden kann")
    args = parser.parse_args()
    if (not job_name.fullmatch(args.job_name) or len(args.job_name) > 105
            or (args.first_episode is not None and args.first_episode < 1)):
        parser.error("Use a short, unique job name and a positive starting episode number")
    sources = [source.resolve(strict=True) for source in args.source]
    output = args.output.resolve()
    config_bytes = args.config.resolve(strict=True).read_bytes()
    source_config = yaml.safe_load(config_bytes) or {}
    if args.mission and (len(sources) != 1 or source_config.get("letsplay", {}).get("episodes") != "per_recording"):
        parser.error("A mission requires one input and per_recording mode")
    if not math.isfinite(args.trim_start) or args.trim_start < 0 or (args.trim_start and not args.mission):
        parser.error("The intro cut requires a finite, non-negative time and a mission")
    template = (args.description_template.read_text(encoding="utf-8-sig").strip()
                if args.description_template else None)
    layout = source_config.get("layout", {})
    if "facecam" not in layout or (layout["facecam"] and not layout.get("facecam_burned_in")):
        parser.error("Declare facecam: null or an already burned-in facecam in the export config")
    if args.audio_track < 0:
        parser.error("The audio track must be zero or greater")
    separated = [split_audio(source) for source in sources] if args.obs_split_audio else []
    if any(separated) and not all(separated):
        parser.error("Do not mix single-track and multi-track recordings in one job")
    use_stems = bool(separated and all(separated))
    source_info = [{"path": str(source), "size": source.stat().st_size,
                    "modified": source.stat().st_mtime_ns} for source in sources]
    profile_file = Path(args.profile)
    profile = str(profile_file.resolve()) if profile_file.is_file() else args.profile
    batch = {
        "source": source_info, "config": hashlib.sha256(config_bytes).hexdigest(),
        "profile": profile, "audio": args.audio_track, "output": str(output),
        "description": hashlib.sha256(template.encode()).hexdigest() if template is not None else None,
    }
    if args.mission:
        batch["mission"] = args.mission
    if args.trim_start:
        batch["trim_start"] = args.trim_start
    if use_stems:
        batch["obs_split_audio"] = True
    identity = json.dumps(batch, sort_keys=True)
    incoming = args.incoming.resolve(strict=True) if args.incoming else None
    lock_output(output)
    if output.exists() and not (output / "batch-identity.json").is_file():
        parser.error("Choose a new output folder")
    first = start_batch(args.series_state, args.series, args.job_name, identity, args.first_episode)
    output.mkdir(exist_ok=True)
    identity_path = output / "batch-identity.json"
    if identity_path.exists() and identity_path.read_text(encoding="utf-8") != identity:
        raise ValueError("The existing output belongs to a different batch")
    identity_path.write_text(identity, encoding="utf-8")
    source_config.setdefault("letsplay", {}).update(series_name=args.series, first_episode=first)
    if args.review_plan:
        source_config["letsplay"]["review_plan"] = True
    # Der Auftragsordner ist durch Auftragsschlüssel und batch-identity.json eindeutig und wird von Dashboard,
    # Plan prüfen und Kalender fest unter <Ausgabe>/nightcut erwartet: Nightcut darf ihn nie umbenennen (_2).
    source_config["workdir_fixed"] = True
    if args.mission and not args.no_chapters:
        # Missionsprofile schalten die KI-Metadaten ab (Titel und Beschreibung stehen fest). Kapitel und Tags
        # braucht auch eine Mission; Titel und Beschreibung ersetzt der Watcher danach ohnehin.
        source_config.setdefault("metadata", {})["enabled"] = True
    source_config.setdefault("audio", {})["mic"] = {"title": None, "index": args.audio_track}
    if use_stems:
        source_config["audio"].update({
            role: {"title": None, "index": index}
            for role, index in (("mic", 1), ("party", 3), ("mix", 4), ("game", 5))
        })
        print("Tonspuren: MIC für Whisper, TeamSpeak und Discord für Schnittschutz; Export ohne Live-Mix", flush=True)
    effective_config = output / "nightcut-effective.yaml"
    effective_config.write_text(yaml.safe_dump(source_config, allow_unicode=True), encoding="utf-8")
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run([
        sys.executable, "-B", "-u", "-c", "from nightcut.cli import app; app()", "run",
        *map(str, sources), "--mode", "letsplay", "--profile", profile,
        "--config", str(effective_config), "--output", str(output), "--name", "nightcut",
    ], env=environment, timeout=NIGHTCUT_TIMEOUT)
    if result.returncode == PENDING_EXIT_CODE and args.review_plan:
        # Kein Fehler: Der Plan wartet auf die Prüfung. Der Watcher erkennt den Code und lässt den Auftrag stehen.
        print("Plan prüfen: Der Auftrag wartet auf die Bestätigung des Schnittplans.", flush=True)
        sys.exit(PENDING_EXIT_CODE)
    result.check_returncode()
    work = output / "nightcut"
    manifest = work / "episodes.json"
    episodes = json.loads(manifest.read_text(encoding="utf-8"))
    if args.mission and len(episodes) != 1:
        raise ValueError("Expected exactly one video for the mission")
    drafts_path = work / "metadata.json"
    drafts = json.loads(drafts_path.read_text(encoding="utf-8")) if drafts_path.is_file() else []
    if drafts and len(drafts) != len(episodes):
        raise ValueError("Nightcut episode count and metadata count differ")
    save_episode_count(args.series_state, args.series, args.job_name, len(episodes))

    recent_titles = []
    for index, episode in enumerate(episodes):
        number = first + episode["n"] - 1
        print(f"Folge {number:02d}, {index + 1} von {len(episodes)}", flush=True)
        stem = f"{args.job_name}-ep{number:02d}"
        video = output / (stem + ".mp4")
        sidecar = output / (stem + ".json")
        draft = drafts[index] if drafts else {}
        if args.trim_start and draft.get("chapters"):
            # Das Rendern schneidet alles vor dem Missionsbeginn ab: Die Kapitelzeiten verschieben sich entsprechend
            offset = trim_offset(episode["pieces"], args.trim_start)
            draft = {**draft, "chapters": shift_chapters(draft["chapters"], offset, episode["length"] - offset)}
        data = upload_metadata(draft, args.series, number, template, recent_titles=recent_titles)
        if args.mission:
            data["title"] = f"{args.series} | {args.mission}"[:100]
        if not sidecar.exists():
            with sidecar.open("x", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
        recent_titles.append(read_metadata(sidecar)["title"])
        if not video.exists():
            render(manifest, episode["n"], sources, args.audio_track, video, args.encoder, args.trim_start,
                   mix_tracks=OBS_TRACKS if use_stems else (), transition=args.transition)
        cover = thumbnail_for(args.thumbnail_dir / video.name) if args.thumbnail_dir else None
        if args.auto_thumbnail and cover is None:
            from thumbnail import make_thumbnail

            cover = video.with_suffix(".jpg")
            if not cover.exists():
                print(f"Thumbnail: Folge {number:02d}", flush=True)
                make_thumbnail(video, cover, args.series, number, mission=args.mission, style=args.thumbnail_style,
                               theme=json.loads(args.thumbnail_theme) if args.thumbnail_theme else None)
        if cover == video.with_suffix(".jpg") and cover.is_file():
            video.with_suffix(".exported").touch(exist_ok=True)
        if incoming:
            stamp = output / (stem + ".handoff")
            if stamp.exists():
                if stamp.read_text(encoding="utf-8") != str(incoming):
                    raise ValueError("This episode already has a handoff to a different directory")
                print(f"Übergabe für Folge {number:02d} bereits angestoßen. Bei Zweifel im Zielordner prüfen.")
                continue
            # Record the intent first. After an interruption, inspect the queue rather than copying twice.
            with stamp.open("x", encoding="utf-8") as handle:
                handle.write(str(incoming))
            print(enqueue(video, sidecar, incoming, thumbnail=cover), flush=True)

    # Alle Folgen sind gerendert: die Vorschau-Proxys (Plan prüfen) werden nicht mehr gebraucht
    remove_proxies(work)
    shutil.rmtree(work / "browser-profile", ignore_errors=True)


if __name__ == "__main__":
    main()
