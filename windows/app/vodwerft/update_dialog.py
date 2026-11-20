"""Fenster vor dem Update: Was ist neu (Patch Notes) und die Frage, ob installiert werden soll."""
import tkinter as tk
from tkinter import ttk

NOTE_FALLBACK = "Zu diesem Update liegen keine Hinweise vor (oder sie konnten nicht geladen werden)."
INFO = ("Das Dashboard schließt sich dabei. Ein neues Fenster zeigt den Fortschritt (Windows fragt nach "
        "Administratorrechten). Läuft gerade ein Schnitt, passiert nichts. Danach öffnest du das Dashboard wieder "
        "über das Tray-Symbol.")


def build(parent, label, installed, notes):
    """Baut das Fenster und gibt (Fenster, Ergebnis-Dict) zurück; getrennt von `ask`, damit es testbar ist."""
    result = {"install": False}
    window = tk.Toplevel(parent)
    window.title("Update installieren")
    window.transient(parent)
    window.minsize(520, 360)
    frame = ttk.Frame(window, padding=16)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=f"Update {label} ist verfügbar", style="Brand.TLabel").pack(anchor="w")
    ttk.Label(frame, text=f"Installiert: {installed or 'unbekannt'}", style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
    ttk.Label(frame, text="Was ist neu").pack(anchor="w")
    box = ttk.Frame(frame)
    box.pack(fill="both", expand=True, pady=(4, 10))
    text = tk.Text(box, wrap="word", height=14, width=64, relief="flat", borderwidth=1)
    scroll = ttk.Scrollbar(box, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=scroll.set)
    text.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    text.insert("1.0", notes.strip() or NOTE_FALLBACK)
    text.configure(state="disabled")  # nur lesen (Markieren und Kopieren geht weiter)
    ttk.Label(frame, text=INFO, style="Small.Muted.TLabel", wraplength=500, justify="left").pack(anchor="w")
    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(12, 0))

    def choose(value):
        result["install"] = value
        window.destroy()
    ttk.Button(buttons, text="Jetzt installieren", command=lambda: choose(True)).pack(side="right")
    ttk.Button(buttons, text="Abbrechen", command=lambda: choose(False)).pack(side="right", padx=(0, 8))
    window.protocol("WM_DELETE_WINDOW", lambda: choose(False))
    window.bind("<Escape>", lambda _event: choose(False))
    return window, result


def ask(parent, label, installed, notes):
    """Zeigt das Fenster und wartet. True = installieren."""
    window, result = build(parent, label, installed, notes)
    window.grab_set()
    window.focus_set()
    parent.wait_window(window)
    return result["install"]
