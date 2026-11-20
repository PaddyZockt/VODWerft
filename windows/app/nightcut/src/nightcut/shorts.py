"""Render vertical Shorts: facecam on top, gameplay below, word-by-word captions.

A Short is ready to upload: its first audio track is the finished mix. Behind it the file
carries the single tracks of the recording, and a small timeline next to it puts them on
separate tracks, so the sound can still be balanced in the editor, like in the main timeline.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import export_xmeml
from .media import AudioStream, MediaInfo, crop_filter, encoder_options, ffmpeg_filters, probe, run
from .tracks import TimelineTrack

W, H = 1080, 1920

# Caption look per game profile. The keys are a contract with the profile editor; do not rename them.
CAPTION_DEFAULTS = {
    "font": "Bebas Neue", "font_size": 82, "primary_color": "#FFFFFF", "highlight_color": "#E50914",
    "outline_color": "#000000", "outline": 7, "box": False, "box_color": "#000000", "box_opacity": 70,
    "words_per_caption": 2, "position": "seam", "uppercase": True,
}
_INT_RANGES = {"font_size": (40, 160), "outline": (0, 12), "box_opacity": (20, 100), "words_per_caption": (1, 5)}
_COLOR_KEYS = ("primary_color", "highlight_color", "outline_color", "box_color")
_POSITIONS = {"top": 220, "middle": 960}  # pixels in the 1080x1920 frame; "seam" follows the layout
_HEX = re.compile(r"#[0-9A-Fa-f]{6}\Z")
_FONT_NAME = re.compile(r"[^,\x00-\x1f\x7f{}\\]{1,80}\Z")
# Families that ship one weight only: asking libass for bold would smear them with synthetic bold.
SINGLE_WEIGHT_FONTS = {"bebas neue", "anton", "bangers"}
BOX_PADDING = 14
# libass has no colour emoji and draws empty boxes instead; drop pictographs, flags, variation selectors, joiners.
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\U0001F1E6-\U0001F1FF\u2190-\u21FF\u2300-\u23FF\u2460-\u24FF"
                    "\u25A0-\u27BF\u2900-\u297F\u2B00-\u2BFF\u3030\u303D\u3297\u3299\uFE00-\uFE0F\u200D\u20E3"
                    "\U000E0020-\U000E007F]")
_ASS_CONTROL = re.compile(r"[{}\\\r\n\t]")


def caption_style(scfg: dict | None) -> dict:
    """Validated caption look: unknown or invalid values fall back to the defaults, numbers are clamped."""
    scfg = scfg if isinstance(scfg, dict) else {}
    style = dict(CAPTION_DEFAULTS)
    font = scfg.get("font")
    if isinstance(font, str) and font.strip() and _FONT_NAME.match(font.strip()):
        style["font"] = font.strip()
    for key, (low, high) in _INT_RANGES.items():
        value = scfg.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            continue
        style[key] = min(high, max(low, int(round(value))))
    for key in _COLOR_KEYS:
        value = scfg.get(key)
        if isinstance(value, str) and _HEX.match(value.strip()):
            style[key] = value.strip().upper()
    for key in ("box", "uppercase"):
        if isinstance(scfg.get(key), bool):
            style[key] = scfg[key]
    if scfg.get("position") in ("seam", *_POSITIONS):
        style["position"] = scfg["position"]
    return style


def caption_position(style: dict, seam_y: int) -> int:
    """Vertical centre of the captions; 'seam' is the edge between facecam and gameplay."""
    return _POSITIONS.get(style["position"], seam_y)


def pick(clips: list[dict], count: int, min_s: float) -> list[dict]:
    """Strongest clips of the edit, best first."""
    usable = [c for c in clips if c["end"] - c["start"] >= min_s]
    return sorted(usable, key=lambda c: c.get("final_score", c["score"]), reverse=True)[:count]


def separate_tracks(audio: list[TimelineTrack], scfg: dict) -> list[TimelineTrack]:
    """The single tracks a Short carries behind its finished mix (`shorts.separate_audio`).
    The mix track of the recording is left out, the Short has its own. A recording with one
    track only has nothing to balance: the Short stays a file with one audio track."""
    if not scfg.get("separate_audio", True):
        return []
    single = [t for t in audio if not t.muted]
    return single if len(single) > 1 else []


def _audio_outputs(tracks: list[TimelineTrack]) -> list[str]:
    """ffmpeg options for the audio of a Short: the finished mix first and marked as default
    (players and upload sites take that one), then the single tracks, named like in the timeline."""
    args = ["-map", "[a]"]
    if not tracks:
        return args
    for pos, label in enumerate(["MIX"] + [t.label for t in tracks]):
        if pos:
            args += ["-map", f"0:{tracks[pos - 1].stream.index}"]
        args += [f"-metadata:s:a:{pos}", f"title={label}", f"-metadata:s:a:{pos}", f"handler_name={label}",
                 f"-disposition:a:{pos}", "default" if pos == 0 else "0"]
    return args


def write_timeline(short: Path, n: int, title: str, tracks: list[TimelineTrack], cfg: dict, name: str) -> Path:
    """Timeline for one Short (`short_01.xml` next to `short_01.mp4`): the single tracks on separate
    audio tracks, the finished mix on the first one but switched off, so nothing sounds twice."""
    info = probe(short)
    labels = ["MIX"] + [t.label for t in tracks]
    audio = [TimelineTrack(s, label, muted=pos == 0) for pos, (s, label) in enumerate(zip(info.audio, labels))]
    clip = {"n": n, "title": title or "Short", "start": 0.0, "end": info.duration, "trim_in": 0.0,
            "gameplay_file": str(short), "facecam_file": None}
    return export_xmeml.write([clip], audio, cfg, short.with_suffix(".xml"), name)


def word_timestamps(pcm: np.ndarray, sample_rate: int, start: float, end: float, cfg: dict, asr) -> list[dict]:
    audio = np.asarray(pcm[int(start * sample_rate):int(end * sample_rate)], dtype=np.float32) / 32768.0
    res = asr({"raw": audio, "sampling_rate": sample_rate}, return_timestamps="word",
              generate_kwargs={"language": cfg["transcribe"]["language"], "task": "transcribe"})
    words = []
    for ch in res.get("chunks", []):
        a, b = ch["timestamp"]
        text = ch["text"].strip()
        if text and a is not None:
            words.append({"start": a, "end": b if b is not None else a + 0.4, "text": text})
    return words


def _ass_time(t: float) -> str:
    t = max(t, 0.0)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def _clean(word: str, uppercase: bool = True) -> str:
    """Caption text of one word: no ASS control characters (override injection), no emoji."""
    word = _EMOJI.sub("", _ASS_CONTROL.sub("", str(word))).strip(" ,.;:")
    return word.upper() if uppercase else word


def _ass_color(hex_rgb: str, alpha: int = 0) -> str:
    """#RRGGBB -> &HAABBGGRR; alpha 00 is opaque."""
    value = hex_rgb.lstrip("#")
    return f"&H{alpha:02X}{value[4:6]}{value[2:4]}{value[0:2]}".upper()


