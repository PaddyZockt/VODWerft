"""Bibliothek: eine lesbare Übersicht aller hochgeladenen Folgen, ohne den Upload-Ablauf anzufassen.

Der Ordner `Fertig/<Hash>-epNN` bleibt, wie er ist: Er ist das Gedächtnis des Upload-Dienstes ("diese Folge ist schon
hochgeladen") und hängt an Prüfung und Aufräumen. Daneben entsteht `Bibliothek/<Spiel>/2026-10-26 Folge 06 – Titel.url`:
Ein Doppelklick öffnet das Video auf YouTube. Die Übersicht wird nur aus `Fertig` gelesen und bei jedem Durchlauf
ergänzt; sie ändert nichts an `Fertig`. Reine Logik ohne Tk, getestet in tests/test_library_overview.py.
"""
import json
import re
from pathlib import Path

import library_names
from atomic import atomic_write

INDEX = ".index.json"
STEM = re.compile(r"^(?P<prefix>[a-z0-9]+)-(?P<hex>[0-9a-f]{20})-ep(?P<number>\d+)$")
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def read_json(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def entries(fertig):
    """Hochgeladene Folgen aus `Fertig`: {Ordnername: {game, number, title, day, video_id}}. Unfertiges fehlt."""
    result = {}
    try:
        folders = sorted(Path(fertig).iterdir())
    except OSError:
        return result
    for folder in folders:
        found = STEM.match(folder.name)
        if not found or not folder.is_dir() or folder.is_symlink():
            continue
        receipt = read_json(folder / "result.json")
        video_id = receipt.get("video_id")
        if receipt.get("state") != "uploaded" or not isinstance(video_id, str) or not VIDEO_ID.match(video_id):
            continue
        meta = read_json(folder / (folder.name + ".json"))
        day = str(meta.get("recordingDate") or str(meta.get("publishAt", ""))[:10] or "")
        result[folder.name] = {
            "game": library_names.clean(meta.get("_vodwerft_game"), 60) or "Sonstige",
            "number": int(found["number"]),
            "title": library_names.clean(meta.get("title"), 90) or folder.name,
            "day": day if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else "",
            "video_id": video_id,
        }
    return result


def file_name(entry):
    head = " ".join(part for part in (entry["day"], f"Folge {entry['number']:02d}") if part)
    return f"{head} – {entry['title']}.url"


def content(entry):
    return f"[InternetShortcut]\r\nURL=https://youtu.be/{entry['video_id']}\r\n"


def refresh(share):
    """Gleicht `<share>/Bibliothek` mit `<share>/Fertig` ab. Gibt die Zahl der neu geschriebenen Verknüpfungen zurück."""
    share = Path(share)
    found = entries(share / "Fertig")
    if not found:
        return 0
    root = share / "Bibliothek"
    index = read_json(root / INDEX)
    relatives = {stem: f"{entry['game']}/{file_name(entry)}" for stem, entry in found.items()}
    for relative in {r for r in relatives.values() if list(relatives.values()).count(r) > 1}:
        # Gleiches Spiel, Datum, Nummer und Titel bei zwei Folgen: die Kennung aus dem Ordnernamen unterscheidet sie
        for stem in [s for s, r in relatives.items() if r == relative]:
            relatives[stem] = relative[:-len(".url")] + f" [{stem.split('-')[1][:6]}].url"
    written = 0
    for stem, relative in relatives.items():
        target = root / relative
        if index.get(stem) == relative and target.is_file():
            continue
        old = index.get(stem)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content(found[stem]), encoding="utf-8")
        if old and old != relative and old not in relatives.values():
            # Titel oder Datum haben sich geändert: die alte Verknüpfung entfällt, aber nur innerhalb der Bibliothek
            # (der Index liegt auf der Freigabe und gilt nicht als vertrauenswürdig)
            try:
                old_path = (root / old).resolve()
                if old_path.is_relative_to(root.resolve()) and old_path.suffix == ".url":
                    old_path.unlink(missing_ok=True)
            except (OSError, ValueError):
                pass
        index[stem] = relative
        written += 1
    if written:
        atomic_write(root / INDEX, json.dumps(index, ensure_ascii=False, indent=1))
    return written
