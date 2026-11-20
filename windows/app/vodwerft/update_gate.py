"""Läuft gerade eine Bearbeitung? Dann darf nicht aktualisiert werden (update.ps1 bricht in dem Fall ab).

Dieselbe Regel wie in update.ps1 und im Setup der öffentlichen Version: ein ffmpeg-Prozess oder ein Prozess mit
`run_letsplay.py` oder `clip_run.py` (Clip-Stufe, rechnet lange ohne ffmpeg) in der Befehlszeile.
Das Dashboard fragt vorher und bietet an, das Update erst nach dem Ende der Bearbeitung einzuspielen.
Ist die Abfrage nicht möglich, gilt "nicht beschäftigt"; update.ps1 (private Version) bzw. das Setup (öffentliche Version) prüft vor dem Einspielen ohnehin noch einmal.
"""
import subprocess

COMMAND = ("if ((Get-Process -Name ffmpeg -ErrorAction SilentlyContinue) -or "
           "(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'run_letsplay\\.py|clip_run\\.py' })) "
           "{ 'busy' } else { 'idle' }")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
RECHECK_SECONDS = 60


def busy(run=subprocess.run, timeout=30):
    """True, wenn gerade gerendert oder bearbeitet wird."""
    try:
        result = run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", COMMAND], capture_output=True,
                     text=True, encoding="utf-8", errors="replace", timeout=timeout, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and "busy" in (result.stdout or "")
