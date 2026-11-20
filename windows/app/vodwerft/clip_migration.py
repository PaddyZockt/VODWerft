"""Einmaliger Umzug der alten Clip-Ordner auf lesbare Namen.

Alt: `Clips/<Spiel>/se-84937072df4df4cb89b2/short_01.mp4` (bei Space Engineers direkt unter `Clips/`)
Neu: `Clips/<Spiel>/2026-10-16 17-15 [849370]/Clip 01 – Unerwarteter Angriff.mp4`

Aufruf: `python clip_migration.py <watcher.json>` zeigt nur den Plan (Probelauf). Mit `--apply` wird umbenannt;
die Zuordnung steht danach in `umbenennung-log.json` im Clips-Ordner (so lässt sich alles zurückverfolgen).
Bei Space Engineers wird zusätzlich `clips_output` in der Profildatei auf `Clips/Space Engineers` geändert (mit Sicherung),
damit neue Clips nicht mehr zwischen den Spielordnern landen. Der Watcher ruft `run_once` beim Start selbst auf;
alles ist wiederholbar: was beim ersten Mal nicht ging (z. B. Datei im Player geöffnet), kommt beim nächsten Start dran.
"""
import json
import re
import shutil
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

import library_names
from atomic import atomic_write
from game_profiles import load_profiles
from library_names import clip_titles


def known_sources(work):
    """{Auftragsschlüssel: Name der Quelldatei} aus der Datenbank des Profils."""
    database = Path(work) / "jobs.sqlite3"
    if not database.is_file():
        return {}
    try:
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
            return {key: Path(source).name for key, source in db.execute("SELECT key, source FROM recordings")}
    except sqlite3.Error:
        return {}


def plan(main):
    """Liste der geplanten Umbenennungen: [{"profile", "key", "old", "new", "files": [(alt, neu)]}]. Ändert nichts."""
    profiles = load_profiles(Path(main))
    result, taken = [], set()
    for index, profile in enumerate(profiles):
        output = profile.get("clips_output")
        if not output or not Path(output).is_dir():
            continue
        output = Path(output)
        prefix = profile.get("job_prefix", "se")
        # Hauptprofil (Space Engineers) schrieb bisher direkt in "Clips": seine Ordner ziehen in "Clips/<Spiel>" um.
        # Nach der Umstellung des Profils bleibt übrig Gebliebenes im Elternordner "Clips" im Blick.
        main_profile = index == 0
        target_root = output / profile["series"] if main_profile and output.name != profile["series"] else output
        roots = [output]
        if main_profile and output.name == profile["series"]:
            roots.append(output.parent)
        sources = known_sources(profile["work"])
        for root in roots:
            for folder in sorted(root.iterdir()):
                if not folder.is_dir() or not re.fullmatch(rf"{re.escape(prefix)}-[0-9a-f]{{20}}", folder.name):
                    continue  # schon lesbar benannt oder fremd
                key = folder.name
                source = sources.get(key, "")
                titles = clip_titles(Path(profile["work"]) / key)
                label = None
                name = library_names.free_folder_name(target_root, key, source, folder.stat().st_mtime, label, taken)
                taken.add(name)
                files = []
                for clip in sorted(folder.glob("*.mp4")):
                    number = library_names.number_of(clip.name)
                    if number:
                        files.append((clip.name, library_names.clip_file_name(number, titles.get(clip.name))))
                result.append({"profile": profile["series"], "key": key, "old": str(folder),
                               "new": str(target_root / name), "files": files})
    return result


