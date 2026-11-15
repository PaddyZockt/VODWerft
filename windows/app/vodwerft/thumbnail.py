"""Generate a branded thumbnail from an episode MP4 without external services."""
import io
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat

from export_episode import duration
from thumbnail_theme import DEFAULT_FONT, resolve_theme


FONT_DIR = Path("C:/Windows/Fonts")
USER_FONT_DIR = Path.home() / "AppData/Local/Microsoft/Windows/Fonts"
BUNDLED_FONT_DIR = Path(__file__).resolve().parent / "fonts"  # mitgelieferte freie Schriften (Inter, OFL)
BUNDLED_FALLBACK = "Inter-Black.otf"
def load_face(font, size):
    """Schrift aus Windows-, Benutzer- oder Programm-Schriftordner; fehlt sie, kommt die Standardschrift, dann die mitgelieferte Inter, zuletzt Pillow."""
    for name in (font, DEFAULT_FONT, BUNDLED_FALLBACK):
        for folder in (FONT_DIR, USER_FONT_DIR, BUNDLED_FONT_DIR):
            path = folder / name
            if path.is_file():
                return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def frame_at(video, seconds):
    data = subprocess.check_output([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-ss", f"{seconds:.3f}",
        "-i", str(video), "-frames:v", "1", "-vf", "scale=1280:-2",
        "-f", "image2pipe", "-c:v", "mjpeg", "-",
    ])
    with Image.open(io.BytesIO(data)) as picture:
        return ImageOps.fit(picture.convert("RGB"), (1280, 720))


def score(frame):
    gray = ImageOps.grayscale(frame.resize((320, 180)))
    stats = ImageStat.Stat(gray)
    brightness = stats.mean[0]
    if not 38 <= brightness <= 218:
        return -1
    edges = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0]
    return stats.stddev[0] + edges * 0.3


def add_text(draw, text, xy, *, size, width, fill, font, stroke=0, stroke_fill="#0A0A0A"):
    while size >= 12:
        face = load_face(font, size)
        if draw.textlength(text, font=face) + 2 * stroke <= width:
            draw.text(xy, text, fill=fill, font=face, stroke_width=stroke, stroke_fill=stroke_fill)
            return
        size -= 2
    raise ValueError("Thumbnail text is too long")


def compose_thumbnail(frame, series, number, *, mission=None, style="numbered", theme=None):
    """Legt Verlauf, Balken und Titel auf ein 1280x720-Bild und gibt das fertige RGB-Bild zurueck."""
    theme = resolve_theme(theme)
    frame = frame.convert("RGBA")
    gradient = Image.new("RGBA", (1280, 720))
    overlay = ImageDraw.Draw(gradient)
    red, green, blue = (int(theme["background"][i:i + 2], 16) for i in (1, 3, 5))
    for y in range(360, 720):
        overlay.line((0, y, 1280, y), fill=(red, green, blue, round(205 * (y - 360) / 360)))
    frame = Image.alpha_composite(frame, gradient)
    draw = ImageDraw.Draw(frame)
    if theme["show_bar"]:
        draw.rectangle((54, 472, 65, 659), fill=theme["accent"])
    add_text(draw, series.upper(), (88, 468), size=59, width=950,
             fill=theme["text_color"], font=theme["font"], stroke=3,
             stroke_fill=theme["background"])
    if style == "numbered":
        add_text(draw, mission.upper() if mission else f"PART {number:02d}", (82, 526),
                 size=100 if mission else 116, width=1135 if mission else 700,
                 fill=theme["text_color"], font=theme["font"], stroke=5,
                 stroke_fill=theme["background"])
    return frame.convert("RGB")


def sample_frame():
    """Ein Beispielbild (ohne Video) fuer die Vorschau im Einstellungsfenster."""
    picture = Image.new("RGB", (1280, 720))
    draw = ImageDraw.Draw(picture)
    for y in range(720):
        shade = y / 720
        draw.line((0, y, 1280, y), fill=(round(38 + 30 * shade), round(70 + 50 * (1 - shade)), round(104 + 40 * (1 - shade))))
    draw.polygon([(0, 470), (260, 300), (470, 420), (700, 210), (960, 400), (1280, 280), (1280, 720), (0, 720)], fill=(34, 52, 62))
    draw.ellipse((900, 70, 1060, 230), fill=(236, 214, 160))
    return picture.filter(ImageFilter.GaussianBlur(2))


def render_preview(theme, series, number=1, *, mission=None, style="numbered", width=480):
    """Vorschau eines Thumbnails mit der echten Gestaltung; gibt ein verkleinertes RGB-Bild zurueck."""
    picture = compose_thumbnail(sample_frame(), series or "DEIN SPIEL", number, mission=mission, style=style, theme=theme)
    return picture.resize((width, round(width * 9 / 16)), Image.LANCZOS)


def make_thumbnail(video, target, series, number, *, frame_times=None, mission=None, style="numbered", theme=None):
    theme = resolve_theme(theme)
    if frame_times is None:
        length = duration(video)
        frame_times = [length * offset for offset in (.12, .24, .36, .48, .60, .72, .84)]
    frames = [frame_at(video, seconds) for seconds in frame_times]
    frame = max(frames, key=score)
    if score(frame) < 0:
        raise ValueError("No usable thumbnail frame in this episode")
    frame = compose_thumbnail(frame, series, number, mission=mission, style=style, theme=theme)
    temp = target.with_suffix(".part")
    frame.save(temp, format="JPEG", quality=89, optimize=True)
    if not 0 < temp.stat().st_size <= 2_000_000:
        raise ValueError("Thumbnail exceeds the upload size limit")
    temp.rename(target)
