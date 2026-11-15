"""Farbpaletten (hell/dunkel) und gemeinsame Stile für alle Tk-Fenster.

`palette(name)` liefert die Farben, `apply(root, colors)` richtet damit alle ttk-Stile ein.
Dashboard, Einstellungen, Einrichtungsassistent und Unterfenster nutzen dieselbe Funktion,
damit Farben, Abstände und der Tastaturfokus überall gleich aussehen.
"""
import sys
from pathlib import Path

import brand

DARK = dict(background="#0B1A24", surface="#112533", border="#2B4556", foreground="#E8F1F5",
            muted="#9DB4C0", accent="#23889F", raised="#183041", selected="#12404F",
            pressed="#21404F", hover="#1C3646", scroll="#46687A", scroll_hover="#5C8296",
            nav_selected="#103545", nav_selected_text="#7FD3E8",
            warning="#F5A623", danger="#FF9C8F", success="#7ED9A8", check="#11596B",
            disabled="#6F8794", text_selection="#1E5568", danger_button="#8E2A1F",
            danger_button_hover="#B03A2C", danger_button_text="#FFFFFF")
LIGHT = dict(background="#F2F7F9", surface="#FFFFFF", border="#BDD0D8", foreground="#0B2A3C",
             muted="#4F6A77", accent="#11596B", raised="#E4EEF2", selected="#D3E8EE",
             pressed="#C6DAE1", hover="#DCE8ED", scroll="#9FB6C0", scroll_hover="#7F9AA7",
             nav_selected="#DCEDF2", nav_selected_text="#0B4556",
             warning="#8A5200", danger="#B3261E", success="#17703B", check="#11596B",
             disabled="#8FA3AD", text_selection="#B9DCE6", danger_button="#B3261E",
             danger_button_hover="#8F1E17", danger_button_text="#FFFFFF")

FONT = "Segoe UI"
# Einheitliche Abstände (Pixel): Fensterrand, Abstand zwischen Blöcken, zwischen Zeilen, zwischen Knöpfen.
PAD_WINDOW = 24
PAD_BLOCK = 14
PAD_ROW = 4
PAD_BUTTON = 6


def windows_uses_light():
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 1
    except OSError:
        return False


def palette(name):
    if name == "system":
        name = "hell" if windows_uses_light() else "dunkel"
    return dict(LIGHT if name == "hell" else DARK)


def is_light(colors):
    return colors["background"] == LIGHT["background"]


def current(widget):
    """Farben, die für das Fenster dieses Widgets schon eingerichtet wurden (oder None)."""
    try:
        top = widget.winfo_toplevel()
        while top is not None:
            found = getattr(top, "_theme_colors", None)
            if found:
                return found
            top = top.master.winfo_toplevel() if top.master is not None else None
    except Exception:  # noqa: BLE001 - nur eine Bequemlichkeitsabfrage, darf nie ein Fenster verhindern
        pass
    return None


def ensure(widget, name=brand.DEFAULT_THEME):
    """Vorhandene Farben verwenden oder (eigenständiges Fenster) jetzt einrichten."""
    return current(widget) or apply(widget.winfo_toplevel(), palette(name))


