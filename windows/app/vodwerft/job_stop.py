"""Auftrag stoppen: Das Dashboard legt eine Wunschdatei an, der Watcher beendet daraufhin den laufenden Auftrag.

Dashboard und Watcher sind getrennte Programme. Deshalb reden sie über eine kleine Datei miteinander:
`<Arbeitsordner>/<Auftrag>.stop`. Der Watcher schaut alle 5 Sekunden nach (er wartet ohnehin auf das Ende des
Auftrags), beendet den Auftrag samt seiner Hilfsprogramme (ffmpeg usw.) und merkt sich den Zustand "stopped".
Fertige Zwischenergebnisse bleiben liegen; "Export erneut versuchen" setzt den Auftrag später dort fort.
Reine Logik ohne Tk, damit sie testbar ist.
"""
import subprocess
import sys
import time
from pathlib import Path


class JobStopped(Exception):
    """Der Auftrag wurde auf Wunsch des Nutzers beendet (kein Fehler)."""


def stop_file(work, key):
    return Path(work) / f"{key}.stop"


def request_stop(work, key):
    """Legt die Wunschdatei an. Eine Datei, die der Watcher schon beachtet hat, ist längst gelöscht."""
    stop_file(work, key).write_text(str(int(time.time())), encoding="utf-8")


def requested(work, key):
    return stop_file(work, key).is_file()


def clear(work, key):
    """Löscht eine alte Wunschdatei (beim Start eines Auftrags und nach dem Stoppen)."""
    try:
        stop_file(work, key).unlink(missing_ok=True)
    except OSError:
        pass


def kill_tree(child):
    """Beendet den Auftrag und alles, was er gestartet hat (ffmpeg, Spracherkennung, ...).

    Unter Windows beendet `taskkill /T` den ganzen Prozessbaum. `child.kill()` allein ließe ffmpeg weiterrechnen."""
    if sys.platform == "win32":
        try:
            subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        child.kill()
    except OSError:
        pass


def wait_for(child, work, key, limit, command, tick=None, step=5):
    """Wartet auf das Ende von `child` und gibt den Rückgabewert zurück.

    Alle `step` Sekunden: Stopp gewünscht? (dann JobStopped), Zeitgrenze erreicht? (dann TimeoutExpired),
    sonst `tick()` aufrufen (z. B. fertig gerenderte Folgen schon übergeben)."""
    deadline = time.monotonic() + limit
    while True:
        try:
            return child.wait(timeout=step)
        except subprocess.TimeoutExpired:
            if requested(work, key):
                kill_tree(child)
                child.wait()
                raise JobStopped(key) from None
            if time.monotonic() >= deadline:
                child.kill()
                child.wait()
                raise subprocess.TimeoutExpired(command, limit) from None
            if tick:
                tick()
