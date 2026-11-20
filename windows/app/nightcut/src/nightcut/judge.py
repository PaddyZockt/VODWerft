"""Clip judge: choose Shorts by story and fun, not only by loudness.

Until now the Shorts were simply the three highest-scoring clips (mic/game level, keywords, picture
check). Nothing asked: is it funny, does it have a payoff, does a viewer understand it without the
rest of the video?

How it works:
- The strongest candidates (by score) are judged one by one by the local text model (Ollama), using
  the spoken text of the clip and what the picture check saw.
- The model answers with three ratings (entertaining, complete story, understandable), a verdict
  and a one-sentence reason. Your criteria are plain text in the config, per game if you like.
- The final rating mixes the three ratings (weights are configurable) with a little of the old score.
- The Shorts are the best-rated clips, never two from the same minute. Clips the judge rejects ("no") are
  not used at all (config: allow_rejected): better two good Shorts than three with a weak one.
- If the model fails, the old score-based pick is used. Nothing is lost.

Everything except the model call is plain Python and tested (tests/test_nightcut_judge.py).
"""

from __future__ import annotations

import hashlib
import json

from . import llm

PROMPT_VERSION = 2   # bump when the prompt changes: cached judgements are made again

DEFAULT_CRITERIA = (
    "A good Short can be understood on its own: someone who has not seen the video gets it. "
    "It has a setup and a payoff (a joke, a success, a fail, a surprise, a funny reaction) and it "
    "ends right after the payoff or the reaction. It is funny, exciting or impressive. "
    "Reject: microphone or audio checks, greetings and goodbyes, chat with nothing happening, "
    "technical trouble, long silences, calm explanations without a punchline, plans that are only "
    "announced and never happen."
)

DEFAULTS = {
    "enabled": True,
    "model": None,              # default: the editor model
    "max_candidates": 40,       # only the strongest candidates are judged (each is one model call)
    "criteria": None,           # free text; default above. The game profile may set its own (judge.criteria)
    "weights": {"entertaining": 0.45, "complete": 0.35, "understandable": 0.20},
    "signal_weight": 0.15,      # share of the old audio/picture score in the final rating (0..1)
    "reject_penalty": 0.5,      # verdict "no": rating times this factor, so rejects come last
    "allow_rejected": False,    # false: a clip the judge rejects is never a Short, even if fewer than `count` remain
    "min_gap_s": 60,            # two Shorts never start within this many seconds of each other
    "max_text_chars": 900,      # spoken text sent per clip
}

SYSTEM = """You judge short clips of a German gaming YouTube channel for vertical Shorts (TikTok/Instagram).
You get the spoken text of ONE clip (the player talking, German) and what a picture check saw.
Be strict. Most clips are ordinary: the typical clip rates 3 to 5. Only about one in ten deserves 8 or more.
Judge by these criteria:
{criteria}

Work in this order:
1. "setup": what is set up or announced (max 12 words), or "none".
2. "payoff": the joke, success, fail, surprise or strong reaction that follows (max 12 words), or "none".
   Talking, explaining, planning or building without an event is NOT a payoff.
3. Rate each from 0 to 10:
   - entertaining: funny, exciting or impressive for someone who does not know the game
   - complete: setup AND payoff are both in the clip and it ends cleanly (not mid-sentence, not before the punchline)
   - understandable: makes sense without any context from earlier in the video
4. Verdict: "yes" = post it (needs a real payoff and entertaining of 7 or more), "maybe" = ok but not great,
   "no" = do not use.
Only state what the text and picture really show. A wish or plan of the player is not an event.
Answer only with JSON:
{{"setup": str, "payoff": str, "entertaining": int, "complete": int, "understandable": int,
  "verdict": "yes"|"maybe"|"no", "reason": "one short German sentence", "title": "German title, max 5 words"}}"""


