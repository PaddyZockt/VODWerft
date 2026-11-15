"""Run Nightcut highlights with one visible caption at a time."""
import argparse
import os
import subprocess
import sys

import numpy as np

from nightcut import shorts


FFMPEG_TIMEOUT = 900  # Sekunden für das Lesen eines Tonausschnitts (höchstens rund eine Minute Ton)


def track_words(source, tracks, sample_rate, start, end, config, asr, transcribe):
    words = []
    for track in tracks:
        raw = subprocess.check_output([
            "ffmpeg", "-v", "error", "-nostdin", "-ss", str(start), "-i", source,
            "-t", str(end - start), "-map", f"0:a:{track}", "-ac", "1", "-ar",
            str(sample_rate), "-f", "s16le", "pipe:1",
        ], timeout=FFMPEG_TIMEOUT)
        pcm = np.frombuffer(raw, dtype="<i2")
        if pcm.size and np.max(np.abs(pcm.astype(np.int32))) >= 32:
            words.append(transcribe(pcm, sample_rate, 0, end - start, config, asr))
    return words


def limit_events(events):
    """Nur eine Einblendung zur selben Zeit: Eine Zeile endet, sobald die nächste beginnt."""
    # Zeilen ohne sichtbare Dauer (unter einer Hundertstelsekunde, der Auflösung der ASS-Zeitangaben) zuerst
    # verwerfen: Sonst würden sie die vorherige Zeile abschneiden und danach selbst wegfallen.
    visible = [event for event in events if round(event["end"] * 100) > round(event["start"] * 100)]
    ordered = sorted(visible, key=lambda event: round(event["start"] * 100))
    limited = []
    for index, event in enumerate(ordered):
        end = event["end"]
        if index + 1 < len(ordered):
            end = min(end, ordered[index + 1]["start"])
        # Vergleich in Hundertstelsekunden, der Auflösung der ASS-Zeitangaben
        if round(end * 100) > round(event["start"] * 100):
            limited.append({**event, "end": end})
    return limited


def recording_argument(argv):
    """Erste Aufnahme aus den Nightcut-Argumenten (`run <Aufnahme> ...`), unabhängig von der Reihenfolge der Optionen."""
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("command")
    parser.add_argument("recordings", nargs="*")
    for names in (("--mode", "-m"), ("--strength",), ("--name",), ("--profile", "-p"), ("--config", "-c"),
                  ("--output", "-o"), ("--gpus",)):
        parser.add_argument(*names)
    parser.add_argument("--force", "-f", action="append")
    for flag in ("--no-vision", "--no-llm", "--fill", "--no-fill"):
        parser.add_argument(flag, action="store_true")
    args, _ = parser.parse_known_args(argv)
    if args.command != "run" or not args.recordings:
        raise SystemExit("clip_run.py: Aufruf mit `run <Aufnahme> ...` erwartet (Tonspuren der Aufnahme werden gelesen)")
    return args.recordings[0]


def patch_shorts(caption_audio, source):
    """Ersetzt drei Funktionen von nightcut.shorts; die Signaturen müssen zu den Originalen passen (siehe Test)."""
    def write_ass(words, path, scfg, caption_y):
        tracks = words if isinstance(words, tuple) else (words,)
        style = shorts.caption_style(scfg)
        events = [event for track in tracks for event in shorts.caption_events(track, style)]
        shorts.write_captions(limit_events(events), path, scfg, caption_y, wrap_style=0)

    shorts.write_ass = write_ass
    if caption_audio in ("stems", "mixed"):
        transcribe_original = shorts.word_timestamps

        def word_timestamps(pcm, sample_rate, start, end, cfg, asr):
            if caption_audio == "stems":
                mic_words = transcribe_original(pcm, sample_rate, start, end, cfg, asr)
                chat = track_words(source, (3, 4), sample_rate, start, end, cfg, asr, transcribe_original)
                return (mic_words, *chat)
            voices = track_words(source, (1, 3, 4), sample_rate, start, end, cfg, asr, transcribe_original)
            return tuple(voices) or ([],)

        shorts.word_timestamps = word_timestamps

    if caption_audio == "stems":
        render_original = shorts.render

        def render(info, clip, n, streams, ass, cfg, out_dir, gpu=None):
            discord = info.find_audio({"index": 4})
            return render_original(info, clip, n, {**streams, "discord": discord}, ass, cfg, out_dir, gpu=gpu)

        shorts.render = render


def main():
    caption_audio = os.environ.get("NIGHTCUT_SHORTS_CAPTION_AUDIO", "default")
    source = recording_argument(sys.argv[1:]) if caption_audio in ("stems", "mixed") else None
    patch_shorts(caption_audio, source)
    from nightcut.cli import app

    app()


if __name__ == "__main__":
    main()
