"""Patch Notes ("Was ist neu") vor dem Update. Reine Logik, ohne Tk und ohne Netz.

Quelle (private Version): die Datei `docs/PATCH-NOTES.md` der neuen Version im Repository, mit je einem Abschnitt
pro Version:

    ## 1.5.0 · 20. November 2026
    - Erste Änderung
    - Zweite Änderung

Quelle (öffentliche Version): der Text des GitHub-Releases (siehe release_update.notes).
Angezeigt wird alles, was neuer ist als die installierte Version, neueste zuerst. Wer mehrere Versionen übersprungen
hat, sieht also alle dazwischen.
"""
import re

import version

HEADING = re.compile(r"^##\s+v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?)\b[ \t]*(.*)$", re.MULTILINE)
MAX_SECTIONS = 8      # nie eine endlose Liste zeigen
MAX_CHARS = 6000


def plain(text):
    """Der Update-Dialog zeigt reinen Text: Markdown-Zeichen (**fett**, `Code`, [Text](Link)) werden entfernt."""
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"\1 (\2)", str(text))
    return text.replace("**", "").replace("`", "")


def whats_new(body):
    """Aus einem GitHub-Release-Text nur die Liste "Neu in dieser Version" (deutsch, die Oberfläche ist deutsch), ohne
    Installer-Hinweis, Links und Prüfsumme. Hat der Text diese Gliederung nicht (ältere Releases), kommt er unverändert."""
    body = str(body or "")
    halves = body.split("\n## Deutsch", 1)
    part = halves[1] if len(halves) == 2 else body
    found = re.search(r"^###\s+(?:Neu in dieser Version|What's new)\s*$", part, re.MULTILINE)
    if not found:
        return body.strip()
    rest = part[found.end():]
    stop = re.search(r"^(?:###\s|Vollständiger Verlauf|Full history|Prüfsumme|Checksum|---)", rest, re.MULTILINE)
    return (rest[:stop.start()] if stop else rest).strip()


def key(text):
    """Sortierschlüssel nach SemVer (Vorabversionen sind kleiner als die fertige Version), sonst None."""
    parsed = version.parse(text)
    if not parsed:
        return None
    major, minor, patch, pre = parsed
    if pre is None:
        return (major, minor, patch, 1, ())
    return (major, minor, patch, 0, tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split(".")))


def sections(text):
    """Abschnitte einer Patch-Notes-Datei als Liste von (Version, Überschrift, Text)."""
    text = str(text or "")
    found = list(HEADING.finditer(text))
    result = []
    for index, match in enumerate(found):
        end = found[index + 1].start() if index + 1 < len(found) else len(text)
        body = text[match.end():end].strip()
        title = (match.group(1) + (" " + match.group(2).strip() if match.group(2).strip() else "")).strip()
        result.append((match.group(1), title, body))
    return result


def newer_than(text, installed, latest=None):
    """Text der Abschnitte, die neuer sind als `installed` (und nicht neuer als `latest`), neueste zuerst.
    Ist `installed` unbekannt, kommt nur der neueste Abschnitt. Leer, wenn es nichts zu zeigen gibt."""
    have = key(installed)
    top = key(latest) if latest else None
    items = [(key(v), title, body) for v, title, body in sections(text) if key(v)]
    items = [item for item in items if (have is None or item[0] > have) and (top is None or item[0] <= top)]
    items.sort(key=lambda item: item[0], reverse=True)
    if have is None:
        items = items[:1]
    parts = [f"{title}\n{body}".strip() for _, title, body in items[:MAX_SECTIONS]]
    result = plain("\n\n".join(part for part in parts if part))
    if len(items) > MAX_SECTIONS:
        result += f"\n\n… und {len(items) - MAX_SECTIONS} ältere Versionen."
    if len(result) > MAX_CHARS:
        result = result[:MAX_CHARS].rstrip() + " …"
    return result


def from_releases(items, installed, latest):
    """Patch Notes aus der Release-Liste von GitHub (öffentliche Version): Abschnitt je Release, dessen Text der
    Release-Beschreibung entspricht."""
    have = key(installed)
    top = key(latest) if latest else None
    chosen = []
    for item in items or []:
        tag = str(item.get("tag_name", "")).lstrip("v")
        tag_key = key(tag)
        if item.get("draft") or tag_key is None:
            continue
        if (have is None or tag_key > have) and (top is None or tag_key <= top):
            chosen.append((tag_key, tag, whats_new(item.get("body"))))
    chosen.sort(key=lambda entry: entry[0], reverse=True)
    if have is None:
        chosen = chosen[:1]
    parts = [f"{tag}\n{body}".strip() for _, tag, body in chosen[:MAX_SECTIONS] if body]
    result = plain("\n\n".join(parts))
    if len(result) > MAX_CHARS:
        result = result[:MAX_CHARS].rstrip() + " …"
    return result
