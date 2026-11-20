"""Plan prüfen aus Sicht des Watchers und des Dashboards (reine Logik ohne Tk).

Die eigentliche Plan-Logik steckt in `nightcut/plan_review.py`. Dieses Modul kennt nur die Dateinamen
im Arbeitsordner eines Auftrags und die Frage, ob die Option für ein Profil an ist.
"""
import json
import sys
from pathlib import Path

# Der Nightcut-Kern liegt neben diesem Ordner (im Repo wie in der Installation)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "nightcut" / "src"))
from nightcut import plan_review  # noqa: E402

# Exit-Code von Nightcut/run_letsplay, wenn der Lauf auf die Prüfung wartet (siehe plan_review.PENDING_EXIT_CODE)
PENDING_EXIT_CODE = 3
STATUS_WAITING = "awaiting_plan"  # Status des Auftrags in der Watcher-Datenbank
OPTION = "plan_pruefen"           # Schlüssel im Spielprofil und in settings.json


class PlanReviewPending(Exception):
    """Kein Fehler: Der Auftrag wartet darauf, dass der Plan geprüft und bestätigt wird."""


def work_folder(output):
    """Arbeitsordner von Nightcut innerhalb des Ausgabeordners eines Auftrags."""
    return Path(output) / "nightcut"


def review_enabled(profile, settings_values=None):
    """Spielprofil gewinnt; fehlt dort der Schlüssel, gilt der globale Standard (Vorgabe: aus)."""
    if OPTION in profile:
        return profile[OPTION] is True
    return bool((settings_values or {}).get(OPTION, False))


def is_confirmed(output):
    return (work_folder(output) / "plan_confirmed.json").is_file()


def read_state(output):
    """Inhalt von plan_review.json (Aufnahmen und Dauer) oder None, wenn nichts auf Prüfung wartet."""
    try:
        data = json.loads((work_folder(output) / "plan_review.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("status") == "waiting" else None


def final_cuts(output):
    """Der tatsächliche Schnittplan eines Auftrags: der automatische Plan (cuts.json), dazu deine Entfernungen
    aus "Plan prüfen", ohne die Bereiche, die du behalten willst. Gibt (cuts, info) zurück; cuts ist None, wenn es
    noch keinen Plan gibt. info = {"manual": Anzahl, "keep": Anzahl}.

    Die Detailansicht im Dashboard zeigt das. cuts.json allein ist nur der automatische Plan."""
    work = work_folder(output)
    try:
        cuts = json.loads((work / "cuts.json").read_text(encoding="utf-8"))
        if not isinstance(cuts, list):
            return None, {"manual": 0, "keep": 0}
    except (OSError, ValueError):
        return None, {"manual": 0, "keep": 0}
    files = read_state(output)
    durations = [f["duration"] for f in (files or {}).get("files", []) if isinstance(f, dict) and "duration" in f]
    if len(durations) != len(cuts):
        return cuts, {"manual": 0, "keep": 0}  # kein Prüfzustand: der Plan bleibt, wie er ist
    manual = plan_review.read_manual(work, len(cuts))
    keep = plan_review.read_keep(work, len(cuts))
    try:
        merged = plan_review.apply_manual(cuts, manual, durations, keep)
    except (KeyError, TypeError, ValueError):
        return cuts, {"manual": 0, "keep": 0}
    return merged, {"manual": sum(len(plan_review.clean_ranges(m, d)) for m, d in zip(manual, durations)),
                    "keep": sum(len(plan_review.clean_keeps(k, d)) for k, d in zip(keep, durations))}


def summary(output):
    """Kurzfassung des automatischen Plans eines wartenden Auftrags: {"removed_s", "ranges", "text"} oder None.

    Steht im Status (Tray, Statuskarte) und im Dashboard, damit man sieht, ob sich das Öffnen lohnt."""
    try:
        cuts = json.loads((work_folder(output) / "cuts.json").read_text(encoding="utf-8"))
        ranges = [r for f in cuts for r in f.get("removals", []) if r["end"] > r["start"]]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    seconds = sum(r["end"] - r["start"] for r in ranges)
    if not ranges:
        return {"removed_s": 0.0, "ranges": 0, "text": "nichts automatisch entfernt"}
    amount = f"{seconds / 60:.1f} min" if seconds >= 60 else f"{seconds:.0f} s"
    noun = "Bereich" if len(ranges) == 1 else "Bereiche"
    return {"removed_s": seconds, "ranges": len(ranges),
            "text": f"{amount} automatisch entfernt ({len(ranges)} {noun})".replace(".", ",")}


def can_resume(output):
    """Darf ein wartender Auftrag weiterlaufen? Erst nach Bestätigung."""
    return is_confirmed(output)
