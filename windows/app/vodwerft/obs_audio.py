"""Recognize an OBS six-track layout without guessing on unrelated recordings."""
import json
import subprocess

TITLES = ("MIX LIVE", "MIC", "DESKTOP", "TEAMSPEAK", "DISCORD", "GAME")
OBS_TRACKS = (1, 3, 4, 5)


def split_audio(source, *, require_known_layout=True):
    raw = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
        "stream_tags=title", "-of", "json", str(source),
    ])
    tracks = json.loads(raw)["streams"]
    if len(tracks) == 1:
        return False
    titles = tuple(stream.get("tags", {}).get("title", "").upper() for stream in tracks)
    if titles not in (TITLES, tuple(f"SOURCE RECORD TRACK {i}" for i in range(1, 7))):
        if require_known_layout:
            raise ValueError("Unbekannte Mehrspurbelegung. Spuren vor der Bearbeitung prüfen.")
        return False
    return True
