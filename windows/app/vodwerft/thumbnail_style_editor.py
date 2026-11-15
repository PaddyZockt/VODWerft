"""Kleines Fenster für den Thumbnail-Stil eines Spielprofils (Farben, Schrift, Dauer-Badge).

Die Werte stehen im Profil unter "thumbnail_theme"; Prüfung und Vorgaben liegen in thumbnail_theme.py.
Oben zeigt eine Live-Vorschau (Beispielbild mit der echten Thumbnail-Gestaltung), wie das Ergebnis aussieht."""
from thumbnail_theme import THEME_DEFAULTS, sanitize_theme

COLOR_FIELDS = (("accent", "Akzentfarbe (Balken, Hervorhebung)"),
                ("text_color", "Textfarbe"),
                ("background", "Hintergrund / Abdunklung"))


def profile_theme(config):
    """Gespeicherter Thumbnail-Stil eines Profils (nur gültige Werte); leer, wenn keiner gewählt wurde."""
    stored = config.get("thumbnail_theme") if isinstance(config, dict) else None
    return sanitize_theme(stored) if isinstance(stored, dict) else {}


def complete(theme):
    """Stil mit allen Feldern für die Anzeige: Vorgaben plus gespeicherte Werte, Dauer-Badge standardmäßig an."""
    return {**THEME_DEFAULTS, "duration_badge": True, **sanitize_theme(theme)}


def summary(theme):
    """Eine Zeile für den Profil-Editor."""
    if not sanitize_theme(theme):
        return "Standard"
    shown = complete(theme)
    return f"{shown['accent']} · Text {shown['text_color']} · {shown['font']}"


def to_profile(values):
    """Aus den Fensterwerten den Stil fürs Profil bauen; was dem Standard entspricht, wird nicht gespeichert."""
    clean = sanitize_theme(values)
    return {key: value for key, value in clean.items()
            if value != {**THEME_DEFAULTS, "duration_badge": True}.get(key)}


def preview_image(values, series=None, style="numbered", width=480):
    """Vorschaubild (Pillow) für die aktuellen Fensterwerte; None, wenn es nicht erzeugt werden kann."""
    try:
        from thumbnail import render_preview
        return render_preview(sanitize_theme(values), series, 1, style=style, width=width)
    except Exception:  # noqa: BLE001 - die Vorschau ist Komfort; die Einstellungen bleiben bedienbar
        return None


def open_in(parent, theme, on_apply, series=None, style="numbered"):
    """Fenster öffnen. `on_apply(dict)` bekommt den Stil fürs Profil ({} = Standard).
    `series` (Spielname) und `style` ("numbered"/"project") bestimmen den Text der Vorschau."""
    import tkinter as tk
    from tkinter import colorchooser, ttk

    top = parent.winfo_toplevel()
    window = tk.Toplevel(top)
    window.title("Thumbnail-Stil")
    window.transient(top)
    window.resizable(False, False)
    values = complete(theme)
    body = ttk.Frame(window, padding=16)
    body.grid()
    swatches, texts = {}, {}
    width = 480
    ttk.Label(body, text="VORSCHAU").grid(row=0, column=0, columnspan=3, sticky="w")
    canvas = tk.Canvas(body, width=width, height=round(width * 9 / 16), highlightthickness=1, borderwidth=0,
                       background="#0E1622")
    canvas.grid(row=1, column=0, columnspan=3, pady=(4, 4))
    note = ttk.Label(body, text="Beispielbild. Im echten Thumbnail steht dein Spielbild aus der Folge.",
                     wraplength=width)
    note.grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 10))
    state = {"photo": None}

    def current():
        return {**values, "font": font.get(), "show_bar": bar.get(), "duration_badge": badge.get()}

    def refresh(*_):
        image = preview_image(current(), series, style, width)
        canvas.delete("all")
        if image is None:
            canvas.create_text(width // 2, round(width * 9 / 32), fill="#B8C4D6", text="Vorschau nicht verfügbar")
            return
        from PIL import ImageTk
        state["photo"] = ImageTk.PhotoImage(image, master=window)
        canvas.create_image(0, 0, anchor="nw", image=state["photo"])

    def pick(key, title):
        chosen = colorchooser.askcolor(color=values[key], parent=window, title=title)[1]
        if chosen:
            values[key] = chosen.upper()
            swatches[key].configure(background=values[key])
            texts[key].configure(text=values[key])
            refresh()

    for row, (key, label) in enumerate(COLOR_FIELDS, start=3):
        ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 16))
        swatch = tk.Label(body, width=6, relief="solid", borderwidth=1, cursor="hand2", background=values[key])
        swatch.grid(row=row, column=1, sticky="w")
        swatch.bind("<Button-1>", lambda _e, k=key, t=label: pick(k, t))
        text = ttk.Label(body, text=values[key])
        text.grid(row=row, column=2, sticky="w", padx=10)
        swatches[key], texts[key] = swatch, text
    font = tk.StringVar(window, values["font"])
    ttk.Label(body, text="Schrift (Dateiname)").grid(row=6, column=0, sticky="w", pady=4)
    ttk.Entry(body, textvariable=font, width=24).grid(row=6, column=1, columnspan=2, sticky="w")
    ttk.Label(body, text="Dateiname einer installierten Schrift, z. B. impact.ttf. Fehlt sie, gilt die Standardschrift.",
              wraplength=420).grid(row=7, column=0, columnspan=3, sticky="w", pady=(0, 6))
    bar = tk.BooleanVar(window, values["show_bar"])
    badge = tk.BooleanVar(window, values["duration_badge"])
    ttk.Checkbutton(body, text="Farbbalken neben dem Titel zeigen", variable=bar).grid(row=8, column=0, columnspan=3, sticky="w")
    ttk.Checkbutton(body, text="Dauer-Badge zeigen (Entwürfe mit Kurzvideos)", variable=badge).grid(
        row=9, column=0, columnspan=3, sticky="w")
    for variable in (font, bar, badge):
        variable.trace_add("write", refresh)

    def apply():
        on_apply(to_profile(current()))
        window.destroy()

    def reset():
        on_apply({})
        window.destroy()

    buttons = ttk.Frame(body)
    buttons.grid(row=10, column=0, columnspan=3, sticky="e", pady=(12, 0))
    ttk.Button(buttons, text="Auf Standard", command=reset).pack(side="left", padx=4)
    ttk.Button(buttons, text="Abbrechen", command=window.destroy).pack(side="left", padx=4)
    ttk.Button(buttons, text="Übernehmen", command=apply).pack(side="left", padx=4)
    refresh()
    window.grab_set()
    return window