def apply(items, log_path):
    """Führt den Plan aus. Gibt (umbenannt, übersprungen) zurück. Jeder Ordner für sich: Scheitert einer (z. B. weil eine
    Datei im Player geöffnet ist), kommen die übrigen trotzdem dran, und der Rest folgt beim nächsten Start.
    Bestehende Zielordner werden nie überschrieben. Das Protokoll wird auch bei Teilerfolg geschrieben."""
    done, skipped = [], []
    for item in items:
        old, new = Path(item["old"]), Path(item["new"])
        try:
            if new.exists() or not old.is_dir():
                skipped.append(item)
                continue
            new.parent.mkdir(parents=True, exist_ok=True)
            old.rename(new)
        except OSError:
            skipped.append(item)
            continue
        written = []
        for before, after in item["files"]:
            name = before
            try:
                if (new / before).is_file() and not (new / after).exists():
                    (new / before).rename(new / after)
                    name = after
            except OSError:
                pass  # bleibt unter dem alten Namen
            written.append(name)
        library_names.claim(new, item.get("key", old.name))
        try:
            atomic_write(new / library_names.LIST_FILE, json.dumps(written, ensure_ascii=False))
        except OSError:
            pass
        done.append(item)
    if done:
        entries = []
        if Path(log_path).is_file():
            try:
                entries = json.loads(Path(log_path).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                entries = []
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        entries.extend({"time": stamp, **item} for item in done)
        try:
            atomic_write(log_path, json.dumps(entries, ensure_ascii=False, indent=1))
        except OSError:
            pass
    return done, skipped


def update_main_profile(main):
    """Space Engineers (Hauptprofil): clips_output zeigt auf `Clips/Space Engineers`. Gibt True zurück, wenn geändert.

    Auch die beim Auftragsstart eingefrorenen Profile (`<Auftrag>.profile.json`) bekommen den neuen Ordner, sonst legt ein
    wartender Auftrag (Plan prüfen) oder ein neuer Clip-Versuch seine Clips weiter in den alten Sammelordner."""
    main = Path(main)
    config = json.loads(main.read_text(encoding="utf-8-sig"))
    old = config.get("clips_output")
    output = Path(old or "")
    if not old or output.name == config["series"] or not output.is_dir():
        return False  # nichts eingestellt, schon umgestellt oder der Ordner (Netzlaufwerk) ist gerade nicht erreichbar
    new = str(output / config["series"])
    shutil.copyfile(main, main.with_name(main.name + ".vor-clip-namen"))
    for frozen in sorted(Path(config.get("work", "")).glob("*.profile.json")):
        try:
            data = json.loads(frozen.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict) and data.get("clips_output") == old:
                data["clips_output"] = new
                atomic_write(frozen, json.dumps(data, ensure_ascii=False, indent=2))
        except (OSError, ValueError):
            continue
    config["clips_output"] = new
    # Atomar schreiben: Statusdienst und Dashboard lesen diese Datei, während der Watcher sie ändert
    atomic_write(main, json.dumps(config, ensure_ascii=False, indent=2), fsync=True)
    return True


def run_once(main):
    """Beim Start des Watchers: alte Clip-Ordner umbenennen und das Hauptprofil umstellen. Idempotent: ohne alte
    Ordner und mit schon umgestelltem Profil passiert nichts. Gibt (umbenannte Ordner, Profil geändert) zurück.
    Der Aufrufer sorgt dafür, dass der Watcher läuft und gerade kein Auftrag Clips kopiert."""
    first = load_profiles(Path(main))[0]
    if not first.get("clips_output"):
        return 0, False
    output = Path(first["clips_output"])
    # Das Protokoll liegt im Sammelordner "Clips" (nicht im Spielordner), vor und nach der Umstellung am selben Ort
    log = (output.parent if output.name == first["series"] else output) / "umbenennung-log.json"
    done, _skipped = apply(plan(main), log)
    return len(done), update_main_profile(main)


if __name__ == "__main__":
    arguments = [a for a in sys.argv[1:] if not a.startswith("--")]
    main_file = Path(arguments[0])
    items = plan(main_file)
    for item in items:
        print(f"{item['profile']}: {Path(item['old']).name}  ->  {Path(item['new']).relative_to(Path(item['new']).parents[1])}")
        for before, after in item["files"]:
            print(f"    {before}  ->  {after}")
    print(f"{len(items)} Ordner, {sum(len(i['files']) for i in items)} Dateien.")
    if "--apply" in sys.argv:
        moved, changed = run_once(main_file)
        print(f"Umbenannt: {moved} Ordner. Hauptprofil angepasst: {changed}.")
    else:
        print("Probelauf: nichts verändert. Mit --apply ausführen.")
