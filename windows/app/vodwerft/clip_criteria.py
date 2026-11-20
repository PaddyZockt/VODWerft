"""Clip-Kriterien: Was ein guter Short in einem Spiel ist (Maßstab für den Clip-Richter).

Welcher Text gilt, in dieser Reihenfolge (der erste vorhandene gewinnt):
1. die Kriterien, die du im Profil-Editor für dieses Spiel eingetragen hast (Schlüssel `clip_kriterien` im Profil),
2. die Kriterien des Spiels aus der Spiele-Bibliothek (`game-library/<spiel>.yaml`, Abschnitt `judge`),
3. der allgemeine Standardtext des Richters.

Reine Logik ohne Tk, getestet in tests/test_clip_criteria.py.
"""
import sys
from pathlib import Path

import game_library

KEY = "clip_kriterien"
LIMIT = 2000  # so viele Zeichen sind erlaubt (das Modell bekommt den Text bei jedem Clip)

# Allgemeiner Standard: derselbe Text wie im Richter selbst (eine Quelle), mit Rückfall falls Nightcut fehlt
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "nightcut" / "src"))
try:
    from nightcut.judge import DEFAULT_CRITERIA
except ImportError:  # pragma: no cover - Nightcut fehlt: der Richter läuft dann ohnehin nicht
    DEFAULT_CRITERIA = ""

SOURCE_PROFILE, SOURCE_LIBRARY, SOURCE_DEFAULT = "profil", "bibliothek", "standard"


def library_text(series):
    """Kriterien des Spiels aus der Bibliothek, oder None."""
    data = game_library.find(series) if series else None
    block = data.get("judge") if isinstance(data, dict) else None
    text = str(block.get("criteria") or "").strip() if isinstance(block, dict) else ""
    return text or None


def default_text(series):
    """Was ohne eigenen Eintrag gilt (Bibliothek, sonst allgemeiner Standard)."""
    return library_text(series) or DEFAULT_CRITERIA


def effective(config):
    """(Text, Quelle) der Kriterien für ein Spielprofil (das dict aus der Profildatei)."""
    own = str((config or {}).get(KEY) or "").strip()
    if own:
        return own, SOURCE_PROFILE
    text = library_text((config or {}).get("series"))
    if text:
        return text, SOURCE_LIBRARY
    return DEFAULT_CRITERIA, SOURCE_DEFAULT


def clean(text):
    """Eingabe aus dem Editor prüfen: Leerzeichen am Rand weg, nicht zu lang. Leer = eigenen Eintrag entfernen."""
    text = " ".join(str(text or "").split())
    if len(text) > LIMIT:
        raise ValueError(f"Bitte höchstens {LIMIT} Zeichen verwenden (aktuell {len(text)}).")
    return text


def to_store(text, series):
    """Was in die Profildatei geschrieben wird: nichts (None), wenn der Text leer oder gleich dem Standard des
    Spiels ist, sonst der Text. So folgt ein Profil weiter der Bibliothek, solange du nichts änderst."""
    text = clean(text)
    return None if not text or text == " ".join(default_text(series).split()) else text


def apply(data, config):
    """Kriterien in die Clips-Konfiguration (dict) eintragen. Ein eigener Eintrag im Profil gewinnt; sonst bleibt
    ein Wert aus der Clips-Datei stehen; sonst gilt die Bibliothek. Ohne alles: Standard des Richters (nichts eintragen)."""
    own = str((config or {}).get(KEY) or "").strip()
    shorts = data.setdefault("shorts", {})
    if not isinstance(shorts, dict):
        return data
    judge = shorts.setdefault("judge", {})
    if not isinstance(judge, dict):
        return data
    if own:
        judge["criteria"] = own
    elif not str(judge.get("criteria") or "").strip():
        text = library_text((config or {}).get("series"))
        if text:
            judge["criteria"] = text
    return data