def _box_alpha(opacity_percent: int) -> int:
    return round((100 - opacity_percent) / 100 * 255)


def caption_events(words: list[dict], style: dict) -> list[dict]:
    """Groups of a few words; one event per spoken word: {start, end, words, highlight}."""
    cleaned = []
    for w in words:
        text = _clean(w["text"], style["uppercase"])
        if text:
            cleaned.append({**w, "text": text})
    events = []
    n = style["words_per_caption"]
    for g in range(0, len(cleaned), n):
        group = cleaned[g:g + n]
        texts = [x["text"] for x in group]
        for i, w in enumerate(group):
            # Whisper sometimes stretches a word back into the silence before it.
            start = max(w["start"], w["end"] - 0.8)
            end = group[i + 1]["start"] if i + 1 < len(group) else w["end"] + 0.25
            end = min(end, w["end"] + 0.6)  # do not keep text on screen through a pause
            events.append({"start": float(start), "end": float(end), "words": texts, "highlight": i})
    return events


def ass_document(events: list[dict], style: dict, y: int, wrap_style: int = 2) -> str:
    hi = _ass_color(style["highlight_color"])
    primary = _ass_color(style["primary_color"])
    bold = 0 if style["font"].casefold() in SINGLE_WEIGHT_FONTS else -1
    if style["box"]:
        # BorderStyle 4 (libass): one box per event in BackColour, padded by Shadow. BorderStyle 3 breaks
        # when the player scales the script. The text outline is switched off inside the box.
        back = _ass_color(style["box_color"], _box_alpha(style["box_opacity"]))
        border_style, outline, shadow = 4, 0, BOX_PADDING
    else:
        back, border_style, outline, shadow = "&H64000000", 1, style["outline"], 3
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", f"WrapStyle: {wrap_style}",
        "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Cap,{style['font']},{style['font_size']},{primary},{primary},{_ass_color(style['outline_color'])},"
        f"{back},{bold},0,0,0,100,100,2,0,{border_style},{outline},{shadow},5,60,60,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for event in events:
        text = " ".join(f"{{\\c{hi}}}{word}{{\\r}}" if j == event["highlight"] else word
                        for j, word in enumerate(event["words"]))
        lines.append(f"Dialogue: 0,{_ass_time(event['start'])},{_ass_time(event['end'])},Cap,,0,0,0,,"
                     f"{{\\pos({W // 2},{y})}}{text}")
    return "\n".join(lines) + "\n"


