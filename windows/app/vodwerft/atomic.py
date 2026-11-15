"""Atomares Schreiben kleiner Status- und Einstellungsdateien (eine Stelle statt mehrerer Varianten)."""
import os
import time
from pathlib import Path


def atomic_write(path, data, *, encoding="utf-8", fsync=False, attempts=5, delay=0.2):
    """Schreibt `data` (str oder bytes) in eine Temp-Datei und ersetzt damit `path`.

    Der Temp-Name enthält die Prozess-ID, damit sich zwei Programme (Watcher, Dashboard, Statusdienst)
    nicht gegenseitig die halbfertige Datei überschreiben. Unter Windows scheitert das Ersetzen kurzzeitig
    mit PermissionError, solange ein anderes Programm (Virenscanner, Leser) die Zieldatei offen hat;
    deshalb wird es einige Male wiederholt."""
    path = Path(path)
    payload = data.encode(encoding) if isinstance(data, str) else bytes(data)
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with temp.open("wb") as handle:
            handle.write(payload)
            if fsync:
                handle.flush()
                os.fsync(handle.fileno())
        for attempt in range(max(1, attempts)):
            try:
                os.replace(temp, path)
                return path
            except PermissionError:
                if attempt + 1 >= max(1, attempts):
                    raise
                time.sleep(delay * (attempt + 1))
    finally:
        try:
            temp.unlink()
        except OSError:
            pass
    return path
