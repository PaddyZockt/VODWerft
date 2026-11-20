"""One output folder per run.

A folder with the name of the recording may already be there: from the same run (the
night was interrupted: go on there), or from another one (another recording with the
same name, other settings, an older nightcut). Results of two runs must never end up
mixed in one folder, so every run notes what it was made from in `run.json`, and a
run that does not match gets a folder of its own: `<name>_2`, `<name>_3`, ...
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from . import __version__

# Do not change the result: where it is written, which GPUs work on it, the price list of the report.
NOT_SETTINGS = ("output_dir", "gpus", "pricing_file")


def fingerprint(sources: list[Path], cfg: dict, mode: str) -> dict:
    """What a run is made from: the recordings, the mode, the settings and the nightcut version."""
    settings = {k: v for k, v in cfg.items() if k not in NOT_SETTINGS}
    if isinstance(settings.get("editor"), dict):
        # the answer to "fill up?" may change between two starts: the pipeline cuts again by itself
        settings["editor"] = {k: v for k, v in settings["editor"].items() if k != "fill"}
    text = json.dumps(settings, sort_keys=True, ensure_ascii=False, default=str)
    return {"recordings": [{"name": s.name, "size": s.stat().st_size} for s in sources],
            "mode": mode, "settings": hashlib.sha1(text.encode("utf-8")).hexdigest()[:16],
            "nightcut": __version__}


def read_log(folder: Path) -> dict | None:
    """The run.json of a folder, or None when there is none that can be read."""
    try:
        log = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return log if isinstance(log, dict) and isinstance(log.get("stages"), dict) else None


def difference(log: dict | None, now: dict) -> str | None:
    """Why the run in a folder is not this run. None: it is this run."""
    if log is None:
        return "holds files that are not from a nightcut run"
    saved = log.get("project")
    if not saved:
        return "holds a run of an older nightcut version"
    if saved.get("recordings") != now["recordings"]:
        several = len(now["recordings"]) > 1 or len(saved.get("recordings") or []) > 1
        return "holds a run of other recordings" if several else "holds a run of another recording with the same name"
    if saved.get("mode") != now["mode"]:
        return f"holds a {saved.get('mode')} run"
    if saved.get("nightcut") != now["nightcut"]:
        return f"holds a run of nightcut {saved.get('nightcut')}"
    if saved.get("settings") != now["settings"]:
        return "holds a run with other settings"
    return None


def _same_recordings(log: dict | None, now: dict) -> bool:
    """A run of these recordings in this mode (a run of an older nightcut did not note them: trusted)."""
    if log is None:
        return False
    saved = log.get("project")
    return not saved or (saved.get("recordings") == now["recordings"] and saved.get("mode") == now["mode"])


def _in_use(folder: Path) -> bool:
    return folder.is_dir() and any(folder.iterdir()) or folder.is_file()


def choose(output_dir: Path, name: str, now: dict, forced: bool = False) -> tuple[Path, str]:
    """The folder for this run and a line for the log (empty for a first run).

    - a folder with exactly this run: go on there, finished stages are skipped
    - `--force` and a folder with a run of these recordings: stay there, although settings or the
      nightcut version changed (you say from which stage on it is made again)
    - otherwise: the first free folder; folders of other runs are left as they are
    """
    base = output_dir / name
    numbered = {}
    if output_dir.is_dir():
        for p in output_dir.iterdir():
            m = re.fullmatch(re.escape(name) + r"_(\d+)", p.name)
            if m and int(m.group(1)) >= 2:
                numbered[int(m.group(1))] = p
    folders = [base] + [numbered[n] for n in sorted(numbered)]
    used = [(f, read_log(f)) for f in folders if _in_use(f)]

    for folder, log in used:
        if difference(log, now) is None:
            done = len(log["stages"])
            return folder, (f"Going on in {folder} (same recording and settings, {done} finished "
                            f"stage{'' if done == 1 else 's'})." if done else "")
    if forced:
        for folder, log in reversed(used):
            if _same_recordings(log, now):
                return folder, (f"{folder} {difference(log, now)}. --force: staying in this folder, "
                                "stages before the forced one are taken as they are.")
    if not used or used[0][0] != base:
        return base, ""
    n = 2
    while _in_use(output_dir / f"{name}_{n}"):
        n += 1
    folder = output_dir / f"{name}_{n}"
    return folder, (f"{base} {difference(used[0][1], now)} and is left as it is. This run writes to {folder}."
                    + (" To make only a part of the old run again, use --force <stage>."
                       if _same_recordings(used[0][1], now) else ""))


def missing_files(result, folder: Path) -> list[Path]:
    """Files inside the run folder that a finished stage names in its result but that are gone."""
    root = os.path.normcase(os.path.abspath(folder)) + os.sep
    found: list[Path] = []

    def walk(value):
        if isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                walk(v)
        elif isinstance(value, str) and os.path.isabs(value) and not os.path.exists(value) \
                and os.path.normcase(os.path.abspath(value)).startswith(root):
            found.append(Path(value))

    walk(result)
    return found
