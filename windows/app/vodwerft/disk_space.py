"""Speicherplatz-Warnung: genug Platz auf dem Arbeitslaufwerk, bevor gerendert wird. Reine Logik, ohne Tk.

Ein Export braucht Platz für die Teilstücke und die fertige Datei (bei AV1 mit 3 Stunden Arma leicht über 40 GB).
Ist das Laufwerk voll, bricht ffmpeg mitten im Rendern ab, oft erst nach Stunden. Die Warnung kommt deshalb vorher.
Sie hält nichts an (kein Eingriff in laufende Abläufe): sie steht im Verlauf des Auftrags und im Dashboard.
"""
import shutil
from pathlib import Path

GB = 1024 ** 3
MIN_FREE_GB = 20      # darunter warnt das Dashboard immer
FACTOR = 2.2          # Platzbedarf eines Exports im Verhältnis zur Aufnahme (Teilstücke plus fertige Datei)


def free_bytes(path):
    """Freier Platz des Laufwerks, auf dem `path` liegt (auch wenn der Ordner selbst noch nicht existiert)."""
    candidate = Path(path)
    for folder in (candidate, *candidate.parents):
        if folder.exists():
            return shutil.disk_usage(folder).free
    raise OSError(f"Laufwerk zu {path} nicht gefunden")


def drive(path):
    """Kurzer Name des Laufwerks für Meldungen, z. B. "C:"."""
    anchor = Path(path).anchor
    return anchor.rstrip("\\/") or str(path)


def needed_bytes(source_size):
    return max(MIN_FREE_GB * GB, int(source_size * FACTOR))


def warning(work, source_size, *, free=None):
    """Meldung, wenn der Platz für diese Aufnahme voraussichtlich nicht reicht, sonst None. Nie ein Fehler:
    Lässt sich der Platz nicht ermitteln (Netzlaufwerk getrennt), gibt es keine Warnung."""
    try:
        have = free_bytes(work) if free is None else free
    except OSError:
        return None
    need = needed_bytes(source_size)
    if have >= need:
        return None
    return (f"Wenig Speicherplatz auf {drive(work)}: {have / GB:.0f} GB frei, für diese Aufnahme werden etwa "
            f"{need / GB:.0f} GB gebraucht. Bitte Platz schaffen, sonst kann das Rendern abbrechen.")


def label(path):
    """Kurzer Name für die Anzeige: "C:" für ein Laufwerk, der Freigabename für ein Netzlaufwerk (ohne Adresse)."""
    anchor = drive(path)
    if anchor.startswith("\\\\"):  # Netzlaufwerk \\Rechner\Freigabe: nur den Freigabenamen zeigen, nicht die Adresse
        return anchor.split("\\")[-1]
    return anchor


def overview(places, minimum_gb=MIN_FREE_GB):
    """Freier Platz je Laufwerk für die Statuskarte: Liste von Wörterbüchern (name, free_gb, total_gb, level).

    `places` ist eine Liste von (Anzeigename, Pfad); mehrere Pfade auf demselben Laufwerk erscheinen einmal.
    level: "ok", "low" (unter dem Mindestplatz) oder "critical" (unter der Hälfte davon). Nicht erreichbare
    Laufwerke fehlen einfach."""
    result, seen = [], set()
    for name, path in places:
        try:
            candidate = Path(path)
            folder = next(f for f in (candidate, *candidate.parents) if f.exists())
            usage = shutil.disk_usage(folder)
        except (OSError, StopIteration):
            continue
        marker = (Path(path).anchor.casefold(), usage.total)
        if marker in seen:
            continue
        seen.add(marker)
        free = usage.free / GB
        level = "critical" if free < minimum_gb / 2 else "low" if free < minimum_gb else "ok"
        result.append({"name": name, "free_gb": int(free), "total_gb": int(usage.total / GB), "level": level})
    return result


def low_space(paths, minimum_gb=MIN_FREE_GB):
    """Laufwerke unter dem Mindestplatz als Liste von (Laufwerk, freie GB), jedes Laufwerk nur einmal."""
    seen, result = set(), []
    for path in paths:
        try:
            have = free_bytes(path)
        except OSError:
            continue
        name = drive(path)
        if name in seen:
            continue
        seen.add(name)
        if have < minimum_gb * GB:
            result.append((name, have / GB))
    return result
