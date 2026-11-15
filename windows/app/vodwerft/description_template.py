"""Beschreibungsvorlage eines Spiels: dieselbe Beschreibung für alle Folgen, ohne KI-Text."""
from pathlib import Path

LIMIT = 5000  # YouTube erlaubt höchstens 5000 Zeichen


def default_text(game, developer=None, channel=None):
    """Startvorlage für ein neues Spiel; die Kapitelmarken hängt das Programm pro Folge selbst an."""
    lines = [f"Willkommen zu meinen {game}-Folgen!", "",
             "Hier steht deine Beschreibung. Erzähle kurz, worum es in der Serie geht.", "",
             "Wenn dir die Videos gefallen, lass gerne ein Abo da!", "",
             f"YouTube: {channel or 'https://www.youtube.com/@DEIN-KANAL'}", "", f"Spiel: {game}"]
    if developer:
        lines.append(f"Entwickler: {developer}")
    return "\n".join(lines) + "\n"


def template_path(config):
    value = config.get("description")
    return Path(value) if value else None


def read_text(path):
    return Path(path).read_text(encoding="utf-8-sig")


def write_text(path, text):
    """Speichert die Vorlage; zu lange Texte lehnt es mit einer verständlichen Meldung ab."""
    text = text.replace("\r\n", "\n").strip()
    if not text:
        raise ValueError("Die Beschreibungsvorlage darf nicht leer sein.")
    if len(text) > LIMIT:
        raise ValueError(f"Die Beschreibung ist {len(text) - LIMIT} Zeichen zu lang (höchstens {LIMIT}, "
                         "dazu kommen noch die Kapitelmarken).")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(text + "\n", encoding="utf-8")
    temp.replace(path)
