"""Aufräumen nach Updates: alte Sicherungen und liegengebliebene Update-Pakete löschen.

Jedes Update legt eine Sicherung des alten Stands an (`update-backup\\JJJJMMTT-HHMMSS`) und das Dashboard ein
Paket im Temp-Ordner (`vodwerft-update-…`). Beides wuchs bisher unbegrenzt. Hier steht, was gelöscht werden darf:

- Sicherungen: nur Ordner mit genau dem Namensmuster JJJJMMTT-HHMMSS (optional mit Zusatz), alle bis auf die
  neuesten `keep`. Alles andere im Ordner bleibt unberührt.
- Pakete: nur `vodwerft-update-*` direkt im Temp-Ordner, die älter als `max_age` Sekunden sind.

Die Auswahl (`old_backups`, `old_packages`) löscht nichts und ist getestet; gelöscht wird nur in `remove`.
Aufruf (von update.ps1):  python update_cleanup.py backups <Ordner> [--keep 5]
                          python update_cleanup.py packages <Temp-Ordner> [--keep <Ordner>]… [--max-age 86400]
"""
import argparse
import os
import re
import shutil
import stat
import sys
import time
from pathlib import Path

BACKUP_NAME = re.compile(r"\d{8}-\d{6}(?:-[\w.-]+)?")
PACKAGE_PREFIX = "vodwerft-update-"


def _folders(base):
    """Echte Ordner direkt unter base (keine Verknüpfungen, keine Dateien)."""
    base = Path(base)
    if not base.is_dir():
        return []
    is_junction = getattr(Path, "is_junction", lambda self: False)  # Python 3.12 und neuer
    return [p for p in base.iterdir() if p.is_dir() and not p.is_symlink() and not is_junction(p)]


def old_backups(base, keep=5):
    """Sicherungen, die nach den neuesten `keep` übrig sind (neueste zuerst nach Name: das Datum steht vorn)."""
    if keep < 1:
        raise ValueError("Mindestens eine Sicherung muss bleiben.")
    found = sorted((p for p in _folders(base) if BACKUP_NAME.fullmatch(p.name)), key=lambda p: p.name, reverse=True)
    return found[keep:]


def old_packages(temp, *, now=None, max_age=86400, keep=()):
    """Update-Pakete im Temp-Ordner, die älter als max_age Sekunden sind. `keep`: Pfade, die bleiben."""
    now = time.time() if now is None else now
    protected = {Path(k).resolve() for k in keep}
    return [p for p in _folders(temp)
            if p.name.startswith(PACKAGE_PREFIX) and p.resolve() not in protected
            and now - p.stat().st_mtime > max_age]


def rmtree(path):
    """Ordner samt Inhalt löschen, auch mit schreibgeschützten Dateien. Git legt seine Pack-Dateien (.git/objects)
    schreibgeschützt an; Windows verweigert dafür das normale Löschen. Genau deshalb blieben Update-Pakete liegen."""
    def writable_then_again(function, target, _error):
        os.chmod(target, stat.S_IWRITE)
        function(target)
    try:
        shutil.rmtree(path, onexc=writable_then_again)  # Python 3.12 und neuer
    except TypeError:
        shutil.rmtree(path, onerror=writable_then_again)


def size(folder):
    return sum(f.stat().st_size for f in Path(folder).rglob("*") if f.is_file())


def remove(folders):
    """Löscht die Ordner. Gibt (gelöschte Namen, freigegebene Bytes) zurück; was sich nicht löschen lässt, bleibt."""
    done, freed = [], 0
    for folder in folders:
        try:
            amount = size(folder)
            rmtree(folder)
        except OSError:
            continue  # in Benutzung oder keine Rechte: beim nächsten Mal
        done.append(folder.name)
        freed += amount
    return done, freed


def main(argv=None):
    parser = argparse.ArgumentParser(description="Alte Update-Sicherungen und -Pakete löschen")
    parser.add_argument("what", choices=("backups", "packages"))
    parser.add_argument("folder")
    parser.add_argument("--keep", action="append", default=[], help="backups: Anzahl (Standard 5); packages: Pfad, der bleibt")
    parser.add_argument("--max-age", type=int, default=86400)
    parser.add_argument("--dry-run", action="store_true", help="nur anzeigen, nichts löschen")
    args = parser.parse_args(argv)
    if args.what == "backups":
        count = int(args.keep[0]) if args.keep else 5
        chosen = old_backups(args.folder, count)
    else:
        chosen = old_packages(args.folder, max_age=args.max_age, keep=args.keep)
    if args.dry_run:
        for folder in chosen:
            print("würde löschen:", folder.name)
        return 0
    done, freed = remove(chosen)
    for name in done:
        print("gelöscht:", name)
    print(f"{len(done)} Ordner gelöscht, {freed / 1e6:.1f} MB frei.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
