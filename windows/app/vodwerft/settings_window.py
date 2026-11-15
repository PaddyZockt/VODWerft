"""Einstellungsfenster (Tk). Logik steckt in settings.py, Farben in theme.py."""
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import settings
import theme


def data_dir():
    """production-Ordner mit watcher.json (Argument oder neben der App)."""
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    return Path(__file__).resolve().parent / "production"


def style_for(root, colors):
    """Gemeinsames Design (theme.apply) verwenden; die "Settings.*"-Namen erben davon.

    Als Unterfenster des Dashboards gilt dessen Farbschema (eine Änderung wirkt nach dem Neustart),
    allein gestartet das gespeicherte."""
    colors = theme.current(root) or theme.apply(root, colors)
    root.configure(background=colors["background"])
    style = ttk.Style(root)
    style.configure("Settings.Muted.TLabel", foreground=colors["muted"], font=(theme.FONT, 9))
    return style


def open_in(parent, directory):
    """Einstellungen als Fenster des Hauptprogramms oeffnen (kein eigener Prozess, kein eigenes Taskleisten-Symbol)."""
    existing = getattr(parent, "_settings_window", None)
    if existing is not None and existing.winfo_exists():
        existing.lift()
        existing.focus_force()
        return existing
    window = tk.Toplevel(parent)
    window.transient(parent)
    SettingsWindow(window, directory)
    window.update_idletasks()
    x = parent.winfo_rootx() + max(0, (parent.winfo_width() - 620) // 2)
    y = parent.winfo_rooty() + max(0, (parent.winfo_height() - 460) // 3)
    window.geometry(f"620x460{x:+d}{y:+d}")
    parent._settings_window = window
    return window


class SettingsWindow:
    def __init__(self, root, directory):
        self.root, self.directory = root, Path(directory)
        self.values = settings.load(self.directory)
        self.vars = {}
        root.title("Einstellungen")
        if isinstance(root, tk.Tk):
            root.geometry("620x460")
        style_for(root, theme.palette(self.values["theme"]))
        self.notebook = ttk.Notebook(root, style="Settings.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=theme.PAD_BLOCK, pady=(theme.PAD_BLOCK, 6))
        self.notebook.enable_traversal()  # Strg+Tab wechselt die Seite
        for category in settings.CATEGORIES:
            self.page(category)
        bar = ttk.Frame(root, style="Settings.TFrame")
        bar.pack(fill="x", padx=theme.PAD_BLOCK, pady=(0, theme.PAD_BLOCK))
        ttk.Button(bar, text="Auf Standard zurücksetzen", style="Settings.TButton", command=self.reset).pack(side="left")
        ttk.Button(bar, text="Speichern (Strg+S)", style="Settings.TButton", command=self.save).pack(side="right")
        ttk.Button(bar, text="Abbrechen", style="Settings.TButton",
                   command=root.destroy).pack(side="right", padx=theme.PAD_BUTTON)
        self.note = ttk.Label(root, text="Änderungen gelten nach dem nächsten Start; Farben nach Neustart des Dashboards.",
                              style="Settings.Muted.TLabel")
        self.note.pack(fill="x", padx=theme.PAD_BLOCK, pady=(0, 10))
        root.bind("<Escape>", lambda _: root.destroy())
        root.bind("<Control-s>", lambda _: self.save())
        root.bind("<Control-S>", lambda _: self.save())

    def page(self, category):
        frame = ttk.Frame(self.notebook, style="Settings.TFrame", padding=theme.PAD_BLOCK + 2)
        self.notebook.add(frame, text=category)
        for option in settings.SCHEMA:
            if option.category != category:
                continue
            block = ttk.Frame(frame, style="Settings.TFrame")
            block.pack(fill="x", pady=(0, theme.PAD_BLOCK))
            if option.kind == "bool":
                var = tk.BooleanVar(value=self.values[option.key])
                ttk.Checkbutton(block, text=option.label, variable=var, style="Settings.TCheckbutton").pack(anchor="w")
            else:
                var = tk.StringVar(value=self.values[option.key])
                ttk.Label(block, text=option.label, style="Settings.TLabel").pack(anchor="w")
                for value, text in option.choices:
                    ttk.Radiobutton(block, text=text, value=value, variable=var, style="Settings.TRadiobutton").pack(anchor="w", padx=(14, 0))
            ttk.Label(block, text=option.help, style="Settings.Muted.TLabel", wraplength=540).pack(anchor="w", padx=(2, 0))
            self.vars[option.key] = var

    def reset(self):
        for key, var in self.vars.items():
            var.set(settings.BY_KEY[key].default)

    def save(self):
        try:
            settings.save(self.directory, {key: var.get() for key, var in self.vars.items()})
        except (OSError, ValueError, tk.TclError) as error:
            from tkinter import messagebox
            from dashboard_data import problem
            messagebox.showerror("Einstellungen", problem("Die Einstellungen konnten nicht gespeichert werden.",
                                                          error, "Einstellungen speichern"), parent=self.root)
            return
        self.root.destroy()


def main():
    root = tk.Tk()
    theme.set_icon(root)
    SettingsWindow(root, data_dir())
    root.mainloop()


if __name__ == "__main__":
    main()
