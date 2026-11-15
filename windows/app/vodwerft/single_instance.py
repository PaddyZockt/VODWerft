"""Einzelinstanz fuer Dashboard und Tray (Verhalten wie bei Steam, TeamSpeak oder Discord).

- Es gibt nur ein Dashboard-Fenster. Ein zweiter Start (Klick auf das Tray-Symbol, Verknuepfung) oeffnet kein
  neues Fenster, sondern bittet das offene, sich zu zeigen.
- Das Dashboard laeuft weiter, wenn man es mit dem X schliesst und der Tray laeuft; es ist dann nur versteckt.
- Der Tray "Beenden" bittet das Dashboard, sich ebenfalls zu beenden.

Technik: Sperrdateien (`dashboard.lock`, `tray.lock`) im Datenordner `production`. Das Betriebssystem gibt sie
frei, sobald das Programm endet, auch nach einem Absturz. Anforderungen laufen ueber kleine Marker-Dateien
(`dashboard-show.flag`, `dashboard-quit.flag`) mit Zeitstempel; aeltere als STALE_SECONDS gelten als erledigt.
Der C#-Tray (VODWerft) haelt `tray.lock` mit FileShare.None und schreibt dieselben Marker.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

DASHBOARD_LOCK = "dashboard.lock"
TRAY_LOCK = "tray.lock"
SHOW_FLAG = "dashboard-show.flag"
QUIT_FLAG = "dashboard-quit.flag"
STALE_SECONDS = 15.0


class Lock:
    """Gehaltene Sperre. Wird freigegeben, wenn das Objekt freigegeben wird oder das Programm endet."""

    def __init__(self, handle):
        self._handle = handle

    def release(self):
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            handle.close()
        except OSError:
            pass


def _try_lock(handle) -> bool:
    if sys.platform == "win32":
        import msvcrt
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def acquire(folder, name: str):
    """Sperre holen. Gibt ein Lock zurueck oder None, wenn sie schon jemand haelt."""
    folder = Path(folder)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        handle = open(folder / name, "a+b")
    except OSError:
        return None  # z. B. vom C#-Tray mit FileShare.None gehalten
    if not _try_lock(handle):
        handle.close()
        return None
    return Lock(handle)


def is_locked(folder, name: str) -> bool:
    lock = acquire(folder, name)
    if lock is None:
        return True
    lock.release()
    return False


def acquire_dashboard(folder):
    return acquire(folder, DASHBOARD_LOCK)


def acquire_tray(folder):
    return acquire(folder, TRAY_LOCK)


def dashboard_running(folder) -> bool:
    return is_locked(folder, DASHBOARD_LOCK)


def tray_running(folder) -> bool:
    return is_locked(folder, TRAY_LOCK)


def _write_flag(folder, name: str, now: float | None = None) -> None:
    folder = Path(folder)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(repr(time.time() if now is None else now), encoding="ascii")
    except OSError:
        pass


def _take_flag(folder, name: str, now: float | None = None) -> bool:
    """True, wenn eine frische Anforderung vorlag. Die Datei wird dabei immer entfernt."""
    path = Path(folder) / name
    try:
        stamp = float(path.read_text(encoding="ascii"))
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        stamp = 0.0  # unleserlich oder halb geschrieben: wie veraltet behandeln
    try:
        path.unlink()
    except OSError:
        return False  # ein anderer hat sie gerade genommen
    return (time.time() if now is None else now) - stamp <= STALE_SECONDS


def request_show(folder, now: float | None = None) -> None:
    _write_flag(folder, SHOW_FLAG, now)


def take_show(folder, now: float | None = None) -> bool:
    return _take_flag(folder, SHOW_FLAG, now)


def request_quit(folder, now: float | None = None) -> None:
    _write_flag(folder, QUIT_FLAG, now)


def take_quit(folder, now: float | None = None) -> bool:
    return _take_flag(folder, QUIT_FLAG, now)


def clear_flags(folder) -> None:
    for name in (SHOW_FLAG, QUIT_FLAG):
        try:
            (Path(folder) / name).unlink()
        except OSError:
            pass
