"""Durable Windows job events and explicit requests to retry the render."""
import sqlite3
import time
from contextlib import closing


def record(db, key, label, detail=""):
    with db:
        db.execute("CREATE TABLE IF NOT EXISTS job_events (job TEXT, time INTEGER, label TEXT, detail TEXT)")
        db.execute("INSERT INTO job_events VALUES (?,?,?,?)", (key, int(time.time()), label, detail))


def history(folder, key):
    with closing(sqlite3.connect((folder / "jobs.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='job_events'").fetchone():
            return []
        return db.execute("SELECT time,label,detail FROM job_events WHERE job=? ORDER BY rowid DESC LIMIT 120",
                          (key,)).fetchall()


def retry_render(folder, key):
    with closing(sqlite3.connect(folder / "jobs.sqlite3", timeout=3)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT source FROM recordings WHERE key=? AND status='review'", (key,)).fetchone()
        if row is None:
            raise ValueError("Für diesen Auftrag kann der Export gerade nicht wiederholt werden.")
        from pathlib import Path

        source = Path(row[0])
        file = source.stat()
        expected = db.execute("SELECT size,modified,inode FROM fingerprints WHERE path=? AND key=?",
                              (str(source), key)).fetchone()
        if source.is_symlink() or not source.is_file() or expected != (file.st_size, file.st_mtime_ns, file.st_ino):
            raise ValueError("Die Originalaufnahme fehlt oder hat sich geändert.")
        db.execute("UPDATE recordings SET status='retry' WHERE key=?", (key,))
        record(db, key, "Export-Wiederholung angefordert")
