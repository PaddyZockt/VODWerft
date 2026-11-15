"""Benutzer-Einstellungen für VODWerft / VODWerft.

Die Datei `settings.json` liegt neben `watcher.json`. Sie speichert NUR die
Abweichungen vom Standard. Dadurch bleiben neue Standardwerte aus Updates
wirksam, solange der Nutzer nichts selbst geändert hat.
"""
import json
from dataclasses import dataclass
from pathlib import Path

import brand
from atomic import atomic_write

FILE_NAME = "settings.json"


@dataclass(frozen=True)
class Option:
    key: str
    category: str
    label: str
    help: str
    kind: str                 # "bool" | "choice"
    default: object
    choices: tuple = ()       # (wert, anzeigetext)
    advanced: bool = False


CATEGORIES = ("Darstellung", "Leistung", "Aufräumen")

SCHEMA = (
    Option("theme", "Darstellung", "Farbschema",
           "Hell, dunkel oder wie Windows eingestellt.", "choice", brand.DEFAULT_THEME,
           (("dunkel", "Dunkel"), ("hell", "Hell"), ("system", "Wie Windows"))),
    Option("encoder", "Leistung", "Video-Encoder",
           "Automatisch nimmt die Grafikkarte (NVENC), sonst den Prozessor.", "choice", "auto",
           (("auto", "Automatisch"), ("h264_nvenc", "Grafikkarte (NVENC)"), ("libx264", "Prozessor (langsamer)")),
           advanced=True),
    Option("pause_while_gaming", "Leistung", "Pausieren, solange ein Spiel läuft",
           "Rendern startet erst, wenn kein Vollbild-Programm im Vordergrund ist.", "bool", False),
    Option("pc_cleanup", "Aufräumen", "Dateien nach dem Upload löschen",
           "Aus: nichts wird automatisch gelöscht. An: Export-Dateien auf dem PC werden erst gelöscht, "
           "wenn YouTube das Video bestätigt hat.", "choice", "off",
           (("off", "Nein, nichts automatisch löschen"), ("auto", "Ja, nach bestätigtem Upload"))),
)

BY_KEY = {option.key: option for option in SCHEMA}


def defaults():
    return {option.key: option.default for option in SCHEMA}


def valid(option, value):
    if option.kind == "bool":
        return isinstance(value, bool)
    return value in {choice[0] for choice in option.choices}


def path_for(directory):
    return Path(directory) / FILE_NAME


def load(directory):
    """Liest settings.json; kaputte oder unbekannte Werte werden ignoriert."""
    values = defaults()
    try:
        stored = json.loads(path_for(directory).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return values
    if isinstance(stored, dict):
        for key, value in stored.items():
            option = BY_KEY.get(key)
            if option and valid(option, value):
                values[key] = value
    return values


def save(directory, values):
    """Speichert nur Werte, die vom Standard abweichen (atomar)."""
    changed = {}
    for key, value in values.items():
        option = BY_KEY.get(key)
        if option is None:
            raise KeyError(key)
        if not valid(option, value):
            raise ValueError(f"Ungültiger Wert für {key}: {value!r}")
        if value != option.default:
            changed[key] = value
    target = path_for(directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(target, json.dumps(changed, indent=2, ensure_ascii=False))
    return changed


def stored(directory):
    """Nur die vom Nutzer gesetzten (gültigen) Werte, ohne Standardwerte."""
    return {key: value for key, value in load(directory).items() if value != BY_KEY[key].default
            or key in _raw(directory)}


def _raw(directory):
    try:
        data = json.loads(path_for(directory).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


PROFILE_KEYS = ("encoder", "pc_cleanup")


def apply_to_profile(profile, overrides):
    """Überlagert ein Watcher-Profil nur mit Werten, die der Nutzer gesetzt hat (Kopie).

    So bleibt eine bestehende watcher.json (z. B. die Live-Installation) unverändert
    wirksam, bis jemand in den Einstellungen bewusst etwas ändert."""
    result = dict(profile)
    for key in PROFILE_KEYS:
        if key in overrides:
            result[key] = overrides[key]
    return result
