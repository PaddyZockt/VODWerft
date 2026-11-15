"""Thumbnail-Stil: Vorgaben und Prüfung (ohne Bildbibliotheken, damit Profile und Oberfläche ihn laden können)."""
import re
from pathlib import Path

RED = "#E50914"
DEFAULT_FONT = "ariblk.ttf"
# Vorgaben des Thumbnail-Stils; sie stehen nicht fest im Code, sondern kommen aus dem Spielprofil
# ("thumbnail_theme"). Fehlende oder ungültige Werte fallen auf diese Vorgaben zurück.
THEME_DEFAULTS = {"accent": RED, "text_color": "#FFFFFF", "font": DEFAULT_FONT, "show_bar": True,
                  "background": "#0A0A0A"}
THEME_KEYS = tuple(THEME_DEFAULTS) + ("duration_badge",)
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def sanitize_theme(theme):
    """Prüft einen Thumbnail-Stil und gibt nur gültige Werte zurück (alles andere fällt weg)."""
    clean = {}
    if not isinstance(theme, dict):
        return clean
    for key in ("accent", "text_color", "background"):
        value = theme.get(key)
        if isinstance(value, str) and _HEX.match(value.strip()):
            clean[key] = value.strip().upper()
    font = theme.get("font")
    if (isinstance(font, str) and font.strip() and not any(c in font for c in "/\\:")
            and Path(font.strip()).suffix.lower() in (".ttf", ".otf")):
        clean["font"] = font.strip()
    for key in ("show_bar", "duration_badge"):
        if isinstance(theme.get(key), bool):
            clean[key] = theme[key]
    return clean


def resolve_theme(theme):
    return {**THEME_DEFAULTS, **sanitize_theme(theme)}
