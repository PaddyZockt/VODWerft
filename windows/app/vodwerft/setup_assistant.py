"""Einrichtungsassistent (Logik): erzeugt aus ein paar Antworten die komplette Konfiguration.

Keine Oberflaeche hier, damit alles testbar bleibt; die Fenster stehen in setup_wizard.py.
Sichere Voreinstellungen: jede Folge wird vor dem Upload geprueft (require_approval) und der Upload bleibt gesperrt,
bis die Datei `upload-freigabe.flag` im Datenordner existiert.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import yaml

from game_library import find as find_preset

OLLAMA_MODELS = ["qwen2.5vl:7b", "qwen3:14b"]
MIN_VRAM_MB = 15500  # "16 GB" laut Nightcut; Karten melden knapp darunter
GATE_FILE = "upload-freigabe.flag"
DEFAULT_DESCRIPTION = (
    "Hier steht deine Beschreibung des Videos. Erzaehle kurz, worum es geht und wo man dich findet.\n\n"
    "Wenn dir die Videos gefallen, lass gerne ein Abo da!\n\n"
    "YouTube: ${channel}\n"
)


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "spiel"


def job_prefix(name):
    return "g" + hashlib.sha256(name.casefold().encode()).hexdigest()[:8]


def valid_game_name(name):
    name = name.strip()
    return (bool(re.fullmatch(r"[\w][\w .&()+’'-]{0,69}", name)) and not name.endswith(".")
            and not re.fullmatch(r"(?i)(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?", name))


def detect_environment():
    """Sucht ffmpeg, Ollama, uv und den Grafikspeicher. Fehlendes bleibt None."""
    found = {"ffmpeg_directory": None, "ollama": None, "uv": None, "vram_mb": None, "gpu": None}
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
        hits = sorted(packages.glob("Gyan.FFmpeg*/*/bin/ffmpeg.exe")) if packages.is_dir() else []
        ffmpeg = str(hits[-1]) if hits else None
    if ffmpeg:
        found["ffmpeg_directory"] = str(Path(ffmpeg).parent)
    ollama = shutil.which("ollama")
    if not ollama:
        candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
        ollama = str(candidate) if candidate.is_file() else None
    found["ollama"] = ollama
    found["uv"] = shutil.which("uv")
    try:
        text = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            text=True, timeout=8, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        name, memory = [part.strip() for part in text.strip().splitlines()[0].split(",")]
        found["gpu"], found["vram_mb"] = name, int(float(memory))
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        pass
    return found


def check_requirements(env):
    """Liste der Probleme (leer = alles da)."""
    problems = []
    if not env.get("ffmpeg_directory"):
        problems.append("ffmpeg fehlt (Installation: winget install Gyan.FFmpeg)")
    if not env.get("ollama"):
        problems.append("Ollama fehlt (Installation: winget install Ollama.Ollama)")
    if not env.get("vram_mb"):
        problems.append("Keine NVIDIA-Grafikkarte erkannt. Die Videoverarbeitung braucht eine NVIDIA-Karte mit 16 GB Grafikspeicher")
    elif env["vram_mb"] < MIN_VRAM_MB:
        problems.append(f"Grafikspeicher {env['vram_mb'] // 1024} GB gefunden, 16 GB werden empfohlen")
    return problems


def validate(answers):
    games = answers.get("games") or []
    if not games:
        raise ValueError("Bitte mindestens ein Spiel angeben.")
    names = set()
    for game in games:
        if not valid_game_name(game["name"]):
            raise ValueError(f"Ungültiger Spielname: {game['name']!r} (keine Sonderzeichen wie : / \\ ? * \" < > |)")
        if game["name"].casefold() in names:
            raise ValueError(f"Spiel doppelt angegeben: {game['name']}")
        names.add(game["name"].casefold())
        if not 5 <= int(game.get("minutes", 25)) <= 180:
            raise ValueError("Folgenlänge muss zwischen 5 und 180 Minuten liegen.")
        days = game.get("weekdays", [0, 3])
        if not days or any(day not in range(7) for day in days):
            raise ValueError("Bitte mindestens einen Veröffentlichungstag wählen.")
    for key in ("data_dir", "ffmpeg_directory", "ollama"):
        if not answers.get(key):
            raise ValueError(f"Angabe fehlt: {key}")
    if answers.get("mode", "server") not in ("server", "direct"):
        raise ValueError("Unbekannter Upload-Modus.")
    if answers.get("mode", "server") == "server" and not answers.get("share"):
        raise ValueError("Bitte die Server-Freigabe angeben (Ordner, in dem der Upload-Server arbeitet).")


def nightcut_yaml(minutes):
    return {
        "layout": {"gameplay": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}, "facecam": None},
        "audio": {"game": None, "party": None, "mix": None},
        "letsplay": {"strength": "gentle", "episodes": "by_length", "episode_minutes": int(minutes),
                     "title_format": "{series} #{n:02d} – {title}"},
        "metadata": {"enabled": True},
    }


def build(answers):
    """Rein berechnend: {Pfad: Inhalt} aller Dateien und die Liste der anzulegenden Ordner."""
    validate(answers)
    data = Path(answers["data_dir"])
    production, config_dir = data / "production", data / "config"
    direct = answers.get("mode", "server") == "direct"
    # Direkt-Modus: Der Upload laeuft auf diesem PC, die "Freigabe" ist ein lokaler Ordner im Datenordner.
    share = data / "uploader" if direct else Path(answers["share"])
    files, folders = {}, [production, config_dir]
    if direct:
        folders += [share / ".upload", share / "Fertig", share / "Pruefen", share / ".status", share / "state", share / "secrets"]
    profiles = []
    for game in answers["games"]:
        name = game["name"].strip()
        stem = slug(name)
        prefix = job_prefix(name)
        inbox = Path(game.get("input") or (Path(answers.get("recordings_dir") or data / "Aufnahmen") / name))
        work = production / prefix
        preset = find_preset(name) or {}
        profile_yaml = {key: value for key, value in preset.items() if key != "developer"} or \
            {"name": name, "keywords": {}, "vision_hints": name}
        profile_yaml["name"] = name
        files[config_dir / f"{stem}.yaml"] = yaml.safe_dump(profile_yaml, allow_unicode=True, sort_keys=False)
        files[config_dir / f"{stem}-{int(game.get('minutes', 25))}min.yaml"] = yaml.safe_dump(
            nightcut_yaml(game.get("minutes", 25)), allow_unicode=True, sort_keys=False)
        description = game.get("description") or DEFAULT_DESCRIPTION
        description = description.replace("${channel}", answers.get("channel_url") or "https://www.youtube.com/@DEIN-KANAL")
        files[config_dir / f"{stem}-description.txt"] = description
        entry = {
            "series": name, "job_prefix": prefix, "first_episode": int(game.get("first_episode", 1)),
            "input": str(inbox), "work": str(work), "state": str(production / "series.sqlite3"),
            "profile": str(config_dir / f"{stem}.yaml"),
            "nightcut_config": str(config_dir / f"{stem}-{int(game.get('minutes', 25))}min.yaml"),
            "description": str(config_dir / f"{stem}-description.txt"),
            "audio_track": int(game.get("audio_track", 1)) - 1,
            "manual_release": False, "publish_weekdays": list(game.get("weekdays", [0, 3])),
            "require_approval": True,
        }
        if preset.get("developer"):
            entry["developer"] = preset["developer"]
        folders += [inbox, work]
        profiles.append(entry)
    main, extra = profiles[0], profiles[1:]
    root = {
        **main,
        "encoder": "auto", "stable_seconds": 90, "poll_seconds": 15,
        "ffmpeg_directory": answers["ffmpeg_directory"], "ollama": answers["ollama"],
        "ollama_models": OLLAMA_MODELS, "ollama_log": str(production / "ollama.log"),
        "upload_incoming": str(share / ".upload"), "blocked_utc_slots": [],
        "upload_gate": str(data / GATE_FILE),
        "retention_enabled": False, "pc_cleanup": "off",
    }
    if direct:
        root["upload_mode"] = "direct"
    if answers.get("title_suffix"):
        root["title_suffix"] = answers["title_suffix"]
    if extra:
        root["additional_profiles"] = []
        for entry in extra:
            path = production / f"{entry['job_prefix']}.json"
            # weitere Spiele erben Rechner-Einstellungen aus der Hauptdatei, nur Spielfelder stehen im Profil
            shared = {key: value for key, value in root.items() if key not in ("additional_profiles",)}
            files[path] = json.dumps({**shared, **entry}, ensure_ascii=False, indent=2)
            root["additional_profiles"].append(str(path))
    files[production / "watcher.json"] = json.dumps(root, ensure_ascii=False, indent=2)
    return files, folders


def write(answers, *, overwrite=False):
    """Schreibt alles. Eine vorhandene Einrichtung wird nur mit overwrite=True ersetzt (dann mit Sicherung)."""
    files, folders = build(answers)
    main = next(path for path in files if path.name == "watcher.json")
    if main.exists():
        if not overwrite:
            raise FileExistsError(f"{main} existiert schon. Bitte zuerst sichern oder bewusst ersetzen.")
        backup = main.parent.parent / "einrichtung-sicherung"
        backup.mkdir(exist_ok=True)
        for path in files:
            if path.exists():
                shutil.copy2(path, backup / (path.name + ".alt"))
    for folder in folders:
        Path(folder).mkdir(parents=True, exist_ok=True)
    for path, content in files.items():
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(content, encoding="utf-8")
    return main


def set_upload_allowed(data_dir, allowed):
    gate = Path(data_dir) / GATE_FILE
    if allowed:
        gate.write_text("Uploads freigegeben\n", encoding="utf-8")
    else:
        gate.unlink(missing_ok=True)
    return gate.exists()


def secrets_dir(data_dir):
    return Path(data_dir) / "uploader" / "secrets"


def install_client_secrets(data_dir, source):
    """Kopiert die heruntergeladene client_secrets.json an ihren Platz (nur nach Pruefung, dass es ein Desktop-Client ist)."""
    from youtube_login import load_client
    source = Path(source)
    load_client(source.parent if source.name == "client_secrets.json" else _check_copy(source))
    target = secrets_dir(data_dir)
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target / "client_secrets.json")
    return target / "client_secrets.json"


def _check_copy(source):
    """load_client erwartet einen Ordner mit der Datei 'client_secrets.json'; fremd benannte Dateien werden so geprueft."""
    import tempfile
    folder = Path(tempfile.mkdtemp())
    shutil.copy2(source, folder / "client_secrets.json")
    return folder


def youtube_state(data_dir):
    """'fehlt' | 'client' (Zugangsdatei da, noch nicht angemeldet) | 'angemeldet'."""
    folder = secrets_dir(data_dir)
    if not (folder / "client_secrets.json").is_file():
        return "fehlt"
    return "angemeldet" if (folder / "request.token").is_file() else "client"


def parse_presets(argv):
    """Vorgaben des Installers (--mode, --data-dir, --share) als Dict; Unbekanntes wird ignoriert."""
    keys = {"--mode": "mode", "--data-dir": "data_dir", "--share": "share"}
    result, i = {}, 0
    while i < len(argv):
        key = keys.get(argv[i])
        if key and i + 1 < len(argv):
            result[key] = argv[i + 1]
            i += 2
        else:
            i += 1
    if result.get("mode") not in (None, "server", "direct"):
        del result["mode"]
    return result
