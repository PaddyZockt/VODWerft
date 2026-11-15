"""Manuell hochladen: fertige Folgen mit Titel, Beschreibung und Vorschaubild bereitstellen.

Für alle, die kein eigenes Google-Projekt einrichten wollen: VODWerft bereitet alles vor, der Upload
selbst geschieht von Hand in YouTube Studio. Das Fenster zeigt die fertigen Folgen, kopiert Titel und
Beschreibung in die Zwischenablage, öffnet den Ordner mit Video und Vorschaubild und YouTube Studio.
Mit „Als hochgeladen markieren“ wandert die Folge in den Ordner „Fertig“ und verschwindet aus der Liste.

Aufruf: manual_upload.py [production-Ordner]   (Standard: %LOCALAPPDATA%\\VODWerft\\production)
"""
import json
import os
import shutil
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

MEDIA = (".mp4", ".mkv", ".mov")
IMAGES = (".jpg", ".png")
UPLOAD_URL = "https://www.youtube.com/upload"


def read_incoming(production):
    """Ordner mit den fertigen Folgen (.upload) und der Ordner „Fertig“ aus der Einrichtung."""
    config = json.loads((Path(production) / "watcher.json").read_text(encoding="utf-8-sig"))
    share = Path(config["upload_incoming"]).parent
    return share / ".upload", share / "Fertig"


