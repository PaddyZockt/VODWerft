"""Windows-Benachrichtigung, wenn ein Auftrag auf dich wartet oder fertig ist. Ohne Tk, die Anzeige übernimmt `toast.py`.

`Tracker.changes(rows)` bekommt bei jeder Aktualisierung die Aufträge des Dashboards und meldet nur, was sich seit
dem letzten Mal geändert hat:

- ein Auftrag wechselt nach „Wartet auf dich“ (Plan prüfen, Missionsbeginn, Freigabe, Fehler zum Prüfen)
- ein Auftrag, der gerade noch in Arbeit war, ist jetzt fertig

Der erste Aufruf (Start des Dashboards) meldet nichts: Alte Aufträge sollen keine Flut an Meldungen auslösen.
Mehr als drei Meldungen auf einmal werden zu einer zusammengefasst.
"""
from dataclasses import dataclass

MAX_SINGLE = 3


@dataclass(frozen=True)
class Message:
    key: str
    kind: str      # "todo" | "done" | "summary"
    title: str
    text: str


class Tracker:
    def __init__(self):
        self.seen = None   # Auftrag -> Gruppe beim letzten Mal; None = noch nie aufgerufen

    def changes(self, rows):
        current = {row.key: row for row in rows}
        if self.seen is None:
            self.seen = {key: row.bucket for key, row in current.items()}
            return []
        found = []
        for key, row in current.items():
            before, now = self.seen.get(key), row.bucket
            if before == now:
                continue
            if now == "todo":
                found.append(Message(key, "todo", f"{row.series}: wartet auf dich", f"{row.name}\n{row.detail}"))
            elif now == "done" and before == "work":
                found.append(Message(key, "done", f"{row.series}: fertig", row.name))
        self.seen = {key: row.bucket for key, row in current.items()}
        if len(found) > MAX_SINGLE:
            todo = sum(1 for m in found if m.kind == "todo")
            return [Message("", "summary", "VODWerft",
                            f"{todo} Aufträge warten auf dich, {len(found) - todo} sind fertig.")]
        return found