def _events_path(ass: Path) -> Path:
    return ass.with_suffix(".captions.json")


def write_captions(events: list[dict], path: Path, scfg: dict, caption_y: int, wrap_style: int = 2) -> None:
    """Write the ASS file and, next to it, the same events as data for the PNG backend."""
    style = caption_style(scfg)
    path.write_text(ass_document(events, style, caption_position(style, caption_y), wrap_style), encoding="utf-8")
    _events_path(path).write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")


def write_ass(words: list[dict], path: Path, scfg: dict, caption_y: int) -> None:
    """Groups of a few words; the word being spoken is highlighted."""
    write_captions(caption_events(words, caption_style(scfg)), path, scfg, caption_y)


def _filter_path(p: Path) -> str:
    """Escape a Windows path for use inside an ffmpeg filter argument."""
    return p.resolve().as_posix().replace(":", r"\:").replace("'", r"\'")


def _ass_seconds(value: str) -> float:
    h, m, s = value.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _caption_backend(scfg: dict) -> str:
    backend = scfg.get("caption_backend", "auto")
    if backend == "auto":
        return "subtitles" if "subtitles" in ffmpeg_filters() else "png_video"
    if backend not in {"subtitles", "png_video"}:
        raise ValueError(f"Unknown shorts.caption_backend: {backend}")
    return backend


_HIGHLIGHT = re.compile(r"\{\\c&H[0-9A-F]+\}(.+?)(?:\{\\r\}|\{\\c&H00FFFFFF\})", re.IGNORECASE)


def _read_events(ass: Path) -> list[dict]:
    """Caption events as data; falls back to parsing an ASS file that has no data file next to it."""
    try:
        events = json.loads(_events_path(ass).read_text(encoding="utf-8"))
        if isinstance(events, list):
            return events
    except (OSError, ValueError):
        pass
    events = []
    for line in ass.read_text(encoding="utf-8").splitlines():
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) != 10:
            continue
        raw = parts[9]
        highlighted = _HIGHLIGHT.search(raw)
        words = re.sub(r"\{[^}]*\}", "", raw).split()
        target = highlighted.group(1).strip() if highlighted else None
        events.append({"start": _ass_seconds(parts[1]), "end": _ass_seconds(parts[2]), "words": words,
                       "highlight": words.index(target) if target in words else -1})
    return events


