"""Reserve one future YouTube time slot per episode, in Berlin time."""
import os
import sqlite3
import subprocess
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@lru_cache(maxsize=512)
def berlin_slot(day, hour=19, minute=0):
    local = datetime.combine(day, time(hour, minute))
    try:
        return local.replace(tzinfo=ZoneInfo("Europe/Berlin")).astimezone(timezone.utc)
    except ZoneInfoNotFoundError:
        if os.name != "nt":
            raise
        script = (
            f"$d=[datetime]::new({day.year},{day.month},{day.day},{hour},{minute},0); "
            "$z=[TimeZoneInfo]::FindSystemTimeZoneById('W. Europe Standard Time'); "
            "[TimeZoneInfo]::ConvertTimeToUtc($d,$z).ToString('yyyy-MM-ddTHH:mm:ssZ')"
        )
        powershell = os.path.join(os.environ["SystemRoot"], "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        stamp = subprocess.check_output([powershell, "-NoProfile", "-NonInteractive", "-Command", script],
                                        text=True, creationflags=subprocess.CREATE_NO_WINDOW).strip()
        return datetime.fromisoformat(stamp)


def next_slot(earliest, after=None, blocked=(), weekdays=(0, 3)):
    if not weekdays or any(day not in range(7) for day in weekdays):
        raise ValueError("Set at least one valid release weekday")
    if after is not None:
        earliest = max(earliest, after + timedelta(seconds=1))
    day = earliest.date()
    while True:
        if day.weekday() in weekdays:
            slot = berlin_slot(day)
            if slot >= earliest and slot.isoformat() not in blocked:
                return slot
        day += timedelta(days=1)


def reserve(path, episode_key, now=None, blocked=(), after_date=None, weekdays=(0, 3)):
    now = now or datetime.now(timezone.utc)
    earliest = now + timedelta(hours=24)
    if after_date:
        first_day = date.fromisoformat(after_date) + timedelta(days=1)
        earliest = max(earliest, berlin_slot(first_day, hour=0))
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS releases (episode TEXT PRIMARY KEY, utc TEXT UNIQUE NOT NULL)")
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT utc FROM releases WHERE episode=?", (episode_key,)).fetchone()
        if row:
            return row[0]
        previous = db.execute("SELECT MAX(utc) FROM releases").fetchone()[0]
        manual = read_manual(db)
        slot = next_slot(earliest, datetime.fromisoformat(previous) if previous else None,
                         (*blocked, *manual.values()), weekdays)
        value = slot.isoformat()
        db.execute("INSERT INTO releases VALUES (?,?)", (episode_key, value))
        return value


def read_manual(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='manual_releases'").fetchone():
        return {}
    return dict(db.execute("SELECT episode, utc FROM manual_releases"))


def reserve_manual(path, episode, day, hour, minute, blocked=()):
    return reserve_manual_batch(path, [(episode, day)], hour, minute, blocked)[episode]


def replace_unpublished_slot(path, episode, stamp, blocked=()):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        for table in ("releases", "manual_releases"):
            db.execute(f"CREATE TABLE IF NOT EXISTS {table} (episode TEXT PRIMARY KEY, utc TEXT UNIQUE NOT NULL)")
            if db.execute(f"SELECT 1 FROM {table} WHERE utc=? AND episode<>?", (stamp, episode)).fetchone():
                raise ValueError("Dieser Veröffentlichungstermin ist bereits belegt.")
        if stamp in blocked:
            raise ValueError("Dieser Veröffentlichungstermin ist bereits belegt.")
        if db.execute("SELECT 1 FROM releases WHERE episode=?", (episode,)).fetchone():
            db.execute("UPDATE releases SET utc=? WHERE episode=?", (stamp, episode))
        else:
            db.execute("INSERT INTO manual_releases VALUES (?,?) ON CONFLICT(episode) DO UPDATE SET utc=excluded.utc",
                       (episode, stamp))


def reserve_manual_batch(path, episodes, hour, minute, blocked=()):
    slots = [(episode, berlin_slot(day, hour, minute)) for episode, day in episodes]
    if not slots or len({episode for episode, _ in slots}) != len(slots) or len({slot for _, slot in slots}) != len(slots):
        raise ValueError("Jede Folge braucht einen eigenen Termin.")
    minimum = datetime.now(timezone.utc) + timedelta(hours=24)
    if any(slot < minimum for _, slot in slots):
        raise ValueError("Wähle einen Termin mindestens 24 Stunden im Voraus.")
    stamps = {episode: slot.isoformat() for episode, slot in slots}
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE IF NOT EXISTS releases (episode TEXT PRIMARY KEY, utc TEXT UNIQUE NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS manual_releases (episode TEXT PRIMARY KEY, utc TEXT UNIQUE NOT NULL)")
        manual = read_manual(db)
        used = set(blocked) | set(manual.values())
        for episode, stamp in stamps.items():
            if episode in manual or stamp in used or db.execute(
                    "SELECT 1 FROM releases WHERE utc=? OR episode=?", (stamp, episode)).fetchone():
                day = dict(episodes)[episode]
                raise ValueError(f"Folge {episode.rsplit('-ep', 1)[-1]} oder der {day:%d.%m.%Y} "
                                 f"um {hour:02d}:{minute:02d} ist bereits eingeplant.")
        db.executemany("INSERT INTO manual_releases VALUES (?, ?)", stamps.items())
    return stamps
