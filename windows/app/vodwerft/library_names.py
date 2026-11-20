"""Lesbare Namen für Ordner und Dateien, die du selbst durchsuchst (zuerst: die Hochkant-Clips).

Intern bleibt der Hash (`se-84937072df4df4cb89b2`) die ID eines Auftrags: Datenbank, Upload und Aufräumen hängen
daran. Die Ordner, die du siehst, bekommen zusätzlich ein Datum und einen Namen, und die Kennung steht nur noch
als kurzes `[84937]` am Ende. So findet man eine Aufnahme nach Datum und Inhalt wieder, und zwei Aufnahmen vom
selben Tag bleiben trotzdem auseinanderzuhalten. Reine Logik ohne Tk, getestet in tests/test_library_names.py.
"""
import json
import re
import time
from pathlib import Path

STAMP = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:[ T_-]+(\d{2})-(\d{2})(?:-\d{2})?)?")
FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
BRACKET = re.compile(r"(?:^| )\[([0-9a-f]{6,20})\]$")
SUFFIX_LENGTH = 6
LONGER = (6, 12, 20)       # bei gleicher Kurzkennung zweier Aufträge: längere Kennung nehmen
MARKER_FILE = ".auftrag"   # steht im Clip-Ordner: der volle Auftragsschlüssel
LIST_FILE = ".clips.json"  # steht im Clip-Ordner: Namen der Clips, die der Watcher selbst abgelegt hat


def clean(text, limit=80):
    """Macht aus Text einen gültigen Datei- oder Ordnernamen (ohne verbotene Zeichen, ohne Punkt/Leerzeichen am Ende)."""
    text = FORBIDDEN.sub(" ", str(text or ""))
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text[:limit].rstrip(" .")


def short_id(key, length=SUFFIX_LENGTH):
    """Kurzkennung aus dem Auftragsschlüssel: `se-84937072df4df4cb89b2` -> `849370`."""
    return key.rpartition("-")[2][:length]


def recording_stamp(name, modified=None):
    """(Datum, Uhrzeit) einer Aufnahme: aus dem Dateinamen ("SR-2026-11-20 19-42-10" -> "2026-11-20", "19-42"), sonst
    aus der Änderungszeit der Datei, sonst (None, None)."""
    found = STAMP.search(str(name))
    if found:
        year, month, day, hour, minute = found.groups()
        return f"{year}-{month}-{day}", f"{hour}-{minute}" if hour else None
    if modified:
        moment = time.localtime(modified)
        return time.strftime("%Y-%m-%d", moment), time.strftime("%H-%M", moment)
    return None, None


def clip_folder_name(key, source_name, modified=None, label=None, length=SUFFIX_LENGTH):
    """Ordnername für die Clips einer Aufnahme: `2026-11-20 19-42 [849370]`.

    `label` ersetzt die Uhrzeit durch einen Namen (z. B. die Mission bei Arma: `2026-10-26 OP Nachtschatten [529787]`)."""
    day, clock = recording_stamp(source_name, modified)
    parts = [part for part in (day, clean(label, 60) if label else clock) if part]
    return " ".join([*parts, f"[{short_id(key, length)}]"]) if parts else f"[{short_id(key, length)}]"


def free_folder_name(root, key, source_name, modified=None, label=None, taken=()):
    """Der erste Ordnername für diesen Auftrag, der unter `root` noch frei oder schon seiner ist: erst mit kurzer, bei einer
    Kollision (anderer Auftrag, gleiche Kennung) mit längerer Kennung."""
    for length in LONGER:
        name = clip_folder_name(key, source_name, modified, label, length)
        folder = Path(root) / name
        if name not in taken and (not folder.exists() or owner(folder) == key):
            return name
    return clip_folder_name(key, source_name, modified, label, LONGER[-1])


def clip_file_name(number, title=None, suffix=".mp4"):
    """`Clip 03 – Schiff explodiert.mp4` (ohne Titel: `Clip 03.mp4`)."""
    title = clean(title, 70)
    return f"Clip {number:02d} – {title}{suffix}" if title else f"Clip {number:02d}{suffix}"


def owner(folder):
    """Voller Auftragsschlüssel, der in der Markierung `.auftrag` des Ordners steht, oder None (ältere Ordner)."""
    try:
        return (Path(folder) / MARKER_FILE).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def claim(folder, key):
    """Merkt den vollen Schlüssel im Ordner, damit zwei Aufträge mit gleicher Kurzkennung nie denselben Ordner teilen."""
    try:
        (Path(folder) / MARKER_FILE).write_text(key, encoding="utf-8")
    except OSError:
        pass


def find_folder(root, key):
    """Vorhandener Ordner dieses Auftrags unter `root` (neuer Name mit Kennung oder alter Hash-Name) oder None.

    Die Kennung im Namen ist nur ein Anfang des Schlüssels; steht im Ordner die Markierung `.auftrag`, muss sie zum
    vollen Schlüssel passen (sonst gehört der Ordner einem anderen Auftrag mit gleicher Kennung)."""
    root = Path(root)
    old = root / key
    if old.is_dir():
        return old
    tail = key.rpartition("-")[2]
    try:
        for folder in sorted(root.iterdir()):
            found = BRACKET.search(folder.name)
            if not folder.is_dir() or not found or not tail.startswith(found[1]):
                continue
            who = owner(folder)
            if who is None or who == key:
                return folder
    except OSError:
        pass
    return None


def clip_titles(output):
    """Titel der Hochkant-Clips aus dem Ergebnis der Clip-Stufe: {"short_01.mp4": "Schiff explodiert", ...}."""
    try:
        entries = json.loads((Path(output) / "highlights" / "shorts.json").read_text(encoding="utf-8"))
        return {Path(str(entry["file"]).replace(chr(92), "/")).name: str(entry.get("title", ""))
                for entry in entries if isinstance(entry, dict) and "file" in entry}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def number_of(clip_name):
    """Laufende Nummer aus `short_03.mp4` oder `Clip 03 – Titel.mp4`, sonst None."""
    found = re.match(r"(?:short_|Clip )(\d+)", clip_name)
    return int(found[1]) if found else None
