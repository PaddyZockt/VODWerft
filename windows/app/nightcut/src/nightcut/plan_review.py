"""Plan prüfen: Bereiche von Hand aus dem Schnittplan entfernen.

Ablauf: Nightcut analysiert und schreibt den automatischen Plan (cuts.json). Ist die Option an,
hält die Pipeline danach an. Der Nutzer markiert Bereiche (manual_cuts.json) und bestätigt
(plan_confirmed.json). Beim nächsten Lauf wird der Plan mit den Markierungen zusammengeführt;
Folgenaufteilung, Export und Metadaten werden dann neu berechnet.

Alles hier ist reine Logik ohne Oberfläche und ohne ffmpeg, damit sie testbar ist.
"""
from __future__ import annotations

import json
from pathlib import Path


# Exit-Code, mit dem der Lauf anhält. Kein Fehler: Aufrufer (run_letsplay) erkennt daran "Plan prüfen".
PENDING_EXIT_CODE = 3

def merge(removals: list[dict]) -> list[dict]:
    """Überlappende Entfernungen verschmelzen (gleiche Regeln wie segments.merge, aber ohne numpy,
    damit dieses Modul und seine Tests überall laufen)."""
    out: list[dict] = []
    for r in sorted(removals, key=lambda r: r["start"]):
        if out and r["start"] <= out[-1]["end"]:
            out[-1]["end"] = max(out[-1]["end"], r["end"])
            if r["label"] not in out[-1]["label"].split("+"):
                out[-1]["label"] += "+" + r["label"]
        else:
            out.append(dict(r))
    return out


def kept_pieces(duration: float, removals: list[dict]) -> list[tuple[float, float]]:
    """Alles, was nicht entfernt ist (wie segments.kept_pieces)."""
    pieces, cur = [], 0.0
    for r in removals:
        if r["start"] > cur:
            pieces.append((round(cur, 2), r["start"]))
        cur = max(cur, r["end"])
    if duration > cur:
        pieces.append((round(cur, 2), round(duration, 2)))
    return pieces


LABEL = "manual"  # Label, das es für Handentfernungen schon gibt
SUMMARY = "Von Hand entfernt"


def manual_path(work) -> Path:
    return Path(work) / "manual_cuts.json"


def confirmed_path(work) -> Path:
    return Path(work) / "plan_confirmed.json"


def applied_path(work) -> Path:
    return Path(work) / "manual_applied.json"


def review_path(work) -> Path:
    return Path(work) / "plan_review.json"