def schedule_text(publish_at):
    """Geplanter Veröffentlichungszeitpunkt in Ortszeit, sonst leer."""
    if not publish_at:
        return ""
    try:
        stamp = datetime.fromisoformat(str(publish_at).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone()
    return stamp.strftime("%d.%m.%Y %H:%M")


def list_bundles(incoming):
    """Fertige Folgen: eine Folge zählt erst, wenn die Markierung .ready da ist. Neueste zuletzt."""
    incoming = Path(incoming)
    bundles = []
    for marker in sorted(incoming.glob("*.ready")):
        stem = marker.stem
        meta_path = incoming / f"{stem}.json"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if not isinstance(meta, dict):
            continue
        video = next((incoming / f"{stem}{ext}" for ext in MEDIA if (incoming / f"{stem}{ext}").is_file()), None)
        if video is None:
            continue
        thumb = next((incoming / f"{stem}{ext}" for ext in IMAGES if (incoming / f"{stem}{ext}").is_file()), None)
        tags = meta.get("tags") or []
        bundles.append({
            "stem": stem, "video": video, "thumbnail": thumb,
            "title": str(meta.get("title", stem)), "description": str(meta.get("description", "")),
            "tags": ", ".join(str(tag) for tag in tags) if isinstance(tags, list) else str(tags),
            "schedule": schedule_text(meta.get("publishAt")),
        })
    return bundles


def mark_done(bundle, incoming, done):
    """Alle Dateien der Folge nach „Fertig“ verschieben, die Markierung zuletzt entfernen. Rückgabe: Zielordner."""
    incoming, done = Path(incoming), Path(done)
    done.mkdir(parents=True, exist_ok=True)
    for path in sorted(incoming.glob(bundle["stem"] + ".*"), key=lambda item: item.suffix == ".ready"):
        target = done / path.name
        counter = 1
        while target.exists():
            target = done / f"{path.stem}-{counter}{path.suffix}"
            counter += 1
        shutil.move(str(path), str(target))
    return done


def reveal(path):
    """Datei im Windows-Explorer markieren (sonst den Ordner öffnen)."""
    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        webbrowser.open(Path(path).parent.as_uri())


def main():
    import tkinter as tk
    from tkinter import messagebox, ttk

    import theme

    production = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "VODWerft" / "production"
    root = tk.Tk()
    root.title("Manuell hochladen")
    root.geometry("860x640")
    theme.set_icon(root)
    colors = theme.ensure(root)
    root.configure(background=colors["background"])
    try:
        incoming, done = read_incoming(production)
    except (OSError, ValueError, KeyError):
        messagebox.showerror("Manuell hochladen", f"Die Einrichtung wurde nicht gefunden:\n{production}\n\nBitte zuerst die Einrichtung abschließen.")
        return
    state = {"bundles": []}

    ttk.Label(root, text="Manuell hochladen", style="Heading.TLabel").pack(anchor="w", padx=16, pady=(14, 0))
    ttk.Label(root, style="Muted.TLabel", justify="left", wraplength=800, text=(
        "1. Folge links wählen.  2. „YouTube Studio öffnen“ und das Video aus dem Ordner hineinziehen.  "
        "3. Titel und Beschreibung hier kopieren und dort einfügen.  4. Vorschaubild unter „Miniaturansicht“ hochladen.  "
        "5. Bei „Sichtbarkeit“ den Termin einstellen (falls hier einer steht).  6. Danach „Als hochgeladen markieren“.")
    ).pack(anchor="w", padx=16, pady=(2, 8))

    body = ttk.Frame(root)
    body.pack(fill="both", expand=True, padx=16)
    listbox = tk.Listbox(body, width=34, exportselection=False, activestyle="none", borderwidth=0, highlightthickness=1)
    listbox.pack(side="left", fill="y")
    listbox.configure(background=colors["surface"], foreground=colors["foreground"], selectbackground=colors["accent"],
                      selectforeground="#FFFFFF", borderwidth=0, highlightthickness=1,
                      highlightbackground=colors["border"], highlightcolor=colors["accent"])
    side = ttk.Frame(body)
    side.pack(side="left", fill="both", expand=True, padx=(14, 0))
    title_var, tags_var, when_var, info_var = tk.StringVar(), tk.StringVar(), tk.StringVar(), tk.StringVar()

    def clip(text):
        root.clipboard_clear()
        root.clipboard_append(text)
        info_var.set("Kopiert. Jetzt in YouTube Studio einfügen (Strg+V).")

    def row(label, var, text_for_copy):
        ttk.Label(side, text=label).pack(anchor="w", pady=(8, 0))
        line = ttk.Frame(side)
        line.pack(fill="x")
        ttk.Entry(line, textvariable=var, state="readonly").pack(side="left", fill="x", expand=True)
        ttk.Button(line, text="Kopieren", command=lambda: clip(text_for_copy())).pack(side="left", padx=(6, 0))

    row("Titel", title_var, lambda: title_var.get())
    ttk.Label(side, text="Beschreibung").pack(anchor="w", pady=(8, 0))
    desc = tk.Text(side, height=11, wrap="word", borderwidth=0, highlightthickness=1)
    desc.pack(fill="both", expand=True)
    theme.style_text(desc, colors)
    ttk.Button(side, text="Beschreibung kopieren", command=lambda: clip(desc.get("1.0", "end").strip())).pack(anchor="w", pady=(4, 0))
    row("Tags", tags_var, lambda: tags_var.get())
    ttk.Label(side, textvariable=when_var, style="Muted.TLabel").pack(anchor="w", pady=(8, 0))

    def current():
        selection = listbox.curselection()
        return state["bundles"][selection[0]] if selection else None

    def show(_event=None):
        bundle = current()
        title_var.set(bundle["title"] if bundle else "")
        tags_var.set(bundle["tags"] if bundle else "")
        when_var.set((f"Geplanter Termin: {bundle['schedule']} (in YouTube Studio unter Sichtbarkeit → Planen einstellen)"
                      if bundle and bundle["schedule"] else ""))
        desc.configure(state="normal")
        desc.delete("1.0", "end")
        desc.insert("1.0", bundle["description"] if bundle else "")

    def refresh():
        selected = current()
        state["bundles"] = list_bundles(incoming)
        listbox.delete(0, "end")
        for bundle in state["bundles"]:
            listbox.insert("end", bundle["title"])
        if state["bundles"]:
            index = next((i for i, b in enumerate(state["bundles"]) if selected and b["stem"] == selected["stem"]), 0)
            listbox.selection_set(index)
        info_var.set("Noch keine fertige Folge. Sobald eine Folge freigegeben und fertig ist, erscheint sie hier." if not state["bundles"] else "")
        show()

    def open_folder():
        bundle = current()
        if bundle:
            reveal(bundle["video"])

    def open_thumbnail():
        bundle = current()
        if bundle and bundle["thumbnail"]:
            reveal(bundle["thumbnail"])
        elif bundle:
            info_var.set("Zu dieser Folge gibt es kein Vorschaubild.")

    def finish():
        bundle = current()
        if bundle and messagebox.askyesno("Als hochgeladen markieren",
                                          f"„{bundle['title']}“ nach „Fertig“ verschieben?\nDie Folge verschwindet dann aus der Liste.", parent=root):
            try:
                mark_done(bundle, incoming, done)
            except OSError as error:
                messagebox.showerror("Manuell hochladen", f"Verschieben nicht möglich:\n{error}", parent=root)
            refresh()

    buttons = ttk.Frame(root)
    buttons.pack(fill="x", padx=16, pady=10)
    ttk.Button(buttons, text="YouTube Studio öffnen", command=lambda: webbrowser.open(UPLOAD_URL)).pack(side="left")
    ttk.Button(buttons, text="Video im Ordner zeigen", command=open_folder).pack(side="left", padx=6)
    ttk.Button(buttons, text="Vorschaubild zeigen", command=open_thumbnail).pack(side="left")
    ttk.Button(buttons, text="Aktualisieren", command=refresh).pack(side="left", padx=6)
    ttk.Button(buttons, text="Als hochgeladen markieren", command=finish).pack(side="right")
    ttk.Label(root, textvariable=info_var, style="Muted.TLabel").pack(anchor="w", padx=16, pady=(0, 10))
    listbox.bind("<<ListboxSelect>>", show)
    theme.close_on_escape(root)
    refresh()
    root.mainloop()


if __name__ == "__main__":
    main()
