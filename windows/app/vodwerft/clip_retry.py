"""Queue a retry for a failed clip step without changing its recording or uploads."""
import sqlite3
from contextlib import closing


PENDING = ("retry", "retrying")


def request_retry(work, key):
    database = (work / "jobs.sqlite3").resolve().as_uri()
    with closing(sqlite3.connect(f"{database}?mode=rw", uri=True, timeout=2)) as db, db:
        return db.execute(
            "UPDATE clips SET status='retry' WHERE key=? AND status='review' "
            "AND EXISTS (SELECT 1 FROM recordings WHERE key=clips.key AND status='ready')",
            (key,),
        ).rowcount == 1