def clean_ranges(ranges, duration: float) -> list[dict]:
    """Markierungen bereinigen: auf die Aufnahme begrenzen, Leeres verwerfen, sortieren, zusammenfassen."""
    out = []
    for r in ranges or []:
        try:
            a, b = float(r["start"]), float(r["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if a != a or b != b:  # NaN
            continue
        a, b = max(0.0, min(a, b)), min(float(duration), max(a, b))  # Reihenfolge egal: 1:34 vor 1:21 ist okay
        if b - a > 0.01:
            out.append({"start": round(a, 2), "end": round(b, 2), "label": LABEL, "summary": SUMMARY})
    return merge(out)


def subtract(removals: list[dict], keeps: list[dict]) -> list[dict]:
    """Entfernungen ohne die Bereiche, die der Nutzer behalten will. Eine Entfernung kann dabei in zwei Teile
    zerfallen (Stück aus der Mitte behalten); Reste unter 0,05 s fallen weg."""
    out = []
    for r in removals:
        pieces = [(r["start"], r["end"])]
        for k in keeps:
            nxt = []
            for a, b in pieces:
                if k["end"] <= a or k["start"] >= b:
                    nxt.append((a, b))
                    continue
                if k["start"] > a:
                    nxt.append((a, k["start"]))
                if k["end"] < b:
                    nxt.append((k["end"], b))
            pieces = nxt
        out += [{**r, "start": round(a, 2), "end": round(b, 2)} for a, b in pieces if b - a > 0.05]
    return out


def clean_keeps(ranges, duration: float) -> list[dict]:
    """Bereiche, die behalten werden sollen: gleiche Bereinigung wie bei Entfernungen, nur ohne Label."""
    return [{"start": r["start"], "end": r["end"]} for r in clean_ranges(ranges, duration)]


def apply_manual(cuts: list[dict], manual: list[list[dict]], durations: list[float],
                 keep: list[list[dict]] | None = None) -> list[dict]:
    """Automatischen Plan (pro Aufnahme {stretches, removals, kept}) anpassen.

    manual: zusätzlich entfernen. keep: trotz automatischer Entfernung behalten (gilt nur für den automatischen
    Plan; was du ausdrücklich entfernst, bleibt entfernt). `kept` wird neu berechnet, nicht nur `removals`
    angepasst. Ohne Markierungen kommt der Plan unverändert zurück.
    """
    keep = keep or []
    if not any(manual) and not any(keep):
        return cuts
    result = []
    for n, f in enumerate(cuts):
        extra = clean_ranges(manual[n] if n < len(manual) else [], durations[n])
        kept_ranges = clean_keeps(keep[n] if n < len(keep) else [], durations[n])
        if not extra and not kept_ranges:
            result.append(f)
            continue
        automatic = subtract([dict(r) for r in f["removals"]], kept_ranges)
        removals = merge(automatic + extra)
        result.append({**f, "removals": removals, "kept": [list(k) for k in kept_pieces(durations[n], removals)]})
    return result


def signature(manual: list[list[dict]], durations: list[float], keep: list[list[dict]] | None = None) -> str:
    """Stabiler Fingerabdruck der bereinigten Markierungen, um Änderungen zu erkennen."""
    def cleaned(items, fn):
        return [[(r["start"], r["end"]) for r in fn(items[n] if n < len(items) else [], d)]
                for n, d in enumerate(durations)]
    removed = cleaned(manual, clean_ranges)
    kept = cleaned(keep or [], clean_keeps)
    # ohne Behalten-Bereiche bleibt der Fingerabdruck wie früher (bereits bestätigte Pläne ändern sich nicht)
    return json.dumps(removed if not any(kept) else {"remove": removed, "keep": kept})


def read_manual(work, files: int) -> list[list[dict]]:
    """Markierungen lesen; immer eine Liste pro Aufnahme. Fehlende oder kaputte Datei = keine Markierungen."""
    try:
        data = json.loads(manual_path(work).read_text(encoding="utf-8"))["files"]
        out = [list(x) if isinstance(x, list) else [] for x in data]
    except (OSError, ValueError, KeyError, TypeError):
        out = []
    return (out + [[] for _ in range(files)])[:files]


def read_keep(work, files: int) -> list[list[dict]]:
    """Bereiche, die der Nutzer trotz automatischer Entfernung behalten will; immer eine Liste pro Aufnahme."""
    try:
        data = json.loads(manual_path(work).read_text(encoding="utf-8"))["keep"]
        out = [list(x) if isinstance(x, list) else [] for x in data]
    except (OSError, ValueError, KeyError, TypeError):
        out = []
    return (out + [[] for _ in range(files)])[:files]


def write_manual(work, manual: list[list[dict]], keep: list[list[dict]] | None = None) -> None:
    data = {"files": manual}
    if keep is not None and any(keep):
        data["keep"] = keep
    manual_path(work).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def is_confirmed(work) -> bool:
    return confirmed_path(work).is_file()


def confirm(work) -> None:
    """Der Nutzer hat den Plan bestätigt: die Pipeline darf weiterlaufen."""
    confirmed_path(work).write_text(json.dumps({"confirmed": True}), encoding="utf-8")


def write_review_state(work, files: list[dict]) -> None:
    """Merkt, dass der Auftrag auf Prüfung wartet (für Dashboard und Prüffenster)."""
    review_path(work).write_text(json.dumps({"status": "waiting", "files": files}, ensure_ascii=False, indent=2),
                                 encoding="utf-8")


def needs_review(cfg: dict, work) -> bool:
    """Soll hier angehalten werden? Nur wenn die Option an ist und noch nicht bestätigt wurde."""
    return bool(cfg.get("letsplay", {}).get("review_plan")) and not is_confirmed(work)
