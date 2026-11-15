"""Systemprüfung und Fehlerbericht.

Die Systemprüfung zeigt auf einen Blick, ob alles da ist, was die Pipeline braucht (ffmpeg, Ollama, Grafikkarte,
Speicherplatz, Server, Hintergrunddienste). Der Fehlerbericht packt Version, Prüfergebnis und die letzten Zeilen der
Protokolle in eine ZIP-Datei, die man weitergeben kann. Passwörter, Tokens und der Benutzername werden dabei entfernt.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import version

OK, WARN, FAIL = "ok", "warn", "fail"
LOG_TAIL_BYTES = 200_000
LOG_FILES = ("watcher.log", "oberflaeche.log", "ollama.log", "upload-worker.log", "upload-worker.err.log",
             "status_report.log", "update.log")
SECRET_PATTERNS = [
    (re.compile(r'("(?:access_token|refresh_token|client_secret|token|password|passwort|api_key|secret)"\s*:\s*)"[^"]*"',
                re.I), r'\1"***"'),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.I), r"\1***"),
    (re.compile(r"(client_secret=|access_token=|refresh_token=|code=)[^&\s]+", re.I), r"\1***"),
]
GIB = 1024 ** 3


def redact(text, user=None):
    """Entfernt Zugangsdaten und ersetzt den Windows-Benutzernamen in Pfaden."""
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    user = user or os.environ.get("USERNAME") or os.environ.get("USER") or ""
    if len(user) >= 3:
        text = re.sub(re.escape(user), "<Benutzer>", text, flags=re.I)
    return text


def _item(name, state, text):
    return {"name": name, "state": state, "text": text}


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _port_open(host, port, timeout=0.6):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _gpu():
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        result = subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader"], capture_output=True,
                                text=True, timeout=6, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    line = (result.stdout or "").strip().splitlines()
    return line[0].strip() if result.returncode == 0 and line else None


def health(config, production, now=None, gpu=_gpu, port_open=_port_open):
    """Liste von {"name", "state": ok|warn|fail, "text"} für alle wichtigen Voraussetzungen."""
    now = time.time() if now is None else now
    production = Path(production)
    items = []

    ffmpeg = Path(config.get("ffmpeg_directory") or "") / "ffmpeg.exe"
    items.append(_item("ffmpeg", OK, "gefunden") if ffmpeg.is_file()
                 else _item("ffmpeg", FAIL, "nicht gefunden – ohne ffmpeg kann nichts geschnitten werden"))

    ollama = Path(config.get("ollama") or "")
    if not ollama.is_file():
        items.append(_item("Ollama", FAIL, "nicht gefunden – die KI-Schritte können nicht laufen"))
    elif port_open("127.0.0.1", 11434):
        items.append(_item("Ollama", OK, "läuft"))
    else:
        items.append(_item("Ollama", OK, "installiert, wird bei Bedarf gestartet"))

    card = gpu()
    items.append(_item("Grafikkarte", OK, card) if card
                 else _item("Grafikkarte", WARN, "keine NVIDIA-Karte erkannt – Schnitt und KI laufen sehr langsam"))

    work = Path(config.get("work") or production)
    try:
        usage = shutil.disk_usage(work if work.exists() else production)
        free = usage.free / GIB
        text = f"{free:.0f} GB frei auf dem Arbeitslaufwerk"
        items.append(_item("Speicherplatz", FAIL if free < 10 else WARN if free < 50 else OK, text))
    except OSError:
        items.append(_item("Speicherplatz", WARN, "Arbeitsordner nicht lesbar"))

    inbox = Path(config.get("input") or "")
    items.append(_item("Eingangsordner", OK, str(inbox)) if inbox.is_dir()
                 else _item("Eingangsordner", FAIL, "existiert nicht – neue Aufnahmen werden nicht erkannt"))

    status = _read_json(production / "tray-status.json")
    if status is None:
        items.append(_item("Hintergrunddienste", FAIL, "Statusdienst meldet sich nicht"))
    else:
        age = int(now - (production / "tray-status.json").stat().st_mtime)
        items.append(_item("Hintergrunddienste", OK if age < 90 else WARN,
                           "laufen" if age < 90 else f"letzte Rückmeldung vor {age // 60} Min"))

    server = _read_json(production / "server-status.json")
    if server:
        state = str(server.get("state", "unknown"))
        items.append(_item("Server", OK if state in ("ok", "direct") else WARN if state in ("unknown", "mismatch")
                           else FAIL, str(server.get("text", state))))
    return items


def summary(items):
    worst = FAIL if any(i["state"] == FAIL for i in items) else WARN if any(i["state"] == WARN for i in items) else OK
    return worst


def as_text(items):
    marks = {OK: "OK     ", WARN: "ACHTUNG", FAIL: "FEHLER "}
    return "\n".join(f"{marks[i['state']]} {i['name']}: {i['text']}" for i in items)


def _tail(path, limit=LOG_TAIL_BYTES):
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            handle.seek(max(0, size - limit))
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def build_report(destination, config, production, app_dir=None):
    """Schreibt die ZIP-Datei und gibt ihren Pfad zurück."""
    production = Path(production)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    items = health(config, production)
    head = [
        f"Programm: {version.full() or version.read()}",
        f"Basis Nightcut: {version.nightcut_version() or 'unbekannt'}",
        f"Erstellt: {time.strftime('%d.%m.%Y %H:%M:%S')}",
        f"System: {platform.platform()}",
        f"Python: {sys.version.split()[0]}",
        "", "Systemprüfung:", as_text(items),
    ]
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bericht.txt", redact("\n".join(head)))
        settings = production / "watcher.json"
        if settings.is_file():
            try:
                archive.writestr("watcher.json", redact(settings.read_text(encoding="utf-8")))
            except OSError:
                pass
        for name in LOG_FILES:
            text = _tail(production / name)
            if text:
                archive.writestr("protokolle/" + name, redact(text))
    return destination
