"""Programmversion (SemVer, z. B. 0.1.0-beta.1). Quelle ist die Datei VERSION neben dem Programmordner."""
import re
import sys
from pathlib import Path

PATTERN = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.]+))?(?:\+[0-9A-Za-z.]+)?")


def read(directory=None):
    """Version aus der Datei VERSION (Standard: eine Ebene ueber diesem Ordner), sonst 'unbekannt'."""
    if directory:
        base = Path(directory)
    elif getattr(sys, "frozen", False):  # gebaute .exe: VERSION liegt neben dem Ordner der .exe (tray\\*.exe)
        base = Path(sys.executable).resolve().parents[1]
    else:
        base = Path(__file__).resolve().parent.parent
    try:
        text = (base / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "unbekannt"
    return text if PATTERN.fullmatch(text) else "unbekannt"


def parse(text):
    match = PATTERN.fullmatch(str(text).strip())
    if not match:
        return None
    major, minor, patch, pre = match.groups()
    return int(major), int(minor), int(patch), pre


def compatible(pc, server):
    """PC und Server passen zusammen, wenn MAJOR gleich ist (bei 0.x auch MINOR). Unbekanntes gilt als passend."""
    a, b = parse(pc), parse(server)
    if not a or not b:
        return True
    return a[0] == b[0] and (a[0] != 0 or a[1] == b[1])


def nightcut_version():
    """Version des mitgelieferten Nightcut (aus dessen pyproject.toml), sonst ''."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parents[1]
    else:
        base = Path(__file__).resolve().parent.parent
    try:
        for line in (base / "nightcut" / "pyproject.toml").read_text(encoding="utf-8").splitlines():
            match = re.fullmatch(r'version\s*=\s*"([^"]+)"', line.strip())
            if match and PATTERN.fullmatch(match.group(1)):
                return match.group(1)
    except OSError:
        pass
    return ""
