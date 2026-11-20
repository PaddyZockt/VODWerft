"""Übergänge an Schnitten: Filter für ffmpeg, die ein Teil einer Folge am Anfang und am Ende bekommt.

Eine Folge besteht aus Teilen, die einzeln gerendert und dann hart aneinandergehängt werden (siehe
`export_episode.render`). Ein Übergang ist hier ein Effekt am Ende des einen und am Anfang des nächsten
Teils (Abblenden, Weichzeichnen, ...). Es gibt keine Überlappung: Jeder Teil bleibt genau so lang wie im
Plan. Dadurch ändern sich Länge, Kapitelzeiten und Metadaten einer Folge nie.

Der Anfang der Folge und ihr Ende bekommen keinen Übergang, nur die Stellen dazwischen.

Reine Logik ohne ffmpeg-Aufruf und ohne Tk; getestet in tests/test_transitions.py.
"""

HART = "hart"
KINDS = (HART, "abblende", "weichzeichner", "weissblitz", "zoom", "pixel")

# Anzeigetexte (Dashboard, Einstellungen, Profil-Editor)
LABELS = {
    "hart": "Hart (kein Übergang)",
    "abblende": "Abblende (schwarz)",
    "weichzeichner": "Weichzeichner",
    "weissblitz": "Weißblitz",
    "zoom": "Zoom",
    "pixel": "Pixel",
}

# Dauer des Effekts am Ende bzw. am Anfang eines Teils (Sekunden)
SECONDS = {"abblende": 0.4, "weichzeichner": 0.8, "weissblitz": 0.25, "zoom": 0.6, "pixel": 0.6}
AUDIO_SECONDS = 0.3   # so lange blendet der Ton höchstens aus bzw. ein (kürzer bei kürzeren Effekten)
MIN_PIECE = 1.5       # Teile unter dieser Länge bekommen keinen Übergang (sonst wäre fast nur Effekt zu sehen)


def valid(kind):
    return kind in KINDS


def effective(profile, settings_values=None):
    """Welcher Übergang gilt? Das Spielprofil gewinnt; fehlt dort der Schlüssel, gilt die globale Einstellung,
    sonst "hart". Unbekannte Werte werden zu "hart" (nie ein Fehler beim Rendern)."""
    value = profile.get("uebergang") if "uebergang" in profile else (settings_values or {}).get("uebergang")
    return value if valid(value) else HART


def _seconds(kind, length):
    """Dauer des Effekts, nie mehr als ein Drittel des Teils (am Anfang und am Ende sollen zusammen höchstens
    zwei Drittel verbraucht werden)."""
    return min(SECONDS[kind], length / 3)


def _ramp_out(duration, length, time="t"):
    """Ausdruck 0..1, der in den letzten `duration` Sekunden eines Teils von 0 auf 1 steigt.
    `time` ist der Name der Zeitvariable (bei zoompan `it`, sonst `t`)."""
    return f"clip(({time}-{length - duration:.3f})/{duration:.3f},0,1)"


def _ramp_in(duration, time="t"):
    """Ausdruck 1..0, der in den ersten `duration` Sekunden eines Teils von 1 auf 0 fällt."""
    return f"(1-clip({time}/{duration:.3f},0,1))"


def _scaled(ramp, size, floor, flags):
    """Bild verkleinern (je nach Rampe bis auf `floor` Pixel Breite) und wieder auf Originalgröße bringen.
    Mit weichem Hochskalieren entsteht ein Weichzeichner, mit `neighbor` Pixelblöcke."""
    width, height = size
    return (f",scale=w='max({floor},{width}*(1-{1 - floor / width:.4f}*{ramp}))':h=-2:eval=frame:flags=bilinear,"
            f"scale={width}:{height}:flags={flags},setsar=1,format=yuv420p")


