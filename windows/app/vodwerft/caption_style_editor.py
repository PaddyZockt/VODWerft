"""Clip-Stil: Aussehen der Untertitel in den Hochkant-Clips, pro Spielprofil.

Der obere Teil dieser Datei ist reine Logik ohne Tk (Vorlagen, Prüfen/Begrenzen der Werte,
Aufteilung des Satzes in Untertitel-Zeilen, Vorschaubild mit Pillow) und wird von den Tests
abgedeckt. Das Fenster selbst (`open_in`) steht im unteren Teil.

Schlüssel des Stils (Vertrag mit der Clip-Erstellung):
font, font_size, primary_color, highlight_color, outline_color, outline, box, box_color,
box_opacity, words_per_caption, position ("seam" | "top" | "middle"), uppercase.
"""
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

DEFAULTS = {
    "font": "Bebas Neue", "font_size": 82, "primary_color": "#FFFFFF", "highlight_color": "#E50914",
    "outline_color": "#000000", "outline": 7, "box": False, "box_color": "#000000", "box_opacity": 70,
    "words_per_caption": 2, "position": "seam", "uppercase": True,
}
LIMITS = {"font_size": (40, 160), "outline": (0, 12), "box_opacity": (20, 100), "words_per_caption": (1, 5)}
COLOR_KEYS = ("primary_color", "highlight_color", "outline_color", "box_color")
POSITIONS = ("seam", "top", "middle")
FALLBACK_FONT = "Arial Black"
MISSING_SUFFIX = " (nicht installiert)"
CUSTOM = "Eigener Stil"
SAMPLE = "Das war einfach unglaublich"

# Bildmaße der Hochkant-Clips und Lage der Untertitel (Mitte der Zeile, in Originalpixeln).
WIDTH, HEIGHT = 1080, 1920
FACECAM_HEIGHT = 608                       # 16:9-Kamerabild über die volle Breite
POSITION_Y = {"seam": 648, "top": 220, "middle": 960}
SEAM_Y_WITHOUT_FACECAM = 1344              # ohne Facecam sitzt "seam" im unteren Drittel


def _preset(**changes):
    return {**DEFAULTS, **changes}


PRESETS = [
    ("Nightcut Rot", _preset()),
    ("Klassisch Gelb", _preset(font="Arial Black", font_size=72, highlight_color="#FFE600", outline=8,
                               words_per_caption=3)),
    ("Box Schwarz", _preset(font="Montserrat ExtraBold", font_size=64, outline=0, box=True, box_color="#000000",
                            box_opacity=70, highlight_color="#00E5FF", words_per_caption=3, uppercase=False)),
    ("Neon Grün", _preset(font="Anton", font_size=86, highlight_color="#39FF14")),
    ("Comic", _preset(font="Bangers", font_size=92, primary_color="#FFE600", outline=10,
                      highlight_color="#FF3344")),
    ("Dezent", _preset(font="Segoe UI Semibold", font_size=56, outline=4, highlight_color="#FFD166",
                       words_per_caption=4, uppercase=False)),
    ("Einzelwort", _preset(font="Impact", font_size=120, highlight_color="#FF5E1A", words_per_caption=1,
                           position="middle")),
    ("Helle Box", _preset(font="Montserrat ExtraBold", font_size=64, primary_color="#111111", outline=0, box=True,
                          box_color="#FFFFFF", box_opacity=90, highlight_color="#D91E36", words_per_caption=3,
                          uppercase=False)),
]


# --- Werte prüfen -----------------------------------------------------------------------------