def apply(root, colors):
    """Richtet alle gemeinsamen ttk-Stile für `root` ein und gibt `colors` zurück."""
    from tkinter import ttk

    bg, surface, border = colors["background"], colors["surface"], colors["border"]
    fg, muted, accent = colors["foreground"], colors["muted"], colors["accent"]
    raised, disabled = colors["raised"], colors["disabled"]
    root.configure(background=bg)
    root._theme_colors = colors
    style = ttk.Style(root)
    if style.theme_use() != "clam":
        style.theme_use("clam")
    style.configure(".", background=bg, foreground=fg, font=(FONT, 10), focuscolor=accent)
    style.configure("TFrame", background=bg)
    style.configure("Surface.TFrame", background=surface)
    style.configure("TLabel", background=bg, foreground=fg, font=(FONT, 10))
    style.configure("Brand.TLabel", foreground=accent, font=(FONT, 10, "bold"))
    style.configure("Title.TLabel", font=(FONT, 25, "bold"))
    style.configure("Heading.TLabel", font=(FONT, 14, "bold"))
    style.configure("Section.TLabel", font=(FONT, 12, "bold"))
    style.configure("Muted.TLabel", foreground=muted)
    style.configure("Small.Muted.TLabel", foreground=muted, font=(FONT, 9))
    style.configure("Warning.TLabel", foreground=colors["warning"])
    style.configure("Danger.TLabel", foreground=colors["danger"])
    style.configure("Success.TLabel", foreground=colors["success"])
    style.configure("Unsaved.TLabel", foreground=colors["warning"], font=(FONT, 10, "bold"))
    style.configure("TLabelframe", background=bg, bordercolor=border, lightcolor=border, darkcolor=border)
    style.configure("TLabelframe.Label", background=bg, foreground=fg, font=(FONT, 10, "bold"))

    style.configure("TButton", background=surface, foreground=fg, bordercolor=border,
                    lightcolor=surface, darkcolor=surface, padding=(11, 7), focusthickness=1, focuscolor=accent)
    style.map("TButton", background=[("disabled", bg), ("pressed", colors["pressed"]), ("active", colors["hover"])],
              foreground=[("disabled", disabled)], bordercolor=[("focus", accent)],
              lightcolor=[("focus", accent)], darkcolor=[("focus", accent)])
    style.configure("Compact.TButton", padding=(8, 3))
    style.configure("Danger.TButton", background=colors["danger_button"], foreground=colors["danger_button_text"],
                    bordercolor=colors["danger_button"], lightcolor=colors["danger_button"],
                    darkcolor=colors["danger_button"])
    style.map("Danger.TButton",
              background=[("disabled", bg), ("pressed", colors["danger_button_hover"]),
                          ("active", colors["danger_button_hover"])],
              foreground=[("disabled", disabled)],
              bordercolor=[("disabled", border), ("focus", fg)],
              lightcolor=[("disabled", bg), ("focus", fg)], darkcolor=[("disabled", bg), ("focus", fg)])
    # Seitenleiste: flach, aber mit sichtbarem Rahmen, sobald der Knopf den Tastaturfokus hat.
    style.configure("Nav.TButton", background=bg, foreground=muted, borderwidth=1, bordercolor=bg,
                    lightcolor=bg, darkcolor=bg, padding=(11, 7))
    style.map("Nav.TButton", background=[("pressed", colors["pressed"]), ("active", colors["hover"])],
              foreground=[("active", fg)], bordercolor=[("focus", accent)],
              lightcolor=[("focus", accent)], darkcolor=[("focus", accent)])
    style.configure("Selected.Nav.TButton", background=colors["nav_selected"],
                    foreground=colors["nav_selected_text"], bordercolor=colors["nav_selected"],
                    lightcolor=colors["nav_selected"], darkcolor=colors["nav_selected"])
    style.map("Selected.Nav.TButton", background=[("active", colors["nav_selected"])],
              foreground=[("active", colors["nav_selected_text"])], bordercolor=[("focus", accent)],
              lightcolor=[("focus", accent)], darkcolor=[("focus", accent)])
    # Kalendertage: normal, ausgewählt (Akzentrahmen) und belegt (getönte Fläche).
    style.configure("Day.TButton", padding=(4, 6))
    style.configure("Day.Busy.TButton", padding=(4, 6), background=colors["nav_selected"],
                    foreground=colors["nav_selected_text"])
    style.map("Day.Busy.TButton", background=[("disabled", bg), ("active", colors["selected"])])
    style.configure("Day.Selected.TButton", padding=(4, 6), background=accent, foreground="#FFFFFF",
                    bordercolor=accent, lightcolor=accent, darkcolor=accent, font=(FONT, 10, "bold"))
    style.map("Day.Selected.TButton", background=[("active", accent), ("pressed", accent)],
              bordercolor=[("focus", fg)], lightcolor=[("focus", fg)], darkcolor=[("focus", fg)])

    style.configure("Treeview", background=surface, fieldbackground=surface, foreground=fg,
                    bordercolor=border, rowheight=30, font=(FONT, 10))
    style.configure("Treeview.Heading", background=raised, foreground=muted, lightcolor=raised,
                    darkcolor=raised, bordercolor=border, padding=(8, 7), font=(FONT, 9, "bold"))
    style.map("Treeview", background=[("selected", colors["selected"])], foreground=[("selected", fg)],
              bordercolor=[("focus", accent)])
    style.configure("Vertical.TScrollbar", background=colors["scroll"], troughcolor=raised,
                    bordercolor=border, lightcolor=colors["scroll"], darkcolor=colors["scroll"],
                    arrowcolor=fg, width=15)
    style.map("Vertical.TScrollbar", background=[("active", colors["scroll_hover"]), ("pressed", accent)])
    style.configure("Render.Horizontal.TProgressbar", background=accent, troughcolor=raised,
                    lightcolor=accent, darkcolor=accent, bordercolor=border)

    focus_border = dict(bordercolor=[("focus", accent)], lightcolor=[("focus", accent)],
                        darkcolor=[("focus", accent)])
    style.configure("TEntry", fieldbackground=surface, foreground=fg, padding=6, insertcolor=fg,
                    bordercolor=border, lightcolor=surface, darkcolor=surface)
    style.map("TEntry", fieldbackground=[("disabled", bg), ("readonly", bg)],
              foreground=[("disabled", disabled)], **focus_border)
    style.configure("TCombobox", fieldbackground=surface, foreground=fg, padding=6, background=surface,
                    arrowcolor=fg, bordercolor=border, lightcolor=surface, darkcolor=surface,
                    selectbackground=surface, selectforeground=fg)
    style.map("TCombobox", fieldbackground=[("disabled", bg), ("readonly", surface)],
              foreground=[("disabled", disabled), ("readonly", fg)],
              selectbackground=[("readonly", surface)], selectforeground=[("readonly", fg)],
              arrowcolor=[("disabled", disabled)], **focus_border)
    style.configure("TSpinbox", fieldbackground=surface, foreground=fg, background=surface, arrowcolor=fg,
                    bordercolor=border, lightcolor=surface, darkcolor=surface, insertcolor=fg, padding=6)
    style.map("TSpinbox", fieldbackground=[("disabled", bg)], foreground=[("disabled", disabled)],
              arrowcolor=[("disabled", disabled)], **focus_border)
    style.configure("Compact.TSpinbox", padding=(4, 2))
    for name in ("TCheckbutton", "TRadiobutton"):
        style.configure(name, background=bg, foreground=fg, indicatorbackground=surface,
                        indicatorforeground=fg, focuscolor=accent, focusthickness=1, padding=(3, 2))
        style.map(name, background=[("active", surface)],
                  foreground=[("disabled", disabled), ("active", fg)],
                  indicatorbackground=[("disabled", bg), ("selected", colors["check"])],
                  indicatorforeground=[("selected", "#FFFFFF")])
    style.configure("TNotebook", background=bg, bordercolor=border)
    style.configure("TNotebook.Tab", background=surface, foreground=muted, padding=(14, 6))
    style.map("TNotebook.Tab", background=[("selected", raised)], foreground=[("selected", fg)],
              bordercolor=[("focus", accent)])
    style.configure("TSeparator", background=border)

    # Aufklappliste der Comboboxen (ein klassisches Tk-Listenfeld, daher über die Optionsdatenbank).
    for option, value in (("background", surface), ("foreground", fg), ("selectBackground", colors["selected"]),
                          ("selectForeground", fg), ("font", (FONT, 10)), ("borderWidth", 0),
                          ("highlightThickness", 0)):
        root.option_add(f"*TCombobox*Listbox.{option}", value)
    return colors


def style_text(widget, colors):
    """Klassisches Tk-Textfeld passend zum Design einfärben (ttk-Stile greifen dort nicht)."""
    widget.configure(background=colors["surface"], foreground=colors["foreground"],
                     insertbackground=colors["foreground"], selectbackground=colors["text_selection"],
                     selectforeground=colors["foreground"], borderwidth=0, highlightthickness=1,
                     highlightbackground=colors["border"], highlightcolor=colors["accent"])


def close_on_escape(window):
    """Unterfenster mit Esc schließen."""
    window.bind("<Escape>", lambda _: window.destroy())


def set_icon(window) -> None:
    """Programm-Symbol statt des Tk-Standardsymbols (Feder) setzen; fehlt die Datei, bleibt alles wie es ist."""
    folder = Path(__file__).resolve().parent
    for ico in sorted(folder.glob("*.ico")):
        try:
            window.iconbitmap(default=str(ico))
        except Exception:  # noqa: BLE001 - ein fehlendes Symbol darf kein Fenster verhindern
            continue
        return
