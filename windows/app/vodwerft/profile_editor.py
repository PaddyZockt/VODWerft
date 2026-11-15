"""Tk view for editing and duplicating Nightcut game profiles."""
import os
import subprocess
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import yaml

import caption_style_editor
import thumbnail_style_editor
import game_library
import theme
from dashboard_data import problem
from game_profiles import profile_paths, read_settings, render_settings, save_profile


DAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
MODES = {"Folgen nach Länge": "by_length", "Eine Folge pro Aufnahme": "per_recording"}
STYLES = {"Projekt und Folgenzahl / Mission": "numbered", "Nur Projektname": "project"}
SAVED_HINT = "Änderungen gelten für neue Aufnahmen. Bereits gestartete Aufträge behalten ihre Einstellungen."


def build(parent, main, on_save):
    colors = theme.ensure(parent)
    frame = ttk.Frame(parent, padding=(theme.PAD_WINDOW, 18))
    header = ttk.Frame(frame)
    header.pack(fill="x", pady=(0, 10))
    ttk.Label(header, text="Spielprofile", style="Section.TLabel").pack(side="left")
    unsaved = ttk.Label(header, text="", style="Unsaved.TLabel")
    unsaved.pack(side="left", padx=14)
    selector = ttk.Combobox(frame, state="readonly")
    selector.pack(fill="x", pady=(0, 10))
    hint = ttk.Label(frame, style="Muted.TLabel", wraplength=850, justify="left")
    actions = ttk.Frame(frame)
    hint.pack(side="bottom", anchor="w", fill="x")
    actions.pack(side="bottom", fill="x", pady=(theme.PAD_BLOCK, 8))

    # Die Felder liegen in einem scrollbaren Bereich, damit auf kleinen Bildschirmen nichts abgeschnitten wird.
    area = ttk.Frame(frame)
    area.pack(fill="both", expand=True)
    canvas = tk.Canvas(area, background=colors["background"], highlightthickness=0, borderwidth=0)
    scroll = ttk.Scrollbar(area, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    fields = ttk.Frame(canvas)
    inner = canvas.create_window(0, 0, anchor="nw", window=fields)
    fields.columnconfigure(1, weight=1)

    def resize(_=None):
        canvas.configure(scrollregion=(0, 0, fields.winfo_reqwidth(), fields.winfo_reqheight()))
        canvas.itemconfigure(inner, width=max(canvas.winfo_width(), 1))
        needed = fields.winfo_reqheight() > canvas.winfo_height() + 1
        if needed and not scroll.winfo_ismapped():
            scroll.pack(side="right", fill="y", before=canvas)
        elif not needed and scroll.winfo_ismapped():
            scroll.pack_forget()
            canvas.yview_moveto(0)

    def wheel(event):
        if fields.winfo_reqheight() <= canvas.winfo_height():
            return
        if isinstance(event.widget, (ttk.Combobox, ttk.Spinbox)):
            return  # dort ändert das Mausrad den Wert
        step = -1 if (getattr(event, "num", 0) == 4 or getattr(event, "delta", 0) > 0) else 1
        canvas.yview_scroll(step * 2, "units")

    fields.bind("<Configure>", resize)
    canvas.bind("<Configure>", resize)
    for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        canvas.bind(sequence, wheel)
        fields.bind_class(f"ProfileScroll{id(fields)}", sequence, wheel)

    mode = tk.StringVar(frame)
    minutes = tk.StringVar(frame)
    audio = tk.StringVar(frame)
    split = tk.BooleanVar(frame)
    style = tk.StringVar(frame)
    manual = tk.BooleanVar(frame)
    approval = tk.BooleanVar(frame)
    mission_start = tk.BooleanVar(frame)
    days = [tk.BooleanVar(frame) for _ in DAYS]
    new_name = tk.StringVar(frame)
    paths = []
    state = {"index": -1, "saved": None, "loading": False, "caption": None, "caption_changed": False,
             "thumb": {}, "thumb_changed": False, "clips": False, "facecam": True, "fonts_dir": None}

    row_number = [0]
    shown = {}

    def section(title, key=None):
        label = ttk.Label(fields, text=title, style="Brand.TLabel")
        label.grid(row=row_number[0], column=0, columnspan=2, sticky="w",
                   pady=(theme.PAD_BLOCK if row_number[0] else 0, 2))
        row_number[0] += 1
        if key:
            shown.setdefault(key, []).append(label)

    def add(label, widget, key=None, help_text=None):
        row = row_number[0]
        row_number[0] += 1
        name = ttk.Label(fields, text=label)
        name.grid(row=row, column=0, sticky="nw" if help_text else "w", padx=(0, 16), pady=theme.PAD_ROW)
        widget.grid(row=row, column=1, sticky="w", pady=theme.PAD_ROW)
        if key:
            shown.setdefault(key, []).extend((name, widget))
        if help_text:
            note = ttk.Label(fields, text=help_text, style="Small.Muted.TLabel", wraplength=560, justify="left")
            note.grid(row=row_number[0], column=1, sticky="w", pady=(0, theme.PAD_ROW))
            row_number[0] += 1
            if key:
                shown[key].append(note)

    def show_only_relevant(*_):
        """Nur Felder zeigen, die zur aktuellen Auswahl passen (z. B. Minuten nur bei 'Folgen nach Länge')."""
        for key, visible in (("minutes", MODES.get(mode.get()) == "by_length"), ("days", not manual.get()),
                             ("clips", state["clips"])):
            for widget in shown[key]:
                widget.grid() if visible else widget.grid_remove()

    inbox = ttk.Label(fields, style="Muted.TLabel", wraplength=650)
    section("AUFNAHME")
    add("Eingangsordner", inbox)
    add("Tonspur für Spracherkennung", ttk.Spinbox(fields, from_=1, to=16, textvariable=audio, width=8),
        help_text="Die Tonspur deiner Aufnahme, auf der dein Mikrofon zu hören ist. Nimmst du nur eine Spur auf, "
                  "bleibt hier 1 stehen. Mit „Tonprobe erstellen“ kannst du die Auswahl anhören.")
    add("Getrennte Tonspuren (OBS)",
        ttk.Checkbutton(fields, text="Mikrofon, Chat und Spiel getrennt nutzen", variable=split),
        help_text="Nur einschalten, wenn OBS Mikrofon, Sprachchat und Spielton auf eigene Spuren aufnimmt.")
    section("SCHNITT")
    add("Schnitt", ttk.Combobox(fields, textvariable=mode, values=list(MODES), state="readonly", width=34))
    add("Minuten pro Folge", ttk.Spinbox(fields, from_=5, to=180, textvariable=minutes, width=8), "minutes")
    add("Thumbnail", ttk.Combobox(fields, textvariable=style, values=list(STYLES), state="readonly", width=34))
    thumb_row = ttk.Frame(fields)
    thumb_info = ttk.Label(thumb_row, style="Muted.TLabel")
    thumb_info.pack(side="left", padx=(0, 10))
    thumb_button = ttk.Button(thumb_row, text="Thumbnail-Stil …")
    thumb_button.pack(side="left")
    add("Thumbnail-Stil", thumb_row)
    section("HOCHKANT-CLIPS", "clips")
    caption_row = ttk.Frame(fields)
    caption_swatch = tk.Label(caption_row, width=4, relief="solid", borderwidth=1, cursor="hand2")
    caption_swatch.pack(side="left", ipady=2)
    caption_info = ttk.Label(caption_row, style="Muted.TLabel")
    caption_info.pack(side="left", padx=10)
    caption_button = ttk.Button(caption_row, text="Clip-Stil …")
    caption_button.pack(side="left")
    add("Untertitel", caption_row, "clips")
    section("VERÖFFENTLICHUNG")
    add("Termine", ttk.Checkbutton(fields, text="Im Kalender selbst auswählen", variable=manual))
    day_bar = ttk.Frame(fields)
    for label, value in zip(DAYS, days):
        ttk.Checkbutton(day_bar, text=label, variable=value).pack(side="left", padx=(0, 6))
    add("Automatisch um 19 Uhr (Berlin)", day_bar, "days")
    section("FREIGABE")
    add("Upload-Freigabe", ttk.Checkbutton(fields, text="Jede Folge vor dem Upload prüfen", variable=approval))
    mission_control = ttk.Checkbutton(fields, text="Missionsbeginn vor dem Schnitt markieren", variable=mission_start)
    add("Missionen", mission_control)
    section("NEUES SPIEL AUS DIESEM PROFIL")
    clone_row = ttk.Frame(fields)
    ttk.Combobox(clone_row, textvariable=new_name, values=game_library.names(), width=34).pack(side="left")
    clone_button = ttk.Button(clone_row, text="Als neues Spiel duplizieren")
    clone_button.pack(side="left", padx=(theme.PAD_BUTTON + 2, 0))
    add("Name oder aus Bibliothek wählen", clone_row,
        help_text="Legt ein neues Spiel mit eigenem Eingangsordner an und übernimmt die Einstellungen von oben.")
    mode.trace_add("write", show_only_relevant)
    manual.trace_add("write", show_only_relevant)

    def selected_path():
        return paths[selector.current()]

    def snapshot():
        return (mode.get(), minutes.get().strip(), audio.get().strip(), split.get(), style.get(), manual.get(),
                approval.get(), mission_start.get(), tuple(day.get() for day in days))

    def dirty():
        return state["saved"] is not None and (snapshot() != state["saved"] or state["caption_changed"]
                                               or state["thumb_changed"])

    def mark(*_):
        if not state["loading"]:
            unsaved.configure(text="● Ungespeicherte Änderungen" if dirty() else "")

    def show_caption():
        current = state["caption"] or caption_style_editor.DEFAULTS
        caption_swatch.configure(background=caption_style_editor.normalize(current)["highlight_color"])
        caption_info.configure(text=caption_style_editor.summary(current))

    def edit_caption():
        def apply(chosen):
            state["caption"] = chosen
            state["caption_changed"] = True
            show_caption()
            mark()

        caption_style_editor.open_in(frame, state["caption"] or caption_style_editor.DEFAULTS, apply,
                                     has_facecam=state["facecam"], fonts_dir=state["fonts_dir"])

    def show_thumb():
        thumb_info.configure(text=thumbnail_style_editor.summary(state["thumb"]))

    def edit_thumb():
        def apply(chosen):
            state["thumb"] = chosen
            state["thumb_changed"] = True
            show_thumb()
            mark()

        try:
            series = read_settings(selected_path()).get("series")
        except (OSError, ValueError, KeyError, IndexError, TypeError, yaml.YAMLError):
            series = None
        thumbnail_style_editor.open_in(frame, state["thumb"], apply, series=series, style=STYLES[style.get()])

    thumb_button.configure(command=edit_thumb)
    caption_button.configure(command=edit_caption)
    caption_swatch.bind("<Button-1>", lambda _: edit_caption())

    def load(event=None):
        state["loading"] = True
        try:
            config = read_settings(selected_path())
            render = render_settings(config)
            inbox.configure(text=config["input"])
            mode.set(next(label for label, value in MODES.items() if value == render.get("episodes", "by_length")))
            minutes.set(str(render.get("episode_minutes", 25)))
            audio.set(str(config.get("audio_track", 0) + 1))
            split.set(bool(config.get("obs_split_audio")))
            style.set(next(label for label, value in STYLES.items() if value == config.get("thumbnail_style", "numbered")))
            manual.set(bool(config.get("manual_release")))
            approval.set(bool(config.get("require_approval")))
            mission_start.set(bool(config.get("require_mission_start")))
            mission_control.configure(state="normal" if config.get("mission_export") else "disabled")
            for index, day in enumerate(days):
                day.set(index in config.get("publish_weekdays", (0, 3)))
            new_name.set("")
            # Der Abschnitt HOCHKANT-CLIPS gilt nur für Profile, die Clips erstellen.
            state["clips"] = bool(config.get("clips_config"))
            state["caption"] = caption_style_editor.profile_style(config)
            state["caption_changed"] = False
            state["thumb"] = thumbnail_style_editor.profile_theme(config)
            state["thumb_changed"] = False
            show_thumb()
            if state["clips"]:
                state["facecam"], state["fonts_dir"] = caption_style_editor.clip_settings(config)
            show_caption()
            hint.configure(text=SAVED_HINT, style="Muted.TLabel")
            state["saved"] = snapshot()
        except (OSError, ValueError, KeyError, IndexError, StopIteration, TypeError, yaml.YAMLError) as error:
            state["saved"] = None
            hint.configure(text=problem("Das Profil konnte nicht gelesen werden.", error, "Spielprofil lesen"),
                           style="Danger.TLabel")
        finally:
            state["loading"] = False
        state["index"] = selector.current()
        show_only_relevant()
        unsaved.configure(text="")
        canvas.yview_moveto(0)

    def reload(pick=None):
        paths[:] = profile_paths(main)
        selector.configure(values=[read_settings(path)["series"] for path in paths])
        selector.current(paths.index(pick) if pick in paths else 0)
        load()

    def number(variable, label, low, high):
        try:
            value = int(variable.get().strip())
        except ValueError:
            value = None
        if value is None or not low <= value <= high:
            raise ValueError(f"Bitte bei „{label}“ eine ganze Zahl zwischen {low} und {high} eintragen.")
        return value

    def save(clone=False):
        """Speichert das Profil. Gibt True zurück, wenn es geklappt hat."""
        name = new_name.get() if clone else None
        try:
            if clone and not name.strip():
                raise ValueError("Bitte den Namen des neuen Spiels eingeben.")
            length = number(minutes, "Minuten pro Folge", 5, 180) if MODES[mode.get()] == "by_length" else None
            if length is None:  # Feld ausgeblendet: den zuletzt gespeicherten Wert behalten
                try:
                    length = min(180, max(5, int(minutes.get())))
                except ValueError:
                    length = 25
            path = caption_style_editor.save_profile_with_style(
                save_profile, main, selected_path(),
                state["caption"] if state["clips"] and state["caption_changed"] else None,
                minutes=length, mode=MODES[mode.get()],
                audio_track=number(audio, "Tonspur für Spracherkennung", 1, 16) - 1, split=split.get(),
                style=STYLES[style.get()], manual=manual.get(),
                weekdays=[index for index, value in enumerate(days) if value.get()],
                approval=approval.get(), mission_start=mission_start.get(), clone_name=name,
                thumbnail_theme=state["thumb"] if state["thumb_changed"] else None)
            reload(path)
            on_save()
            hint.configure(text="Profil gespeichert. Die Automatik übernimmt es von selbst.", style="Success.TLabel")
            return True
        except ValueError as error:  # verständliche Hinweise zur Eingabe
            messagebox.showerror("Spielprofil", str(error), parent=frame)
        except (OSError, KeyError, TypeError, yaml.YAMLError) as error:
            messagebox.showerror("Spielprofil", problem("Das Profil konnte nicht gespeichert werden.", error,
                                                        "Spielprofil speichern"), parent=frame)
        return False

    def switch(event=None):
        """Anderes Profil gewählt: bei ungespeicherten Änderungen erst nachfragen."""
        if selector.current() != state["index"] and dirty():
            target = selector.current()
            selector.current(state["index"])
            answer = messagebox.askyesnocancel(
                "Ungespeicherte Änderungen",
                f"Die Änderungen an „{selector.get()}“ sind noch nicht gespeichert.\n\nJetzt speichern?",
                parent=frame)
            if answer is None or (answer and not save()):
                return
            selector.current(target)
        load()

    def open_inbox():
        try:
            os.startfile(read_settings(selected_path())["input"])
        except (OSError, ValueError, KeyError, AttributeError) as error:
            hint.configure(text=problem("Der Eingangsordner ist gerade nicht erreichbar.", error, "Eingang öffnen"),
                           style="Danger.TLabel")

    def sample():
        source = filedialog.askopenfilename(parent=frame, title="Aufnahme für eine lokale 12-Sekunden-Tonprobe",
                                            filetypes=[("Aufnahmen", "*.mp4 *.mkv *.mov")])
        if not source:
            return
        try:
            track = 1 if split.get() else number(audio, "Tonspur für Spracherkennung", 1, 16) - 1
            ffmpeg = Path(read_settings(main)["ffmpeg_directory"]) / "ffmpeg.exe"
            preview_dir = Path(read_settings(main)["work"]) / "profile-previews"
            preview_dir.mkdir(exist_ok=True)
            output = Path(tempfile.mkdtemp(prefix="tonprobe-", dir=preview_dir)) / "Tonprobe.m4a"
            task = subprocess.Popen([str(ffmpeg), "-v", "error", "-nostdin", "-i", source, "-t", "12",
                                     "-map", f"0:a:{track}", "-c:a", "aac", str(output)],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            hint.configure(text=f"Tonprobe für Spur {track + 1} wird erstellt …", style="Muted.TLabel")
        except ValueError as error:
            hint.configure(text=str(error), style="Danger.TLabel")
            return
        except (OSError, KeyError) as error:
            hint.configure(text=problem("Die Tonprobe konnte nicht gestartet werden.", error, "Tonprobe"),
                           style="Danger.TLabel")
            return

        def poll_sample():
            code = task.poll()
            if code is None:
                frame.after(300, poll_sample)
            elif code:
                hint.configure(text="Tonprobe fehlgeschlagen. Bitte prüfen, ob die Aufnahme diese Spur enthält.",
                               style="Danger.TLabel")
            else:
                try:
                    os.startfile(output)
                    hint.configure(text="Tonprobe erstellt. Sie bleibt im lokalen Vorschauordner.", style="Success.TLabel")
                except (OSError, AttributeError):
                    hint.configure(text=f"Tonprobe gespeichert unter {output}", style="Muted.TLabel")

        poll_sample()

    def save_shortcut(event=None):
        if frame.winfo_ismapped() and event is not None and event.widget.winfo_toplevel() is frame.winfo_toplevel():
            save()
            return "break"

    clone_button.configure(command=lambda: save(True))
    ttk.Button(actions, text="Speichern (Strg+S)", command=save).pack(side="left", padx=(0, theme.PAD_BUTTON))
    for label, command in (("Eingang öffnen", open_inbox), ("Tonprobe erstellen", sample)):
        ttk.Button(actions, text=label, command=command).pack(side="left", padx=(0, theme.PAD_BUTTON))
    for variable in (mode, minutes, audio, split, style, manual, approval, mission_start, *days):
        variable.trace_add("write", mark)
    selector.bind("<<ComboboxSelected>>", switch)
    frame.winfo_toplevel().bind("<Control-s>", save_shortcut, add="+")
    frame.winfo_toplevel().bind("<Control-S>", save_shortcut, add="+")
    reload()

    def enable_wheel(widget):
        widget.bindtags((f"ProfileScroll{id(fields)}", *widget.bindtags()))
        for child in widget.winfo_children():
            enable_wheel(child)

    enable_wheel(fields)
    frame.is_dirty = dirty
    frame.save = save
    return frame