def _zoomed(ramp, size):
    """Bild bis auf das 1,4-fache vergrößern (Mitte bleibt) bei gleicher Ausgabegröße.

    Mit zoompan statt scale+crop: crop rechnet nach einem scale mit eval=frame mit der Startgröße und schnitt
    den Ausschnitt in der linken oberen Ecke statt in der Mitte aus (vom Prüfer belegt). `fps=60` davor sorgt
    dafür, dass zoompan (ein Ausgabebild je Eingangsbild) die Länge des Teils nie verändert."""
    width, height = size
    return (f",fps=60,zoompan=z='1+0.4*{ramp}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={width}x{height}:fps=60,"
            f"setsar=1,format=yuv420p")


def video_filter(kind, edge, length, size):
    """ffmpeg-Filterkette (mit führendem Komma) für ein Teil.

    kind: Übergang. edge: "out" (Ende des Teils) oder "in" (Anfang). length: Länge des Teils in Sekunden.
    size: (Breite, Höhe) des Ausgabebilds. Für "hart" und zu kurze Teile: leer.
    """
    if kind == HART or kind not in SECONDS or length < MIN_PIECE or edge not in ("out", "in"):
        return ""
    d = _seconds(kind, length)
    time = "it" if kind == "zoom" else "t"  # zoompan kennt `it` (Eingangszeit) statt `t`
    ramp = _ramp_out(d, length, time) if edge == "out" else _ramp_in(d, time)
    if kind in ("abblende", "weissblitz"):
        color = ":color=white" if kind == "weissblitz" else ""
        start = f"{length - d:.3f}" if edge == "out" else "0"
        return f",fade=t={edge}:st={start}:d={d:.3f}{color}"
    if kind == "weichzeichner":
        return _scaled(ramp, size, max(24, size[0] // 80), "bicubic")
    if kind == "pixel":
        return _scaled(ramp, size, max(24, size[0] // 60), "neighbor")
    # Zoom: hineinzoomen und dabei ins Dunkle blenden bzw. umgekehrt
    start = f"{length - d:.3f}" if edge == "out" else "0"
    return _zoomed(ramp, size) + f",fade=t={edge}:st={start}:d={d:.3f}"


def audio_filter(kind, edge, length):
    """Ton-Überblendung (mit führendem Komma): kurzes Aus- bzw. Einblenden, damit der Schnitt nicht knackt."""
    if kind == HART or kind not in SECONDS or length < MIN_PIECE or edge not in ("out", "in"):
        return ""
    d = min(AUDIO_SECONDS, _seconds(kind, length))
    start = f"{length - d:.3f}" if edge == "out" else "0"
    return f",afade=t={edge}:st={start}:d={d:.3f}"


def is_seam(previous, current, durations):
    """True, wenn zwei aufeinanderfolgende Teile nahtlos ineinander übergehen: Das eine endet am Ende seiner
    Quelldatei, das nächste beginnt am Anfang der nächsten Datei (Aufnahme in Teildateien). Dort wurde nichts
    herausgeschnitten, ein Übergang würde mitten in durchgehender Handlung abblenden."""
    if previous["file"] == current["file"]:
        return False
    return previous["end"] >= durations[previous["file"]] - 0.1 and current["start"] <= 0.1


def piece_filters(kind, n, count, length, size, seam_before=False, seam_after=False):
    """(Bild-Filter, Ton-Filter) für das n-te von `count` Teilen (n zählt ab 1).

    Das erste Teil bekommt nur ein Ende, das letzte nur einen Anfang: Folgenanfang und -ende bleiben unberührt.
    seam_before/seam_after: Die Grenze zum Nachbarteil ist nur ein Dateiwechsel ohne Schnitt (siehe `is_seam`).
    """
    video, audio = "", ""
    if n > 1 and not seam_before:
        video += video_filter(kind, "in", length, size)
        audio += audio_filter(kind, "in", length)
    if n < count and not seam_after:
        video += video_filter(kind, "out", length, size)
        audio += audio_filter(kind, "out", length)
    return video, audio
