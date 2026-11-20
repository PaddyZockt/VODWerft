"""YouTube-Angaben pro Spielprofil: Playlist, feste Tags und Collab-Partner. Reine Logik, ohne Tk.

- Playlist: Der Upload-Dienst ordnet das Video nach dem Hochladen der Playlist zu (API: playlistItems.insert).
- Tags: feste Tags des Spiels; sie kommen zu den Tags, die das Sprachmodell vorschlägt (ohne Doppelte).
- Collab: Die YouTube-API kann keinen Collab-Partner setzen (nur YouTube Studio). Darum gibt es einen Hinweis
  "Collab einladen: <Kanal>" in der Detailansicht. Pro Profil steht, welcher Text im Dateinamen der Aufnahme
  zu welchem Kanal gehört (der Kanal heißt oft anders als die Gruppe).
"""
import re
from urllib.parse import parse_qs, urlparse

PLAYLIST = re.compile(r"[A-Za-z0-9_-]{10,64}")
MAX_TAG_CHARS = 450  # YouTube erlaubt 500 Zeichen für alle Tags zusammen; etwas Luft für Anführungszeichen


def playlist_id(text):
    """Playlist-Kennung aus einer Kennung oder einem Link (…?list=PL…), sonst None."""
    text = (text or "").strip()
    if not text:
        return None
    if "/" in text or "?" in text:
        try:
            text = (parse_qs(urlparse(text).query).get("list") or [""])[0]
        except ValueError:
            return None
    return text if PLAYLIST.fullmatch(text) else None


def parse_tags(text):
    """Tags aus Text mit Komma oder Zeilenumbruch getrennt; ohne Doppelte, ohne Leere."""
    return merge_tags([], re.split(r"[,\n]", text or ""), limit=None)


def merge_tags(first, second, *, limit=MAX_TAG_CHARS):
    """Zwei Tag-Listen zusammen, ohne Doppelte (Groß-/Kleinschreibung egal). `limit`: Höchstzahl an Zeichen
    für alle Tags zusammen; was nicht mehr hineinpasst, fällt weg (zuerst die hinteren)."""
    result, seen, used = [], set(), 0
    if isinstance(first, str):  # Text statt Liste (z. B. von der KI): an Kommas teilen, nie in Buchstaben zerlegen
        first = first.split(",")
    if isinstance(second, str):
        second = second.split(",")
    for tag in [*(first or []), *(second or [])]:
        tag = " ".join(str(tag).replace("<", "").replace(">", "").split())[:100]
        if not tag or tag.casefold() in seen:
            continue
        cost = len(tag) + (2 if " " in tag else 0) + 1
        if limit is not None and used + cost > limit:
            continue
        seen.add(tag.casefold())
        result.append(tag)
        used += cost
    return result


def parse_collab(text):
    """Einträge der Form "Suchtext = Kanalname", getrennt mit Semikolon oder Zeilenumbruch, als Liste von
    {"match", "channel"}."""
    entries = []
    for line in re.split(r"[;\n]", text or ""):
        match, separator, channel = line.partition("=")
        if separator and match.strip() and channel.strip():
            entries.append({"match": match.strip(), "channel": channel.strip()})
    return entries


def collab_text(entries):
    """Umkehrung von `parse_collab` für das Eingabefeld."""
    return "; ".join(f"{e['match']} = {e['channel']}" for e in entries or []
                     if isinstance(e, dict) and e.get("match") and e.get("channel"))


def collab_hints(entries, source_name):
    """Kanäle, die zu einer Aufnahme passen: Der Suchtext steht im Dateinamen (Groß-/Kleinschreibung egal)."""
    name = str(source_name).casefold()
    found = []
    for entry in entries or []:
        if (isinstance(entry, dict) and entry.get("match") and entry.get("channel")
                and str(entry["match"]).casefold() in name):
            if entry["channel"] not in found:
                found.append(entry["channel"])
    return found


# --- Kapitel nach einem abgeschnittenen Vorspann (Missionsbeginn) ------------------------------------

CHAPTER_LINE = re.compile(r"\d{1,2}:\d{2}(?::\d{2})?(?= )")
MIN_CHAPTER_GAP = 10.0   # YouTube: jedes Kapitel mindestens 10 Sekunden lang
MIN_CHAPTERS = 3         # und mindestens drei Kapitel, sonst zeigt YouTube keine an


def clock_seconds(text):
    """"M:SS" oder "H:MM:SS" in Sekunden, sonst None."""
    parts = str(text).strip().split(":")
    if not 2 <= len(parts) <= 3 or not all(p.isdigit() for p in parts):
        return None
    return float(sum(int(p) * 60 ** i for i, p in enumerate(reversed(parts))))


def clock_text(seconds):
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else f"{rest // 60}:{rest % 60:02d}"


def trim_offset(pieces, trim):
    """Wie viele Sekunden der Folge (Schnittzeitleiste) fallen weg, wenn alles vor `trim` Sekunden der Aufnahme
    abgeschnitten wird (Missionsbeginn; siehe export_episode.render). Gilt für eine Quelldatei."""
    return sum(min(max(trim - p["start"], 0.0), p["end"] - p["start"]) for p in pieces)


def shift_chapters(chapters, offset, length):
    """Kapitel ({"at": "M:SS", "title": …}) um `offset` Sekunden nach vorn schieben. Das Kapitel, das beim neuen
    Anfang läuft, wird zu 0:00; Kapitel dahinter müssen ≥10 s auseinanderliegen und vor `length` (neue Länge der
    Folge) beginnen. Unter drei Kapiteln bleibt nichts (YouTube würde sie nicht anzeigen)."""
    items = []
    for chapter in chapters or []:
        at = clock_seconds(chapter.get("at", ""))
        if at is not None:
            items.append((at - offset, str(chapter.get("title", "")).strip() or "Kapitel"))
    items.sort(key=lambda item: item[0])
    before = [item for item in items if item[0] <= 0]
    after = [item for item in items if item[0] > 0]
    if before and not (after and after[0][0] < MIN_CHAPTER_GAP):
        after.insert(0, (0.0, before[-1][1]))
    elif after:  # beginnt das nächste Kapitel gleich nach dem Anfang, wird es selbst zum 0:00-Kapitel
        after[0] = (0.0, after[0][1])
    result, last = [], None
    for at, title in after:
        if at >= length or (last is not None and at - last < MIN_CHAPTER_GAP):
            continue
        result.append({"at": clock_text(at), "title": title})
        last = at
    return result if len(result) >= MIN_CHAPTERS else []


def chapter_lines(description):
    """Kapitelzeilen ("0:00 Titel") aus einer Beschreibung: der zusammenhängende Block ab der Zeile "0:00 …".
    Eine Uhrzeit irgendwo im Text ("19:30 Uhr Training") zählt nicht als Kapitel."""
    lines = [line.strip() for line in str(description).splitlines()]
    for start, line in enumerate(lines):
        if re.match(r"0:00 ", line):
            block = []
            for entry in lines[start:]:
                if not CHAPTER_LINE.match(entry):
                    break
                block.append(entry)
            return block
    return []
