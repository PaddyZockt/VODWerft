"""Restzeit pro Schritt: schätzt aus dem Fortschritt ("35 von 100", "41 %"), wie lange ein Schritt noch dauert.

Es gibt keine Vorhersage aus Erfahrungswerten, sondern nur eine Rechnung aus dem, was man sieht: Wie schnell ist
der Zähler seit der ersten Beobachtung gewachsen? Daraus folgt, wie lange der Rest braucht. Die Schätzung erscheint
erst, wenn genug Zeit vergangen und der Zähler wirklich gewachsen ist; sonst zeigt man lieber nichts als Unsinn.
Reine Logik ohne Tk, getestet in tests/test_eta.py.
"""
import re

MIN_SECONDS = 45          # so lange muss ein Schritt beobachtet worden sein
MAX_SECONDS = 48 * 3600   # Schätzungen über zwei Tage sind Unsinn (z. B. Zähler fast stehengeblieben)
COUNTER = re.compile(r"^(?P<step>.+?) \((?P<done>\d+) von (?P<total>\d+)\)$")
RENDER = re.compile(r"^(?:Korrektur · )?(?P<step>Rendern) · .* · (?P<done>\d+) % · ")


def progress_of(detail):
    """(Schritt, erledigt, gesamt) aus einem Statustext oder None.

    Zwei Schreibweisen: "Bild und Ton werden analysiert (35 von 100)" und die Renderanzeige des Dashboards
    "Rendern · Abschnitt 2 von 5 · 41 % · ...". "Folge 4 wird gerendert (1 von 1)" zählt Folgen, nicht Fortschritt:
    dort kommt der Prozentwert aus der Renderdatei (siehe `Estimator.update`)."""
    found = RENDER.match(detail or "")
    if found:
        return found["step"], int(found["done"]), 100
    found = COUNTER.match(detail or "")
    if found and not found["step"].startswith("Folge "):
        done, total = int(found["done"]), int(found["total"])
        if total > 0 and done <= total:
            return found["step"], done, total
    return None


def format_seconds(seconds):
    """Kurzer Text für die Restzeit, grob gerundet: "weniger als 1 Min.", "etwa 12 Min.", "etwa 1 Std. 20 Min."."""
    minutes = seconds / 60
    if minutes < 1:
        return "weniger als 1 Min."
    if minutes >= 10:
        minutes = int(minutes / 5 + 0.5) * 5  # bei längeren Zeiten wäre jede Minute vorgetäuschte Genauigkeit
    else:
        minutes = int(minutes + 0.5)  # kaufmännisch runden (round() rundet 2,5 auf 2)
    hours, rest = divmod(int(minutes), 60)
    if hours:
        return f"etwa {hours} Std. {rest} Min." if rest else f"etwa {hours} Std."
    return f"etwa {rest} Min."


class Estimator:
    """Merkt sich pro Auftrag, seit wann ein Schritt beobachtet wird, und schätzt die Restzeit."""

    def __init__(self):
        self.runs = {}

    def forget(self, key):
        self.runs.pop(key, None)

    def update(self, key, step, done, total, now):
        """Neue Beobachtung. Gibt die geschätzten Restsekunden zurück oder None, wenn es noch nichts Verlässliches gibt.

        `now` ist eine laufende Zeit in Sekunden (time.monotonic()). Beginnt ein neuer Schritt oder geht der Zähler
        zurück (Neustart des Schritts), fängt die Beobachtung von vorn an."""
        if total <= 0 or done > total:
            return None
        run = self.runs.get(key)
        if run is None or run["step"] != step or done < run["last"]:
            run = self.runs[key] = {"step": step, "start": now, "from": done, "last": done}
        run["last"] = done
        elapsed, gained = now - run["start"], done - run["from"]
        if elapsed < MIN_SECONDS or gained <= 0:
            return None
        remaining = (total - done) * elapsed / gained
        return remaining if remaining <= MAX_SECONDS else None

    def text(self, key, detail, now, percent=None):
        """Fertiger Text ("etwa 12 Min.") für einen Statustext oder None.

        `percent` (0-100) ist der Renderfortschritt einer Folge aus der Renderdatei; er hat Vorrang vor dem Zähler im Text."""
        if percent is not None and detail.startswith("Folge ") and " wird gerendert" in detail:
            found = ("Rendern", percent, 100)
        else:
            found = progress_of(detail)
        if not found:
            self.forget(key)
            return None
        seconds = self.update(key, *found, now)
        return format_seconds(seconds) if seconds is not None else None