def valid_color(value):
    return isinstance(value, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", value.strip()) is not None


def _number(value, default, low, high):
    try:
        if isinstance(value, bool):
            raise ValueError
        number = int(round(float(str(value).strip().replace(",", "."))))
    except (TypeError, ValueError, OverflowError):
        return default
    return max(low, min(high, number))


def _flag(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str) and value.strip().casefold() in ("true", "1", "ja", "yes", "false", "0", "nein", "no"):
        return value.strip().casefold() in ("true", "1", "ja", "yes")
    return default


def normalize(style):
    """Vollständiger, gültiger Stil: fehlende oder kaputte Angaben werden durch den Standard ersetzt,
    Zahlen auf den erlaubten Bereich begrenzt, Farben als #RRGGBB in Großbuchstaben."""
    source = style if isinstance(style, dict) else {}
    result = dict(DEFAULTS)
    font = source.get("font")
    if isinstance(font, str) and font.strip():
        result["font"] = clean_font(font)
    for key, (low, high) in LIMITS.items():
        result[key] = _number(source.get(key), DEFAULTS[key], low, high)
    for key in COLOR_KEYS:
        if valid_color(source.get(key)):
            result[key] = source[key].strip().upper()
    for key in ("box", "uppercase"):
        result[key] = _flag(source.get(key), DEFAULTS[key])
    if source.get("position") in POSITIONS:
        result["position"] = source["position"]
    return result


def clean_font(label):
    """Schriftname ohne den Zusatz „(nicht installiert)“."""
    label = label.strip()
    return label[:-len(MISSING_SUFFIX)].strip() if label.endswith(MISSING_SUFFIX) else label


def preset_name(style):
    """Name der Vorlage, die genau diesem Stil entspricht, sonst None."""
    current = normalize(style)
    for name, preset in PRESETS:
        if current == preset:
            return name
    return None


def summary(style):
    """Kurzinfo für die Profilseite, z. B. „Nightcut Rot · Bebas Neue 82“."""
    current = normalize(style)
    return f"{preset_name(current) or CUSTOM} · {current['font']} {current['font_size']}"


def position_label(position, has_facecam=True):
    if position == "seam":
        return "Zwischen Facecam und Spiel" if has_facecam else "Unteres Drittel"
    return {"top": "Oben", "middle": "Mitte"}[position]


def position_y(position, has_facecam=True):
    """Senkrechte Mitte der Untertitel in Originalpixeln (1080 x 1920)."""
    if position == "seam" and not has_facecam:
        return SEAM_Y_WITHOUT_FACECAM
    return POSITION_Y.get(position, POSITION_Y["seam"])


# --- Satz in Untertitel-Zeilen aufteilen ------------------------------------------------------

def split_captions(text, words_per_caption):
    """Teilt einen Satz in Zeilen mit höchstens `words_per_caption` Wörtern."""
    words = text.split() if isinstance(text, str) else list(text)
    size = _number(words_per_caption, DEFAULTS["words_per_caption"], *LIMITS["words_per_caption"])
    return [words[start:start + size] for start in range(0, len(words), size)]


def caption_for_word(text, words_per_caption, word_index):
    """Zeile, die gerade zu sehen ist, wenn das Wort `word_index` gesprochen wird.

    Gibt (Wörter der Zeile, Stelle des gesprochenen Worts in dieser Zeile) zurück."""
    lines = split_captions(text, words_per_caption)
    total = sum(len(line) for line in lines)
    if not total:
        return [], 0
    index = max(0, min(total - 1, int(word_index)))
    for line in lines:
        if index < len(line):
            return line, index
        index -= len(line)
    return lines[-1], len(lines[-1]) - 1


def display_text(word, uppercase):
    return word.upper() if uppercase else word


def rgba(color, opacity=100):
    """#RRGGBB + Deckkraft in Prozent -> (r, g, b, a)."""
    value = color.lstrip("#")
    alpha = round(255 * max(0, min(100, opacity)) / 100)
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha


# --- Schriften --------------------------------------------------------------------------------

def bundled_fonts(fonts_dir):
    """Mitgelieferte Schriftdateien: {Schriftname: Pfad}. Der Name kommt aus der Datei selbst."""
    found = {}
    if not fonts_dir:
        return found
    try:
        files = sorted(p for p in Path(fonts_dir).iterdir() if p.suffix.lower() in (".ttf", ".otf"))
    except OSError:
        return found
    for path in files:
        name = path.stem
        try:
            from PIL import ImageFont
            family, variant = ImageFont.truetype(str(path), 20).getname()
            if family:
                plain = not variant or variant in ("Regular", "Bold") or variant in family
                name = family if plain else f"{family} {variant}"
        except Exception:  # noqa: BLE001 - defekte Schriftdatei oder Pillow fehlt: Dateiname genügt
            pass
        found.setdefault(name, path)
    return found


def font_choices(bundled, installed, current=None):
    """Auswahlliste: zuerst mitgelieferte, dann installierte Schriften.

    Fehlt die aktuell gewählte Schrift (z. B. aus einer Vorlage), steht sie mit dem Zusatz
    „(nicht installiert)“ ganz oben."""
    result = list(bundled)
    known = {name.casefold() for name in result}
    for name in sorted({n for n in installed if n and not n.startswith("@")}, key=str.casefold):
        if name.casefold() not in known:
            known.add(name.casefold())
            result.append(name)
    if current and clean_font(current).casefold() not in known:
        result.insert(0, clean_font(current) + MISSING_SUFFIX)
    return result


def font_label(name, bundled, installed):
    """Text für die Auswahl: der Name selbst oder mit Zusatz, wenn die Schrift fehlt."""
    known = {n.casefold() for n in bundled} | {n.casefold() for n in installed}
    name = clean_font(name)
    return name if name.casefold() in known else name + MISSING_SUFFIX


def effective_font(label):
    """Schrift, die wirklich verwendet wird: fehlt die gewählte, dann die Ersatzschrift."""
    return FALLBACK_FONT if label.strip().endswith(MISSING_SUFFIX) else clean_font(label)


@lru_cache(maxsize=None)
def _windows_fonts():
    fonts = {}
    if sys.platform != "win32":
        return fonts
    try:
        import os
        import winreg
        folders = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
                   Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"]
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                key = winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
            except OSError:
                continue
            with key:
                for index in range(winreg.QueryInfoKey(key)[1]):
                    title, file, _ = winreg.EnumValue(key, index)
                    path = Path(str(file))
                    if path.suffix.lower() not in (".ttf", ".otf"):
                        continue
                    if not path.is_absolute():
                        path = next((folder / path for folder in folders if (folder / path).is_file()), path)
                    fonts.setdefault(re.sub(r"\s*\((TrueType|OpenType)\)\s*$", "", title).casefold(), path)
    except Exception:  # noqa: BLE001 - ohne Schriftliste bleibt die Ersatzschrift in der Vorschau
        pass
    return fonts


@lru_cache(maxsize=256)
def system_font_file(name):
    """Datei einer installierten Schrift (für die Vorschau), oder None."""
    wanted = name.casefold()
    if sys.platform == "win32":
        fonts = _windows_fonts()
        for candidate in (wanted, wanted + " regular", wanted + " bold"):
            path = fonts.get(candidate)
            if path and path.is_file():
                return path
        return None
    try:
        answer = subprocess.run(["fc-match", "-f", "%{file}|%{family}|%{fullname}", name], capture_output=True,
                                text=True, timeout=3, check=False).stdout
        file, _, names = answer.partition("|")
        if file and any(wanted == part.strip().casefold() or wanted.startswith(part.strip().casefold() + " ")
                        for part in re.split(r"[|,]", names) if part.strip()):
            return Path(file)
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def font_file(name, bundled=None):
    """Schriftdatei für `name`: zuerst mitgeliefert, dann installiert. None, wenn nichts passt."""
    for known, path in (bundled or {}).items():
        if known.casefold() == name.casefold():
            return Path(path)
    return system_font_file(name)


def load_font(path, pixels):
    """Pillow-Schrift in der gewünschten Größe; notfalls die Ersatzschrift oder Pillows Standardschrift."""
    from PIL import ImageFont

    pixels = max(4, int(round(pixels)))
    candidates = [path, system_font_file(FALLBACK_FONT), "arialbd.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return ImageFont.truetype(str(candidate), pixels)
        except OSError:
            continue
    return ImageFont.load_default(pixels)


# --- Vorschaubild (Pillow, ohne Tk) -----------------------------------------------------------

FACECAM_COLOR = "#6E737B"
GAME_TOP, GAME_BOTTOM = (36, 58, 82), (14, 22, 34)


def draw_caption(image, style, words, highlight, *, center, font, factor=1.0):
    """Zeichnet eine Untertitel-Zeile mittig um `center` (x, y). Gibt die Textbreite zurück."""
    from PIL import Image, ImageDraw

    draw = ImageDraw.Draw(image)
    texts = [display_text(word, style["uppercase"]) for word in words]
    widths = [draw.textlength(text, font=font) for text in texts]
    space = draw.textlength(" ", font=font)
    total = sum(widths) + space * max(0, len(texts) - 1)
    ascent, descent = font.getmetrics()
    height = ascent + descent
    left, top = center[0] - total / 2, center[1] - height / 2
    stroke = 0 if style["box"] else int(round(style["outline"] * factor))
    if style["box"] and texts:
        pad_x, pad_y = height * 0.32, height * 0.10
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).rounded_rectangle(
            (left - pad_x, top - pad_y, left + total + pad_x, top + height + pad_y),
            radius=height * 0.18, fill=rgba(style["box_color"], style["box_opacity"]))
        image.alpha_composite(layer)
        draw = ImageDraw.Draw(image)
    x = left
    for index, (text, width) in enumerate(zip(texts, widths)):
        draw.text((x, top), text, font=font,
                  fill=style["highlight_color"] if index == highlight else style["primary_color"],
                  stroke_width=stroke, stroke_fill=style["outline_color"])
        x += width + space
    return total


def render_preview(style, word_index=0, *, has_facecam=True, font_path=None, scale=0.25, supersample=2,
                   text=SAMPLE):
    """Vorschau eines Hochkant-Clips als Pillow-Bild. Gibt (Bild, passt_ins_Bild) zurück."""
    from PIL import Image, ImageDraw

    style = normalize(style)
    factor = scale * supersample
    width, height = round(WIDTH * factor), round(HEIGHT * factor)
    image = Image.new("RGBA", (width, height), GAME_BOTTOM + (255,))
    draw = ImageDraw.Draw(image)
    seam = round(FACECAM_HEIGHT * factor) if has_facecam else 0
    for y in range(seam, height):  # Spielfläche als ruhiger Verlauf
        part = (y - seam) / max(1, height - seam)
        draw.line((0, y, width, y), fill=tuple(round(a + (b - a) * part) for a, b in zip(GAME_TOP, GAME_BOTTOM)))
    label_font = load_font(None, 40 * factor)
    if has_facecam:
        draw.rectangle((0, 0, width, seam), fill=FACECAM_COLOR)
        draw.text((width / 2, seam / 2), "Facecam", font=label_font, fill="#C9CDD3", anchor="mm")
    draw.text((width / 2, height - 150 * factor), "Gameplay", font=label_font, fill="#52657B", anchor="mm")
    words, highlight = caption_for_word(text, style["words_per_caption"], word_index)
    font = load_font(font_path, style["font_size"] * factor)
    total = draw_caption(image, style, words, highlight, font=font, factor=factor,
                         center=(width / 2, position_y(style["position"], has_facecam) * factor))
    fits = total <= width - 2 * 40 * factor
    target = (round(WIDTH * scale), round(HEIGHT * scale))
    if image.size != target:
        image = image.resize(target, Image.LANCZOS)
    return image.convert("RGB"), fits


def render_tile(style, *, font_path=None, size=(120, 44), supersample=2):
    """Kleine Kachel „Aa“ im Stil einer Vorlage (A in Textfarbe, a in der Farbe des gesprochenen Worts)."""
    from PIL import Image

    style = normalize(style)
    width, height = size[0] * supersample, size[1] * supersample
    image = Image.new("RGBA", (width, height), (52, 64, 82, 255))
    tile = {**style, "outline": min(style["outline"], 8) * 0.55, "words_per_caption": 2}
    font = load_font(font_path, height * 0.62)
    draw_caption(image, tile, ["A", "a"], 1, center=(width / 2, height / 2), font=font)
    return image.resize(size, Image.LANCZOS).convert("RGB")


# --- Anbindung an das Spielprofil --------------------------------------------------------------

def profile_style(config):
    """Gespeicherter Clip-Stil eines Profils oder None, wenn noch keiner gewählt wurde."""
    stored = config.get("caption_style") if isinstance(config, dict) else None
    return normalize(stored) if isinstance(stored, dict) and stored else None


def clip_settings(config):
    """(hat Facecam, Ordner mit mitgelieferten Schriften) aus der Clip-Konfiguration des Profils."""
    has_facecam, fonts_dir = True, None
    try:
        import yaml
        data = yaml.safe_load(Path(config["clips_config"]).read_text(encoding="utf-8-sig")) or {}
        if "layout" in data:
            has_facecam = bool((data.get("layout") or {}).get("facecam"))
        fonts_dir = (data.get("shorts") or {}).get("fonts_dir") or None
    except Exception:  # noqa: BLE001 - ohne lesbare Clip-Konfiguration gelten die üblichen Annahmen
        pass
    return has_facecam, fonts_dir


def save_profile_with_style(save_profile, main, path, caption_style=None, **values):
    """Ruft `game_profiles.save_profile` auf und gibt den Clip-Stil als `caption_style=` mit.

    None lässt den gespeicherten Stil unverändert; ein Dict wird vorher geprüft und vervollständigt."""
    style = normalize(caption_style) if isinstance(caption_style, dict) else None
    return save_profile(main, path, caption_style=style, **values)


# --- Fenster ----------------------------------------------------------------------------------

def open_in(parent, style, on_apply, *, has_facecam=True, fonts_dir=None):
    """Clip-Stil als Fenster des Hauptprogramms öffnen. `on_apply(dict)` bekommt den gewählten Stil."""
    import tkinter as tk

    existing = getattr(parent, "_caption_style_window", None)
    if existing is not None and existing.winfo_exists():
        existing.lift()
        existing.focus_force()
        return existing
    top = parent.winfo_toplevel()
    window = tk.Toplevel(top)
    window.transient(top)
    window.editor = CaptionStyleEditor(window, style, on_apply, has_facecam=has_facecam, fonts_dir=fonts_dir)
    window.update_idletasks()
    width, height = 880, 640
    x = top.winfo_rootx() + max(0, (top.winfo_width() - width) // 2)
    y = top.winfo_rooty() + max(0, (top.winfo_height() - height) // 3)
    window.geometry(f"{width}x{height}{x:+d}{y:+d}")
    window.minsize(820, 600)
    parent._caption_style_window = window
    # Wie beim Thumbnail-Stil: Das Hauptfenster ist gesperrt, solange dieses Fenster offen ist.
    try:
        window.wait_visibility()
        window.grab_set()
    except tk.TclError:
        pass  # Fenster nicht sichtbar (z. B. Test ohne Bildschirm): ohne Sperre weiterarbeiten
    return window


class CaptionStyleEditor:
    PREVIEW = (270, 480)
    TILE = (120, 44)

    def __init__(self, root, style, on_apply, *, has_facecam=True, fonts_dir=None):
        import tkinter as tk
        from tkinter import font as tkfont, ttk

        import theme

        self.tk, self.ttk = tk, ttk
        self.root, self.on_apply, self.has_facecam = root, on_apply, has_facecam
        self.colors = theme.ensure(root)
        self.bundled = bundled_fonts(fonts_dir)
        try:
            self.installed = [name for name in tkfont.families(root) if name]
        except tk.TclError:
            self.installed = []
        self.word = 0
        self.pending = self.playing = None
        self.loading = False
        self.photo = None
        self.tile_photos = {}
        self.tiles = {}
        start = normalize(style)
        root.title("Clip-Stil")
        root.configure(background=self.colors["background"])
        root.bind("<Escape>", lambda _: self.cancel())
        root.protocol("WM_DELETE_WINDOW", self.cancel)

        outer = ttk.Frame(root, padding=(theme.PAD_WINDOW, 16, theme.PAD_WINDOW, 14))
        outer.pack(fill="both", expand=True)
        bar = ttk.Frame(outer)
        bar.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Button(bar, text="Auf Standard zurücksetzen", command=self.reset).pack(side="left")
        ttk.Button(bar, text="Übernehmen", command=self.apply).pack(side="right")
        ttk.Button(bar, text="Abbrechen", command=self.cancel).pack(side="right", padx=theme.PAD_BUTTON)
        right = ttk.Frame(outer, width=self.PREVIEW[0] + 2)
        right.pack(side="right", fill="y", padx=(20, 0))
        left = ttk.Frame(outer)
        left.pack(side="left", fill="both", expand=True)

        # Vorlagen
        ttk.Label(left, text="VORLAGEN", style="Brand.TLabel").pack(anchor="w")
        self.active_label = ttk.Label(left, style="Muted.TLabel")
        gallery = ttk.Frame(left)
        gallery.pack(anchor="w", pady=(4, 2))
        for index, (name, preset) in enumerate(PRESETS):
            cell = ttk.Frame(gallery)
            cell.grid(row=index // 4, column=index % 4, padx=(0, 6), pady=(0, 4), sticky="w")
            tile = tk.Canvas(cell, width=self.TILE[0], height=self.TILE[1], highlightthickness=2, borderwidth=0,
                             highlightbackground=self.colors["border"], highlightcolor=self.colors["foreground"],
                             background="#344052", takefocus=1, cursor="hand2")
            tile.pack()
            ttk.Label(cell, text=name, style="Small.Muted.TLabel").pack(anchor="w")
            for sequence in ("<Button-1>", "<space>", "<Return>"):
                tile.bind(sequence, lambda _, values=preset, widget=tile: (widget.focus_set(), self.load(values)))
            self.tiles[name] = tile
            self.draw_tile(name, preset)
        self.active_label.pack(anchor="w", pady=(0, 8))

        # Felder (kompakt, damit alles ohne Scrollen in das Fenster passt)
        ttk.Label(left, text="SCHRIFT UND FARBEN", style="Brand.TLabel").pack(anchor="w")
        fields = ttk.Frame(left)
        fields.pack(fill="x", pady=(2, 0))
        fields.columnconfigure(1, weight=1)
        self.vars = {
            "font": tk.StringVar(root), "font_size": tk.StringVar(root), "uppercase": tk.BooleanVar(root),
            "primary_color": tk.StringVar(root), "highlight_color": tk.StringVar(root),
            "outline_color": tk.StringVar(root), "outline": tk.StringVar(root), "box": tk.BooleanVar(root),
            "box_color": tk.StringVar(root), "box_opacity": tk.StringVar(root),
            "words_per_caption": tk.StringVar(root), "position": tk.StringVar(root),
        }
        self.rows, self.swatches, row = {}, {}, [0]

        def add(label, widget, key=None):
            name = ttk.Label(fields, text=label)
            name.grid(row=row[0], column=0, sticky="w", padx=(0, 14), pady=2)
            widget.grid(row=row[0], column=1, sticky="w", pady=2)
            row[0] += 1
            if key:
                self.rows[key] = (name, widget)

        def spin(holder, key, **options):
            low, high = LIMITS[key]
            return ttk.Spinbox(holder, from_=low, to=high, textvariable=self.vars[key], width=5,
                               style="Compact.TSpinbox", **options)

        def color(holder, key, title):
            swatch = tk.Label(holder, width=4, relief="solid", borderwidth=1, cursor="hand2", takefocus=0)
            swatch.pack(side="left", ipady=2)
            swatch.bind("<Button-1>", lambda _: self.pick(key, title))
            ttk.Label(holder, textvariable=self.vars[key], width=8, style="Muted.TLabel").pack(side="left", padx=6)
            ttk.Button(holder, text="Ändern …", style="Compact.TButton",
                       command=lambda: self.pick(key, title)).pack(side="left")
            self.swatches[key] = swatch
            return holder

        self.font_box = ttk.Combobox(fields, textvariable=self.vars["font"], state="readonly", width=34)
        add("Schriftart", self.font_box)
        self.font_hint = ttk.Label(fields, style="Warning.TLabel", wraplength=520, justify="left")
        self.font_hint.grid(row=row[0], column=0, columnspan=2, sticky="w")
        row[0] += 1
        size_row = ttk.Frame(fields)
        spin(size_row, "font_size").pack(side="left")
        ttk.Checkbutton(size_row, text="GROSSBUCHSTABEN", variable=self.vars["uppercase"]).pack(side="left", padx=14)
        add("Größe", size_row)
        add("Textfarbe", color(ttk.Frame(fields), "primary_color", "Textfarbe"))
        add("Farbe gesprochenes Wort", color(ttk.Frame(fields), "highlight_color", "Farbe des gesprochenen Worts"))
        add("Hintergrundbox", ttk.Checkbutton(fields, text="Text auf einer Box zeigen", variable=self.vars["box"]))
        add("Umrandungsfarbe", color(ttk.Frame(fields), "outline_color", "Umrandungsfarbe"), "outline_color")
        add("Umrandungsstärke", spin(fields, "outline"), "outline")
        add("Boxfarbe", color(ttk.Frame(fields), "box_color", "Boxfarbe"), "box_color")
        opacity = ttk.Frame(fields)
        spin(opacity, "box_opacity", increment=5).pack(side="left")
        ttk.Label(opacity, text="%", style="Muted.TLabel").pack(side="left", padx=6)
        add("Deckkraft der Box", opacity, "box_opacity")
        add("Wörter pro Zeile", spin(fields, "words_per_caption"))
        places = ttk.Frame(fields)
        for value in POSITIONS:
            ttk.Radiobutton(places, text=position_label(value, has_facecam), value=value,
                            variable=self.vars["position"]).pack(side="left", padx=(0, 10))
        add("Position", places)

        # Vorschau
        ttk.Label(right, text="VORSCHAU", style="Brand.TLabel").pack(anchor="w")
        self.canvas = tk.Canvas(right, width=self.PREVIEW[0], height=self.PREVIEW[1], highlightthickness=1,
                                highlightbackground=self.colors["border"], borderwidth=0, background="#0E1622")
        self.canvas.pack(pady=(4, 8))
        controls = ttk.Frame(right)
        controls.pack(fill="x")
        for column in range(3):
            controls.columnconfigure(column, weight=1, uniform="controls")
        for column, (text, command) in enumerate((("◀ Wort", lambda: self.step(-1)), ("Wort ▶", lambda: self.step(1)),
                                                  ("▶ Abspielen", self.toggle_play))):
            button = ttk.Button(controls, text=text, style="Compact.TButton", width=4, command=command)
            button.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 3, 0))
        self.play_button = button
        # Hinweis nur zeigen, wenn es etwas zu sagen gibt (sonst bleibt der Platz für die Vorschau frei).
        self.preview_hint = ttk.Label(right, style="Warning.TLabel", wraplength=self.PREVIEW[0], justify="left")

        self.load(start)
        for variable in self.vars.values():
            variable.trace_add("write", self.changed)

    # --- Werte
    def style(self, *, substitute=False):
        """Aktueller Stil aus den Feldern. Halb getippte Zahlen fallen auf den letzten gültigen Wert zurück."""
        raw = {}
        for key, variable in self.vars.items():
            try:
                raw[key] = variable.get()
            except self.tk.TclError:
                raw[key] = None
        for key, (low, high) in LIMITS.items():
            raw[key] = _number(raw[key], self.last[key], low, high)
        raw["font"] = effective_font(raw["font"]) if substitute else clean_font(raw["font"] or self.last["font"])
        result = normalize(raw)
        if substitute and result["box"]:
            result["outline"] = 0  # mit Box wird keine Umrandung gezeichnet
        return result

    def load(self, values):
        """Alle Felder auf einmal setzen (Vorlage, Standard oder Startwert)."""
        values = normalize(values)
        self.last = dict(values)
        self.loading = True
        try:
            self.font_box.configure(values=font_choices(self.bundled, self.installed, values["font"]))
            for key, variable in self.vars.items():
                variable.set(font_label(values["font"], self.bundled, self.installed) if key == "font"
                             else str(values[key]) if key in LIMITS else values[key])
        finally:
            self.loading = False
        self.refresh()

    def changed(self, *_):
        if self.loading:
            return
        if self.pending:
            self.root.after_cancel(self.pending)
        self.pending = self.root.after(120, self.refresh)

    def refresh(self):
        """Felder, Vorlagen-Markierung und Vorschau an den aktuellen Stil anpassen."""
        self.pending = None
        current = self.style()
        if not current["box"] and self.last["box"] and current["outline"] == 0:
            # Box abgeschaltet: ohne Umrandung wäre der Text kaum lesbar, also den Standard vorschlagen
            self.last = {**current, "outline": DEFAULTS["outline"]}
            self.loading = True
            self.vars["outline"].set(str(DEFAULTS["outline"]))
            self.loading = False
            current = self.style()
        self.last = dict(current)
        for key, swatch in self.swatches.items():
            swatch.configure(background=current[key])
        for key, visible in (("outline_color", not current["box"]), ("outline", not current["box"]),
                             ("box_color", current["box"]), ("box_opacity", current["box"])):
            for widget in self.rows[key]:
                widget.grid() if visible else widget.grid_remove()
        active = preset_name(current)
        for name, tile in self.tiles.items():
            tile.configure(highlightbackground=self.colors["accent"] if name == active else self.colors["border"])
        self.active_label.configure(text=f"Gewählt: {active or CUSTOM}")
        label = self.vars["font"].get()
        self.font_hint.configure(
            text=(f"„{clean_font(label)}“ ist auf diesem PC nicht installiert. Vorschau und Clips verwenden "
                  f"dafür {FALLBACK_FONT}.") if label.endswith(MISSING_SUFFIX) else "")
        self.draw()

    # --- Zeichnen
    def draw_tile(self, name, preset):
        tile = self.tiles[name]
        try:
            from PIL import ImageTk
            font = effective_font(font_label(preset["font"], self.bundled, self.installed))
            image = render_tile(preset, font_path=font_file(font, self.bundled), size=self.TILE)
            self.tile_photos[name] = ImageTk.PhotoImage(image, master=self.root)
            tile.create_image(2, 2, anchor="nw", image=self.tile_photos[name])
        except Exception:  # noqa: BLE001 - ohne Pillow bleibt eine schlichte Text-Kachel
            tile.create_text(self.TILE[0] // 2, self.TILE[1] // 2, text="Aa", fill=preset["primary_color"],
                             font=("Segoe UI", 16, "bold"))

    def draw(self):
        style = self.style(substitute=True)
        self.canvas.delete("all")
        try:
            from PIL import ImageTk
            image, fits = render_preview(style, self.word, has_facecam=self.has_facecam,
                                         font_path=font_file(style["font"], self.bundled))
            self.photo = ImageTk.PhotoImage(image, master=self.root)
            self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
            self.hint(None if fits else "Die Zeile ist breiter als das Bild. Wähle eine kleinere Schrift oder "
                      "weniger Wörter pro Zeile.")
        except Exception:  # noqa: BLE001 - Vorschau ist Komfort; die Einstellungen bleiben bedienbar
            self.photo = None
            words, highlight = caption_for_word(SAMPLE, style["words_per_caption"], self.word)
            self.canvas.create_text(self.PREVIEW[0] // 2, self.PREVIEW[1] // 2, width=self.PREVIEW[0] - 20,
                                    text=" ".join(display_text(w, style["uppercase"]) for w in words),
                                    fill=style["primary_color"], font=("Segoe UI", 16, "bold"))
            self.hint("Die Bildvorschau ist gerade nicht verfügbar.")

    def hint(self, text):
        if text:
            self.preview_hint.configure(text=text)
            if not self.preview_hint.winfo_manager():
                self.preview_hint.pack(anchor="w", pady=(6, 0))
        elif self.preview_hint.winfo_manager():
            self.preview_hint.pack_forget()

    # --- Bedienung
    def pick(self, key, title):
        from tkinter import colorchooser

        chosen = colorchooser.askcolor(color=self.style()[key], parent=self.root, title=title)[1]
        if chosen and valid_color(chosen):
            self.vars[key].set(chosen.upper())

    def step(self, delta):
        self.stop()
        self.word = (self.word + delta) % len(SAMPLE.split())
        self.draw()

    def toggle_play(self):
        if self.playing:
            return self.stop()
        self.word = 0
        self.draw()
        self.play_button.configure(text="■ Stopp")
        self.playing = self.root.after(350, self.tick)

    def tick(self):
        if self.word + 1 >= len(SAMPLE.split()):
            return self.stop()
        self.word += 1
        self.draw()
        self.playing = self.root.after(350, self.tick)

    def stop(self):
        if self.playing:
            self.root.after_cancel(self.playing)
        self.playing = None
        self.play_button.configure(text="▶ Abspielen")

    def reset(self):
        self.load(DEFAULTS)

    def close(self):
        self.stop()
        if self.pending:
            self.root.after_cancel(self.pending)
            self.pending = None
        self.root.destroy()

    def cancel(self):
        self.close()

    def apply(self):
        result = self.style(substitute=True)
        self.close()
        self.on_apply(result)
