"""Spiele-Bibliothek: fertige Spielprofile (Schluesselwoerter, Bildhinweise, Entwickler).

Quellen: der Ordner `game-library` neben diesem Modul (eigene Profile, mit `developer`)
und der Profilordner des mitgelieferten Nightcut (`../nightcut/profiles`).
Ein eigenes Profil mit gleichem Namen ueberschreibt das von Nightcut.
"""
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
# Gebaute .exe (tray\\*.exe): der mitgelieferte Nightcut liegt dann neben dem Ordner der .exe
APP = Path(sys.executable).resolve().parents[1] if getattr(sys, "frozen", False) else HERE.parent
SOURCES = (APP / "nightcut" / "profiles", HERE / "game-library")


def normalize(name):
    return re.sub(r"[^0-9a-z]+", "", str(name).casefold())


def presets():
    """{normalisierter Name: (Anzeigename, Pfad)}"""
    found = {}
    for folder in SOURCES:
        for path in sorted(folder.glob("*.yaml")) if folder.is_dir() else []:
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
            except (OSError, yaml.YAMLError):
                continue
            if isinstance(data, dict) and data.get("name"):
                found[normalize(data["name"])] = (str(data["name"]), path)
    return found


def names():
    return sorted((name for name, _ in presets().values()), key=str.casefold)


def find(name):
    """Profil-Daten (dict) zu einem Spielnamen, oder None."""
    entry = presets().get(normalize(name))
    if entry is None:
        return None
    return yaml.safe_load(entry[1].read_text(encoding="utf-8-sig"))


def developer(game, explicit=None):
    """Entwicklername fuer den Beschreibungs-Fuss: ausdruecklich gesetzt, sonst aus der Bibliothek."""
    if explicit:
        return explicit
    data = find(game)
    return data.get("developer") if data else None
