"""Turn one Nightcut Let's Play episode into a checked MP4 and upload package."""
import argparse
import json
import math
import subprocess
import tempfile
from contextlib import nullcontext
from pathlib import Path

from bundle import enqueue, job_name, read_metadata
from transitions import KINDS as TRANSITIONS, HART, is_seam, piece_filters

ENCODERS = ("auto", "h264_nvenc", "libx264")


def probe_video(path):
    raw = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height,bit_rate",
        "-of", "json", str(path),
    ])
    info = json.loads(raw)
    kinds = {s["codec_type"] for s in info["streams"]}
    value = float(info["format"]["duration"])
    if not {"video", "audio"} <= kinds or not math.isfinite(value) or value <= 0:
        raise ValueError(f"Expected video, audio and a positive duration in {path.name}")
    video = next(stream for stream in info["streams"] if stream["codec_type"] == "video")
    return value, video


def video_info(path):
    value, video = probe_video(path)
    return value, video["width"], video["height"]


def duration(path):
    return video_info(path)[0]


def render(manifest, episode, sources, audio_track, target, encoder, trim_start=0, resume_work=None,
           mix_tracks=(), transition=HART):
    eps = json.loads(manifest.read_text(encoding="utf-8"))
    matches = [ep for ep in eps if ep["n"] == episode]
    if len(matches) != 1 or not matches[0]["pieces"]:
        raise ValueError(f"Episode {episode} not found")
    if audio_track < 0 or target.exists():
        raise ValueError("Use a non-negative audio track and a new output name")
    if not math.isfinite(trim_start) or trim_start < 0 or (trim_start and len(sources) != 1):
        raise ValueError("The intro cut requires a finite, non-negative time and one source")
    source_info = [probe_video(source) for source in sources]
    pieces = matches[0]["pieces"]
    for piece in pieces:
        index, start, end = piece["file"], piece["start"], piece["end"]
        if not isinstance(index, int) or not 0 <= index < len(sources):
            raise ValueError("Supply the original sources in Nightcut's input order")
        if not 0 <= start < end <= source_info[index][0] + 0.05:
            raise ValueError("Invalid segment bounds in the episode manifest")
    if trim_start:
        pieces = [{**p, "start": max(p["start"], trim_start)} for p in pieces if p["end"] > trim_start]
        if not pieces:
            raise ValueError("The intro cut would remove the entire episode")
        print(f"Vorspann bis {trim_start:.3f} s der Aufnahme entfernt", flush=True)

    base = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-n"]
    if transition not in TRANSITIONS:
        raise ValueError("Unknown transition")
    graph = None
    if mix_tracks:
        inputs = "".join(f"[0:a:{index}]" for index in mix_tracks)
        graph = (f"{inputs}amix=inputs={len(mix_tracks)}:normalize=0:dropout_transition=0,"
                 "alimiter=limit=0.95:level=0:latency=1")

    def audio_map(fade=""):
        """Ton eines Teils; `fade` ist die Ton-Überblendung für Übergänge (leer bei hartem Schnitt)."""
        if graph:
            return ["-filter_complex", f"{graph}{fade}[mixed]", "-map", "[mixed]"]
        return ["-map", f"0:a:{audio_track}"] + (["-af", fade.lstrip(",")] if fade else [])
    videos = [source_info[index][1] for index in {piece["file"] for piece in pieces}]
    width, height = (2560, 1440) if all(v["width"] >= 2560 and v["height"] >= 1440 for v in videos) else (1920, 1080)
    print(f"Exportauflösung: {width} × {height}", flush=True)
    video_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    )
    if encoder == "auto" and all(v["codec_name"] == "av1" for v in videos):
        encoder = "av1_nvenc"
        fallback = 20_000_000 if height == 1440 else 12_000_000
        rates = {}
        for index in {p["file"] for p in pieces}:
            rate = source_info[index][1].get("bit_rate", "N/A")
            rates[index] = int(rate) if rate.isdigit() and int(rate) > 0 else fallback
            if rates[index] == fallback and rate != str(fallback):
                print(f"Keine Videobitrate in {sources[index].name}; nutze {fallback // 1_000_000} Mbit/s", flush=True)
        total = sum(p["end"] - p["start"] for p in pieces)
        target_rate = round(sum((p["end"] - p["start"]) * rates[p["file"]] for p in pieces) / total)
        encode = ["-preset", "p5", "-rc", "vbr", "-b:v", str(target_rate),
                  "-maxrate", str(target_rate * 5 // 4), "-bufsize", str(target_rate * 5 // 2)]
        print(f"Export: AV1 mit Zielbitrate {target_rate / 1_000_000:.2f} Mbit/s", flush=True)
    else:
        if encoder == "auto":
            encoder = "h264_nvenc"
        encode = (["-preset", "p5", "-cq", "19"] if encoder == "h264_nvenc"
                  else ["-preset", "fast", "-crf", "19"])
    if resume_work is not None:
        resume_work = resume_work.resolve(strict=True)
        if resume_work.parent != target.parent.resolve() or not resume_work.name.startswith("episode-"):
            raise ValueError("Resume only from an episode work folder next to the target")
    workspace = (nullcontext(resume_work) if resume_work is not None
                 else tempfile.TemporaryDirectory(prefix="episode-", dir=target.parent))
    with workspace as temporary:
        work = Path(temporary)
        concat = work / "segments.ffconcat"
        telemetry = work / "render-progress.txt"
        progress = work / "render-state.json"
        total_seconds = sum(p["end"] - p["start"] for p in pieces)
        finished_seconds = 0.0
        files = []
        for n, piece in enumerate(pieces, 1):
            print(f"Rendern: Teil {n} von {len(pieces)}", flush=True)
            segment = work / f"segment-{n:06d}.mp4"
            length = piece["end"] - piece["start"]
            # Übergang: Effekt am Anfang/Ende des Teils, Länge des Teils bleibt gleich (keine Überlappung)
            # (an reinen Dateiwechseln ohne Schnitt, z. B. OBS-Teildateien, gibt es keinen Übergang)
            durations = {index: info[0] for index, info in enumerate(source_info)}
            seam_before = n > 1 and is_seam(pieces[n - 2], piece, durations)
            seam_after = n < len(pieces) and is_seam(piece, pieces[n], durations)
            fade_video, fade_audio = piece_filters(transition, n, len(pieces), length, (width, height),
                                                   seam_before, seam_after)
            if resume_work is not None and segment.is_file():
                try:
                    actual, stream = probe_video(segment)
                except (subprocess.CalledProcessError, ValueError, KeyError):
                    actual, stream = 0, {}
                expected_codec = "av1" if encoder == "av1_nvenc" else "h264"
                if (abs(actual - length) <= 0.08 and stream.get("codec_name") == expected_codec
                        and (stream.get("width"), stream.get("height")) == (width, height)):
                    print(f"Abschnitt {n} bereits vollständig", flush=True)
                    files.append(f"file '{segment.name}'\n")
                    finished_seconds += length
                    continue
                segment.unlink()
            telemetry.unlink(missing_ok=True)
            pending_state = progress.with_suffix(".tmp")
            pending_state.write_text(json.dumps({
                "segment": n, "segments": len(pieces), "segment_seconds": length,
                "finished_seconds": finished_seconds, "total_seconds": total_seconds,
            }), encoding="utf-8")
            pending_state.replace(progress)
            subprocess.run(base + [
                "-stats_period", "2", "-progress", str(telemetry),
                "-ss", f'{piece["start"]:.3f}', "-i", str(sources[piece["file"]]),
                "-t", f"{length:.3f}", "-map", "0:v:0", *audio_map(fade_audio),
                "-vf", video_filter + fade_video, "-r", "60", "-c:v", encoder, *encode,
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2",
                "-b:a", "192k", str(segment),
            ], check=True)
            files.append(f"file '{segment.name}'\n")
            finished_seconds += length
        concat.write_text("".join(files), encoding="ascii")
        pending = work / "episode.mp4"
        if resume_work is not None:
            pending.unlink(missing_ok=True)
        subprocess.run(base + [
            "-f", "concat", "-safe", "1", "-i", str(concat), "-c", "copy",
            "-movflags", "+faststart", str(pending),
        ], check=True)
        if abs(duration(pending) - total_seconds) > max(0.5, len(pieces) * 0.08):
            raise ValueError("Rendered duration differs from the Nightcut episode")
        pending.rename(target)
        if resume_work is not None:
            for n in range(1, len(pieces) + 1):
                (work / f"segment-{n:06d}.mp4").unlink()
            concat.unlink()
            telemetry.unlink(missing_ok=True)
            progress.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--episode", type=int, required=True)
    parser.add_argument("--audio-track", type=int, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--encoder", choices=ENCODERS, default="h264_nvenc")
    parser.add_argument("--trim-start", type=float, default=0, help="Start of the episode in source seconds")
    parser.add_argument("--thumbnail", type=Path)
    parser.add_argument("--transition", choices=TRANSITIONS, default=HART, help="Übergang an den Schnitten der Folge")
    parser.add_argument("--incoming", type=Path, help="Publish the complete package to this queue")
    args = parser.parse_args()
    read_metadata(args.metadata, allow_publish=True)
    if args.output.suffix != ".mp4" or not job_name.fullmatch(args.output.stem):
        parser.error("--output must be a new .mp4 with a simple, unique name")
    render(args.manifest, args.episode, args.source, args.audio_track, args.output, args.encoder, args.trim_start,
           transition=args.transition)
    print(f"MP4 geprüft: {args.output}")
    if args.incoming:
        print(enqueue(args.output, args.metadata, args.incoming, thumbnail=args.thumbnail))


if __name__ == "__main__":
    main()
