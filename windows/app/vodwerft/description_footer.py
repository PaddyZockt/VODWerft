"""Append the channel's shared footer to a game's video description."""
from pathlib import Path
from string import Template

from game_library import developer as library_developer

FOOTER = Path(__file__).with_name("description-footer.txt")


def with_footer(description, game, developer=None):
    developer = library_developer(game, developer)
    if developer is None:
        return description
    footer = Template(FOOTER.read_text(encoding="utf-8-sig").strip()).substitute(game=game, developer=developer)
    body = description.replace("\r\n", "\n").replace(footer, "").strip()
    available = 5000 - len(footer.encode("utf-8")) - 2
    if available < 0:
        raise ValueError("The shared description footer is too long")
    body = body.encode("utf-8")[:available].decode("utf-8", errors="ignore").rstrip()
    return f"{body}\n\n{footer}" if body else footer