def settings(cfg: dict) -> dict:
    """The judge settings: defaults, then the config (shorts.judge), then the game profile (judge)."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    block = (cfg.get("shorts") or {}).get("judge")
    if isinstance(block, dict):
        for key, value in block.items():
            if key in out:
                out[key] = {**out[key], **value} if isinstance(out[key], dict) and isinstance(value, dict) else value
    profile = (cfg.get("profile") or {}).get("judge")
    # An explicit criteria text in the config wins (VODWerft puts the text you set in the profile editor there);
    # otherwise the game profile's text; otherwise the built-in default.
    if (isinstance(profile, dict) and str(profile.get("criteria") or "").strip()
            and not str(out["criteria"] or "").strip()):
        out["criteria"] = str(profile["criteria"]).strip()
    out["enabled"] = bool(out["enabled"])
    out["criteria"] = str(out["criteria"] or DEFAULT_CRITERIA).strip()
    for key, low, high in (("signal_weight", 0.0, 1.0), ("reject_penalty", 0.0, 1.0)):
        try:
            out[key] = min(high, max(low, float(out[key])))
        except (TypeError, ValueError):
            out[key] = DEFAULTS[key]
    for key in ("max_candidates", "min_gap_s", "max_text_chars"):
        try:
            out[key] = max(1 if key != "min_gap_s" else 0, int(out[key]))
        except (TypeError, ValueError):
            out[key] = DEFAULTS[key]
    return out


def window_text(segments: list[dict], start: float, end: float, limit: int) -> str:
    """The spoken text between start and end, in order, shortened to `limit` characters."""
    parts = [s["text"].strip() for s in segments if s["end"] > start and s["start"] < end and s["text"].strip()]
    text = " ".join(parts)
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " ..."


def build_prompt(candidate: dict, text: str, criteria: str) -> tuple[str, str]:
    vision = candidate.get("vision") or {}
    info = {
        "length_s": round(candidate["end"] - candidate["start"]),
        "spoken_text": text or "(nobody speaks)",
        "picture_check": {"event": vision.get("event"), "what_happens": str(vision.get("summary", ""))[:200]},
    }
    return SYSTEM.format(criteria=criteria), json.dumps(info, ensure_ascii=False)


def _score(value) -> float | None:
    try:
        return min(10.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return None


NOTHING = {"", "none", "nothing", "n/a", "-", "keine", "kein", "keiner", "keines", "nichts", "null"}


def _text(value) -> str:
    return "" if value is None else str(value).strip()[:160]


def parse_verdict(answer) -> dict | None:
    """A usable verdict from the model's answer, or None. Ratings are clamped to 0..10.

    Without a payoff the clip cannot be complete or a "yes": the model tends to be generous, so this is
    enforced here (complete at most 3, verdict at most "maybe")."""
    if not isinstance(answer, dict):
        return None
    ratings = {k: _score(answer.get(k)) for k in ("entertaining", "complete", "understandable")}
    if any(v is None for v in ratings.values()):
        return None
    setup, payoff = _text(answer.get("setup")), _text(answer.get("payoff"))
    has_payoff = payoff.lower().strip(" .") not in NOTHING
    if "payoff" in answer and not has_payoff:
        ratings["complete"] = min(ratings["complete"], 3.0)
    verdict = str(answer.get("verdict", "")).strip().lower()
    mean = sum(ratings.values()) / 3
    if verdict not in ("yes", "maybe", "no"):
        verdict = "yes" if mean >= 7 else "maybe" if mean >= 4 else "no"
    if "payoff" in answer and not has_payoff and verdict == "yes":
        verdict = "maybe"
    return {**ratings, "verdict": verdict, "setup": setup, "payoff": payoff if has_payoff else "",
            "reason": _text(answer.get("reason"))[:200], "title": _text(answer.get("title"))[:60]}


def rating(verdict: dict, jcfg: dict) -> float:
    """0..1 from the three ratings (weights from the config, normalised)."""
    weights = jcfg["weights"]
    total = sum(max(0.0, float(weights.get(k, 0))) for k in ("entertaining", "complete", "understandable")) or 1.0
    value = sum(max(0.0, float(weights.get(k, 0))) * verdict[k] for k in ("entertaining", "complete", "understandable"))
    return value / total / 10.0


def final_rating(verdict: dict, signal: float, jcfg: dict) -> float:
    """Judge rating mixed with the normalised old score (0..1); a rejected clip is pushed down."""
    base = (1 - jcfg["signal_weight"]) * rating(verdict, jcfg) + jcfg["signal_weight"] * signal
    return base * jcfg["reject_penalty"] if verdict["verdict"] == "no" else base


def signature(cfg: dict, candidates: list[dict]) -> str:
    """Changes when the criteria, model, settings or the judged candidates change: the cached judgement is stale."""
    jcfg = settings(cfg)
    pool = _pool(candidates, jcfg)
    material = json.dumps({"v": PROMPT_VERSION, "j": jcfg, "model": _model(cfg, jcfg),
                           "c": [(c["id"], round(c["start"], 1), round(c["end"], 1)) for c in pool]}, sort_keys=True)
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]


def _model(cfg: dict, jcfg: dict) -> str:
    return jcfg["model"] or (cfg.get("editor") or {}).get("model") or "qwen3:14b"


def _pool(candidates: list[dict], jcfg: dict) -> list[dict]:
    """The strongest candidates by score, in time order."""
    best = sorted(candidates, key=lambda c: c.get("final_score", c.get("score", 0)), reverse=True)
    return sorted(best[:jcfg["max_candidates"]], key=lambda c: c["start"])


def run(candidates: list[dict], segments: list[dict], cfg: dict, *, chat=None, progress=None) -> dict:
    """Judge the strongest candidates. `chat` (default: llm.chat_json) is replaceable for tests.

    Returns {"signature", "model", "items": [...], "failed": n}. Each item: id, start, end, signal (0..1),
    verdict fields, "final". Only Ollama setup problems are raised; a single bad answer just skips that clip.
    """
    jcfg = settings(cfg)
    chat = chat or llm.chat_json
    model = _model(cfg, jcfg)
    pool = _pool(candidates, jcfg)
    top = max((c.get("final_score", c.get("score", 0)) for c in pool), default=0) or 1.0
    items, failed = [], 0
    try:
        for n, c in enumerate(pool, 1):
            system, user = build_prompt(c, window_text(segments, c["start"], c["end"], jcfg["max_text_chars"]),
                                        jcfg["criteria"])
            try:
                answer = chat(cfg["ollama"], model, system, user, temperature=0.2, keep_loaded=True, max_tokens=300)
            except llm.OllamaError:
                raise  # Ollama down or model missing: tell the user, as the editor does
            except Exception:  # timeout or bad answer: this clip stays unjudged
                failed += 1
                answer = None
            verdict = parse_verdict(answer)
            if verdict is None:
                failed += answer is not None
                if progress:
                    progress(n, len(pool))
                continue
            signal = max(0.0, min(1.0, c.get("final_score", c.get("score", 0)) / top))
            items.append({"id": c["id"], "start": c["start"], "end": c["end"], "signal": round(signal, 3),
                          **verdict, "rating": round(rating(verdict, jcfg), 3),
                          "final": round(final_rating(verdict, signal, jcfg), 3)})
            if progress:
                progress(n, len(pool))
    finally:
        try:
            llm.unload(cfg["ollama"], model)
        except Exception:
            pass
    return {"signature": signature(cfg, candidates), "model": model, "items": items, "failed": failed}


def pick(result: dict | None, candidates: list[dict], count: int, min_s: float, jcfg: dict) -> list[dict] | None:
    """The Shorts: best final rating first, not two within min_gap_s, rejected clips not at all (allow_rejected).

    Returns clip dicts (the candidate plus the judge's title, reason and rating); the list may be shorter than
    `count` or empty when nothing is good enough. Returns None when there is no usable judgement at all: the
    caller then falls back to the score-based pick."""
    if not result or not result.get("items"):
        return None
    by_id = {c["id"]: c for c in candidates}
    chosen = []
    for item in sorted(result["items"], key=lambda i: i["final"], reverse=True):
        c = by_id.get(item["id"])
        if not c or c["end"] - c["start"] < min_s:
            continue
        if item["verdict"] == "no" and not jcfg.get("allow_rejected"):
            continue
        if any(abs(c["start"] - o["start"]) < jcfg["min_gap_s"] for o in chosen):
            continue
        chosen.append({**c, "title": item["title"] or c.get("title", ""), "reason": item["reason"],
                       "judge": {k: item[k] for k in ("entertaining", "complete", "understandable", "verdict",
                                                      "rating", "final")} | {"payoff": item.get("payoff", "")}})
        if len(chosen) >= count:
            break
    return chosen


def report(result: dict, candidates: list[dict], chosen: list[dict]) -> str:
    """A readable list (judge.md): every judged clip with its verdict, so you can see why a Short was chosen."""
    by_id = {c["id"]: c for c in candidates}
    picked = {c["id"] for c in chosen}
    lines = ["# Clip judge", "", f"Model: {result.get('model')} · judged: {len(result['items'])} · "
             f"unusable answers: {result.get('failed', 0)}", "",
             "| | Time | Final | Fun | Story | Clear | Verdict | Title | Payoff | Reason |", "|---|---|---|---|---|---|---|---|---|---|"]
    for item in sorted(result["items"], key=lambda i: i["final"], reverse=True):
        at = item["start"]
        mark = "✔" if item["id"] in picked else ""
        title = item["title"] or by_id.get(item["id"], {}).get("title", "")
        lines.append(f"| {mark} | {int(at // 60)}:{int(at % 60):02d} | {item['final']:.2f} | {item['entertaining']:.0f} | "
                     f"{item['complete']:.0f} | {item['understandable']:.0f} | {item['verdict']} | {title} | "
                     f"{item.get('payoff', '')} | {item['reason']} |")
    return "\n".join(lines) + "\n"