def _font_dirs(fonts_dir) -> list[Path]:
    home = Path.home()
    dirs = [Path(fonts_dir)] if fonts_dir else []
    dirs += [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
             Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local")) / "Microsoft/Windows/Fonts",
             home / ".fonts", home / ".local/share/fonts", Path("/usr/local/share/fonts"), Path("/usr/share/fonts"),
             home / "Library/Fonts", Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental")]
    return [d for d in dirs if d.is_dir()]


def _font_files(directory: Path) -> list[Path]:
    try:
        return sorted(p for p in directory.rglob("*") if p.suffix.lower() in (".ttf", ".otf") and p.is_file())
    except OSError:
        return []


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def _family_match(path: Path, family: str, styles: list[str]) -> int | None:
    """Rank of a font file for a family via its name table (lower is better); needs fontTools."""
    from fontTools.ttLib import TTFont

    try:
        with TTFont(str(path), lazy=True, fontNumber=0) as font:
            names = font["name"]
            families = {_norm(str(names.getDebugName(i) or "")) for i in (1, 16)}
            full = _norm(str(names.getDebugName(4) or ""))
            sub = _norm(str(names.getDebugName(17) or names.getDebugName(2) or ""))
    except Exception:
        return None
    if _norm(family) not in families and _norm(family) != full:
        return None
    return styles.index(sub) if sub in styles else len(styles)


def find_font(family: str, fonts_dir=None) -> Path | None:
    """Map a family name ('Bebas Neue') to a font file. libass finds fonts by family, Pillow needs the path."""
    direct = Path(family)
    if direct.suffix.lower() in (".ttf", ".otf") and direct.is_file():
        return direct
    base = _norm(family)
    if not base:
        return None
    single = family.casefold() in SINGLE_WEIGHT_FONTS
    suffixes = ["", "regular", "bold", "bd"] if single else ["bold", "bd", "", "regular"]
    dirs = _font_dirs(fonts_dir)
    listings = [_font_files(d) for d in dirs]
    # 1) File name heuristic: BebasNeue-Regular.ttf, Bebas Neue.ttf, Anton-Regular.ttf, arialbd.ttf ...
    for files in listings:
        by_stem = {}
        for path in files:
            by_stem.setdefault(_norm(path.stem), path)
        for suffix in suffixes:
            if base + suffix in by_stem:
                return by_stem[base + suffix]
    # 2) Name table (only with fontTools installed): finds files whose name does not show the family.
    try:
        import fontTools.ttLib  # noqa: F401
    except ImportError:
        return None
    styles = ["regular", "bold"] if single else ["bold", "regular"]
    for files in listings:
        ranked = [(rank, path) for path in files[:3000]
                  if (rank := _family_match(path, family, styles)) is not None]
        if ranked:
            return min(ranked, key=lambda item: item[0])[1]
    return None


_FALLBACK_FONTS = ("C:/Windows/Fonts/arialbd.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                   "/Library/Fonts/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def _caption_font(style: dict, fonts_dir) -> ImageFont.FreeTypeFont:
    path = find_font(style["font"], fonts_dir)
    if path is None:
        path = next((Path(p) for p in _FALLBACK_FONTS if Path(p).is_file()), None)
        if path is None:
            raise RuntimeError(f"Caption font '{style['font']}' was not found; set shorts.fonts_dir in the config")
        print(f"Warnung: Schrift '{style['font']}' wurde nicht gefunden – die Untertitel nutzen ersatzweise "
              f"{path.name}. Schrift installieren oder die .ttf in shorts.fonts_dir ablegen.",
              file=sys.stderr, flush=True)
    return ImageFont.truetype(str(path), int(style["font_size"]))


def caption_strip_height(style: dict) -> int:
    """Height of the transparent caption strip of the PNG backend (even number, grows with the font)."""
    margin = BOX_PADDING if style["box"] else style["outline"] + 6  # 6: room for the soft shadow
    return int(math.ceil((style["font_size"] * 1.5 + 2 * margin + 16) / 2) * 2)


def _hex_rgba(hex_rgb: str, alpha: int = 255) -> tuple:
    value = hex_rgb.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha)


def _caption_image(event: dict, style: dict, font, height: int) -> Image.Image:
    image = Image.new("RGBA", (W, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    words = [str(word) for word in event.get("words", [])]
    if not words:
        return image
    widths = [draw.textlength(w, font=font) for w in words]
    space = draw.textlength(" ", font=font)
    total = sum(widths) + space * (len(words) - 1)
    x = (W - total) / 2
    middle = height / 2
    stroke = 0 if style["box"] else int(style["outline"])
    if style["box"]:
        ascent, descent = font.getmetrics()
        half = (ascent + descent) / 2 + BOX_PADDING
        draw.rounded_rectangle((max(0, x - BOX_PADDING * 1.5), max(0, middle - half),
                                min(W, x + total + BOX_PADDING * 1.5), min(height, middle + half)),
                               radius=BOX_PADDING, fill=_hex_rgba(style["box_color"],
                                                                  255 - _box_alpha(style["box_opacity"])))
    for index, (word, width) in enumerate(zip(words, widths)):
        color = style["highlight_color"] if index == event.get("highlight") else style["primary_color"]
        draw.text((x, middle), word, font=font, anchor="lm", fill=_hex_rgba(color),
                  stroke_width=stroke, stroke_fill=_hex_rgba(style["outline_color"]))
        x += width + space
    return image


def _png_caption_video(ass: Path, scfg: dict, duration: float) -> Path:
    """Render captions to one small alpha MOV; avoids one FFmpeg filter graph per word."""
    style = caption_style(scfg)
    events = sorted(_read_events(ass), key=lambda event: event["start"])
    height = caption_strip_height(style)
    font = _caption_font(style, scfg.get("fonts_dir"))
    images = [_caption_image(event, style, font, height).tobytes() for event in events]
    blank = Image.new("RGBA", (W, height), (0, 0, 0, 0)).tobytes()

    mov = ass.with_suffix(".captions.mov")
    cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba",
           "-s", f"{W}x{height}", "-r", "30", "-i", "-", "-an", "-c:v", "qtrle", "-pix_fmt", "argb", str(mov)]
    with tempfile.TemporaryFile() as errors:  # a file, not a pipe: a full pipe would block ffmpeg
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=errors)
        failed = False
        try:
            assert proc.stdin is not None
            index = 0
            try:
                for frame in range(max(1, round(duration * 30))):
                    t = frame / 30
                    while index < len(events) and t > events[index]["end"]:
                        index += 1
                    shown = index < len(events) and events[index]["start"] <= t <= events[index]["end"]
                    proc.stdin.write(images[index] if shown else blank)
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                failed = True  # ffmpeg went away; its own message follows below
            if proc.wait() != 0:
                failed = True
        finally:
            if proc.poll() is None:  # interrupted (Ctrl+C, error while drawing): do not leave ffmpeg behind
                proc.kill()
                proc.wait()
                failed = True
            if failed:
                errors.seek(0)
                detail = errors.read().decode("utf-8", "replace").strip()[-2000:]
                print(f"Untertitel-Video abgebrochen (ffmpeg): {detail or 'keine Fehlermeldung'}",
                      file=sys.stderr, flush=True)
        if failed:
            raise RuntimeError("Could not render PNG caption video")
    return mov


def render(info: MediaInfo, clip: dict, n: int, streams: dict[str, AudioStream], ass: Path, cfg: dict,
           out_dir: Path, gpu: int | None = None, tracks: list[TimelineTrack] | None = None) -> Path:
    """streams: what goes into the finished mix. tracks: single tracks kept behind it (see separate_tracks)."""
    scfg = cfg["shorts"]
    out = out_dir / f"short_{n:02d}.mp4"
    start = clip["start"]
    dur = min(clip["end"] - clip["start"], scfg["max_s"])
    lay = cfg["layout"]

    if lay.get("facecam"):
        cam_h = round(W * 9 / 16 / 2) * 2                      # 16:9 camera across the full width
        game_h = H - cam_h
        graph = (f"[0:v]{crop_filter(lay['facecam'], info.width, info.height)},scale={W}:{cam_h}:force_original_aspect_ratio=increase,crop={W}:{cam_h}[cam];"
                 f"[0:v]{crop_filter(lay['gameplay'], info.width, info.height)},"
                 f"crop=ih*{W}/{game_h}:ih,scale={W}:{game_h}[game];[cam][game]vstack,setsar=1[stack];")
        src = "[stack]"
    else:
        graph = f"[0:v]{crop_filter(lay['gameplay'], info.width, info.height)},crop=ih*9/16:ih,scale={W}:{H},setsar=1[stack];"
        src = "[stack]"
    caption_video = None
    caption_backend = _caption_backend(scfg)
    if caption_backend == "png_video":
        caption_video = _png_caption_video(ass, scfg, dur)
        style = caption_style(scfg)
        top = caption_position(style, caption_y(cfg)) - caption_strip_height(style) // 2
        graph += f"{src}[1:v]overlay=0:{max(0, top)}:eof_action=pass,setsar=1[v];"
    else:
        sub = f"subtitles=filename='{_filter_path(ass)}'"
        if scfg.get("fonts_dir"):
            sub += f":fontsdir='{_filter_path(Path(scfg['fonts_dir']))}'"
        graph += f"{src}{sub}[v];"
    audio_in = "".join(f"[0:{s.index}]" for s in streams.values())
    graph += f"{audio_in}amix=inputs={len(streams)}:normalize=0:dropout_transition=0[a]"

    inputs = ["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(info.path)]
    if caption_video:
        inputs += ["-i", str(caption_video)]
    run(["ffmpeg", "-hide_banner", "-v", "error", "-y", *inputs,
         "-filter_complex", graph, "-map", "[v]", *_audio_outputs(tracks or []),
         *encoder_options(cfg["render"]["codec"], 20, gpu, cfg["render"].get("video_bitrate")),
         "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])
    return out


def caption_y(cfg: dict) -> int:
    """Captions sit on the edge between facecam and gameplay."""
    if cfg["layout"].get("facecam"):
        return round(W * 9 / 16 / 2) * 2 + 40
    return int(H * 0.7)
