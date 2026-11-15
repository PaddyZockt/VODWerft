"""Story moments: let a clip start at the setup, not only at the reaction.

A funny or exciting moment is often the *payoff* of something the player said or started
shortly before ("pass auf, das geht schief", "ich wette, der kommt gleich ..."). Without that
setup a viewer does not understand the reaction.

How it works (no extra AI call, everything is plain text matching, so it is fast and traceable):
- The game profile has a `story:` block. It is off by default and every game decides for itself.
- `triggers` are the phrases YOU choose. A trigger is a name plus a list of phrases that mark a setup.
- For every candidate clip we look into the transcript a few seconds *before* the clip
  (`lookback_s`). If a trigger phrase was said there, the clip starts at that sentence.
- The clip is never longer than `max_clip_s`; what was chosen is written to `story.json`.

Example for a profile (see profiles/story-example.yaml):

    story:
      enabled: true
      lookback_s: 45
      max_clip_s: 75
      triggers:
        - name: Ankündigung
          phrases: ["pass auf", "gleich passiert", "ich wette"]
"""

from __future__ import annotations

import re

DEFAULTS = {"enabled": False, "lookback_s": 45.0, "max_clip_s": 75.0, "triggers": []}


def settings(profile: dict | None) -> dict:
    """The story block of a profile with defaults; broken entries are ignored, never fatal."""
    block = (profile or {}).get("story")
    cfg = dict(DEFAULTS)
    if isinstance(block, dict):
        cfg.update({k: v for k, v in block.items() if k in DEFAULTS})
    cfg["enabled"] = bool(cfg["enabled"])
    for key in ("lookback_s", "max_clip_s"):
        try:
            cfg[key] = max(0.0, float(cfg[key]))
        except (TypeError, ValueError):
            cfg[key] = DEFAULTS[key]
    triggers = []
    for t in cfg["triggers"] or []:
        if not isinstance(t, dict):
            continue
        phrases = [str(p).strip().lower() for p in (t.get("phrases") or []) if str(p).strip()]
        if phrases:
            triggers.append({"name": str(t.get("name") or phrases[0]), "phrases": phrases})
    cfg["triggers"] = triggers
    return cfg


def _compile(triggers: list[dict]) -> list[tuple[str, re.Pattern]]:
    return [(t["name"], re.compile(r"(?<!\w)" + re.escape(p) + r"(?!\w)")) for t in triggers for p in t["phrases"]]


def extend(candidates: list[dict], segments: list[dict], profile: dict | None) -> tuple[list[dict], list[dict]]:
    """Move clip starts back to the earliest trigger sentence inside the lookback window.

    Returns (candidates, notes). Candidates are changed in place; a changed one gets a `story`
    entry. Does nothing when the profile has no enabled story block or no triggers.
    """
    cfg = settings(profile)
    if not cfg["enabled"] or not cfg["triggers"]:
        return candidates, []
    patterns = _compile(cfg["triggers"])
    notes = []
    for c in candidates:
        earliest = None
        for seg in segments:
            if seg["end"] > c["start"] or seg["start"] < c["start"] - cfg["lookback_s"]:
                continue
            text = seg["text"].lower()
            hit = next((name for name, pat in patterns if pat.search(text)), None)
            if hit and (earliest is None or seg["start"] < earliest[0]["start"]):
                earliest = (seg, hit)
        if not earliest:
            continue
        seg, name = earliest
        new_start = max(seg["start"] - 0.3, 0.0)
        # never longer than max_clip_s: the end stays, the start is only moved as far as allowed
        new_start = max(new_start, c["end"] - cfg["max_clip_s"])
        if new_start >= c["start"] - 0.5:
            continue
        note = {"id": c.get("id"), "trigger": name, "setup": seg["text"].strip()[:160],
                "old_start": round(c["start"], 1), "new_start": round(new_start, 1)}
        c["start"] = new_start
        c["story"] = {"trigger": name, "setup": note["setup"], "max_len": cfg["max_clip_s"]}
        notes.append(note)
    return candidates, notes
