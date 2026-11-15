"""Keep episode reservations stable across independent recordings."""
import sqlite3
from contextlib import closing
from pathlib import Path


def connect(path):
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS series (
            name TEXT PRIMARY KEY, next_episode INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS batches (
            series TEXT REFERENCES series(name),
            name TEXT, identity TEXT NOT NULL, first_episode INTEGER NOT NULL,
            count INTEGER, PRIMARY KEY (series, name)
        );
    """)
    return connection


def initialize(path, series, initial):
    with closing(connect(path)) as database, database:
        database.execute("INSERT OR IGNORE INTO series VALUES (?,?)", (series, initial))


def start_batch(path: Path, series, batch, identity, initial=None):
    with closing(connect(path)) as database, database:
        database.execute("BEGIN IMMEDIATE")
        existing = database.execute(
            "SELECT first_episode, identity FROM batches WHERE series=? AND name=?",
            (series, batch),
        ).fetchone()
        if existing:
            if existing[1] != identity:
                raise ValueError("This batch name already belongs to different inputs")
            return existing[0]
        running = database.execute(
            "SELECT name FROM batches WHERE series=? AND count IS NULL", (series,),
        ).fetchone()
        if running:
            raise ValueError(f"Finish or resume the previous batch first: {running[0]}")
        next_number = database.execute(
            "SELECT next_episode FROM series WHERE name=?", (series,),
        ).fetchone()
        if next_number is None:
            first = initial if initial is not None else 1
            database.execute("INSERT INTO series VALUES (?,?)", (series, first))
        else:
            first = next_number[0]
            if initial is not None and initial != first:
                raise ValueError(f"This series already continues at episode {first}")
        database.execute("INSERT INTO batches VALUES (?,?,?,?,NULL)", (series, batch, identity, first))
        return first


def save_episode_count(path, series, batch, count):
    if count < 1:
        raise ValueError("An empty episode list cannot reserve a range")
    with closing(connect(path)) as database, database:
        database.execute("BEGIN IMMEDIATE")
        first, saved = database.execute(
            "SELECT first_episode, count FROM batches WHERE series=? AND name=?", (series, batch),
        ).fetchone()
        if saved is not None:
            if saved != count:
                raise ValueError("The episode count changed after numbers were assigned")
            return
        database.execute(
            "UPDATE batches SET count=? WHERE series=? AND name=?", (count, series, batch),
        )
        database.execute("UPDATE series SET next_episode=? WHERE name=?", (first + count, series))
