"""Verbindungsstatus zum Server: erreichbar, Rueckmeldung aktuell, Version passt.

Der Server schreibt etwa jede Minute `server-version.json` ({"version", "updated"}) in den Status-Ordner der Freigabe.
Der Statusdienst wertet sie aus und legt das Ergebnis lokal als `server-status.json` ab; Dashboard und Tray zeigen es an.
"""
import json
import time
from pathlib import Path

from version import compatible

STALE_SECONDS = 180  # der Server meldet sich etwa jede Minute


def evaluate(directory, pc_version, now=None, direct=False):
    """{"state": ok|mismatch|stale|offline|unknown|direct, "text": ..., "server": ...}"""
    now = time.time() if now is None else now
    if direct:
        return {"state": "direct", "text": "Direkt-Modus · kein Server nötig", "server": None}
    directory = Path(directory)
    try:
        if not directory.is_dir():
            return {"state": "offline", "text": "Server nicht erreichbar", "server": None}
        version, updated = "", None
        alive = sorted(directory.glob("server-*.alive"), key=lambda item: item.stat().st_mtime, reverse=True)
        if alive:  # bevorzugt: Version im Dateinamen, Zeit = Aenderungszeit (braucht keinen Dateiinhalt)
            version = alive[0].name[len("server-"):-len(".alive")]
            updated = alive[0].stat().st_mtime
        else:  # aelterer Server: Versionsdatei mit Inhalt
            path = directory / "server-version.json"
            if not path.is_file():
                return {"state": "unknown", "server": None,
                        "text": "Server erreichbar · meldet noch keine Version (bitte Server aktualisieren)"}
            data = json.loads(path.read_text(encoding="utf-8"))
            version = str(data.get("version") or "")
            updated = data.get("updated") or path.stat().st_mtime
        age = max(0, int(now - float(updated)))
    except (OSError, ValueError, TypeError, AttributeError):
        return {"state": "offline", "text": "Server nicht erreichbar", "server": None}
    if age > STALE_SECONDS:
        return {"state": "stale", "server": version or None,
                "text": f"Keine Rückmeldung vom Server seit {age // 60} Min"}
    if version and not compatible(pc_version, version):
        return {"state": "mismatch", "server": version,
                "text": f"Server verbunden · Version {version} passt nicht zu {pc_version}: bitte Server aktualisieren"}
    return {"state": "ok", "server": version or None,
            "text": f"Server verbunden · Version {version} passt" if version else "Server verbunden"}
