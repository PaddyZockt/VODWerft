"""Local operator view for the Nightcut pipeline.

Daten lesen, zusammenfassen und gruppieren steht in dashboard_data.py (ohne Tk, mit Tests);
hier steht nur die Anzeige.
"""
import os
import re
import sqlite3
import subprocess
import sys
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from tkinter import filedialog, messagebox, simpledialog, ttk

import settings as user_settings
import single_instance
import settings_window
import theme
from version import read as program_version, nightcut_version
from release_calendar import build as build_calendar, youtube_dates
from release_slots import berlin_slot
from game_profiles import load_profiles
from profile_editor import build as build_profiles
from job_cleanup import request as request_cleanup
from clip_retry import request_retry
from episode_approval import approval_path, approve, draft_path, mission_seconds
from job_history import history, retry_render
from retention import write
from dashboard_data import (  # noqa: F401 - einige Namen bleiben hier für ältere Aufrufer erreichbar
    CUTS, EMPTY_TEXT, GROUPS, UPLOAD, UPLOAD_REASON, cleanup_view, correction, counts_text, describe,
    done_by_game, episode_number, episode_updates, file_activity, grouped, parse_local_date, percent,
    phase_engine, preferred, problem, progress_detail, read_json, set_log_file, snapshot, timestamp)

if getattr(sys, "frozen", False):
    # Gebaute exe: liegt im Datenordner, die Programmdateien sind darin gebuendelt.
    ROOT = Path(sys.executable).resolve().parents[1]
    ICON = ROOT / "vodwerft.ico"
else:
    # Start als Skript (z. B. VODWerft unter Programme): die Daten liegen immer in %LOCALAPPDATA%,
    # nie im Programmordner (der ist ohne Administratorrechte nicht beschreibbar).
    ROOT = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "VODWerft"
    ICON = Path(__file__).resolve().parent / "vodwerft.ico"
CONTROL = ROOT / "production"  # Sperr- und Marker-Dateien fuer Einzelinstanz (siehe single_instance.py)
NOTICE_SECONDS = 8
GROUP = "grp:"


def main():
    # Nur ein Fenster: laeuft das Dashboard schon, bitten wir es, sich zu zeigen, und beenden uns.
    instance = single_instance.acquire_dashboard(CONTROL)
    if instance is None:
        single_instance.request_show(CONTROL)
        return
    single_instance.clear_flags(CONTROL)  # Anforderungen aus frueheren Laeufen verwerfen
    root = tk.Tk()
    root.title("VODWerft")
    # Startgroesse so, dass die Spielerprofil-Seite ohne Ziehen passt (1280 x 1030), auf kleinen Bildschirmen begrenzt.
    width = min(1280, root.winfo_screenwidth() - 48)
    height = min(1030, root.winfo_screenheight() - 100)
    left = max(0, (root.winfo_screenwidth() - width) // 2)
    top = max(0, (root.winfo_screenheight() - height) // 3)
    root.geometry(f"{width}x{height}{left:+d}{top:+d}")
    root.minsize(min(900, width), min(640, height))
    try:
        root.iconbitmap(default=str(ICON))  # gilt auch fuer alle Unterfenster (Thumbnail-Stil, Clip-Stil, Einstellungen)
    except tk.TclError:
        pass  # Symbol fehlt (z. B. Programm nicht am Installationsort gestartet): Fenster trotzdem oeffnen
    set_log_file(ROOT / "production")
    colors = theme.apply(root, theme.palette(user_settings.load(ROOT / "production")["theme"]))
    surface, border = colors["surface"], colors["border"]
    foreground, muted, accent = colors["foreground"], colors["muted"], colors["accent"]
    profile_file = ROOT / "production" / "watcher.json"
    profiles = load_profiles(profile_file)
    config = profiles[0]
    nav = ttk.Frame(root, padding=(theme.PAD_WINDOW, 12, theme.PAD_WINDOW, 0))
    nav.pack(fill="x")
    pages = ttk.Frame(root)
    pages.pack(fill="both", expand=True)
    frame = ttk.Frame(pages, padding=(theme.PAD_WINDOW, 18))
    buttons = ttk.Frame(frame)
    buttons.pack(side="bottom", fill="x")
    cleanup_bar = ttk.Frame(frame)
    cleanup_bar.pack(side="bottom", fill="x", pady=(0, 7))
    notices = Path(config["upload_incoming"]).parent / ".status"
    calendar_page = build_calendar(pages, profiles, config.get("blocked_utc_slots", []),
                                   notices / "youtube-calendar.json")

    def reload_profiles():
        profiles[:] = load_profiles(profile_file)

    profiles_page = build_profiles(pages, profile_file, reload_profiles)
    current_page = [None]

    def leave_profiles_ok():
        """Ungespeicherte Profiländerungen: vor dem Verlassen nachfragen. True = weitermachen."""
        dirty = getattr(profiles_page, "is_dirty", None)
        if current_page[0] is not profiles_page or not dirty or not dirty():
            return True
        answer = messagebox.askyesnocancel(
            "Ungespeicherte Änderungen",
            "Die Änderungen am Spielprofil sind noch nicht gespeichert.\n\nJetzt speichern?", parent=root)
        if answer is None:
            return False
        return profiles_page.save() if answer else True

    def change_page(page):
        if page is current_page[0]:
            return
        if not leave_profiles_ok():
            return
        for panel, button in ((frame, jobs_button), (calendar_page, calendar_button),
                              (profiles_page, profiles_button)):
            panel.pack_forget()
            button.configure(style="Selected.Nav.TButton" if panel is page else "Nav.TButton")
        page.pack(fill="both", expand=True)
        current_page[0] = page

    jobs_button = ttk.Button(nav, text="Aufträge", style="Nav.TButton", command=lambda: change_page(frame))
    jobs_button.pack(side="left", padx=(0, theme.PAD_BUTTON))
    calendar_button = ttk.Button(nav, text="Kalender", style="Nav.TButton",
                                 command=lambda: change_page(calendar_page))
    calendar_button.pack(side="left", padx=(0, theme.PAD_BUTTON))
    profiles_button = ttk.Button(nav, text="Spielprofile", style="Nav.TButton",
                                 command=lambda: change_page(profiles_page))
    profiles_button.pack(side="left")
    ttk.Label(nav, text="Alt+1 / 2 / 3 wechselt die Seite · F5 aktualisiert",
              style="Small.Muted.TLabel").pack(side="left", padx=(14, 0))

    def open_settings():  # als Fenster im Hauptprogramm, nicht als eigener Prozess
        settings_window.open_in(root, ROOT / "production")

    ttk.Button(nav, text="Einstellungen", command=open_settings).pack(side="right", padx=(0, theme.PAD_BUTTON))
    if config.get("status_page_url"):  # optional: Link auf eine eigene Statusseite (z. B. fuers Handy)
        ttk.Button(nav, text="Handy-Status öffnen",
                   command=lambda: webbrowser.open(config["status_page_url"])).pack(side="right")
    change_page(frame)
    ttk.Label(frame, text="VODWERFT  /  VIDEO-PIPELINE", style="Brand.TLabel").pack(anchor="w")
    ttk.Label(frame, text=("Nightcut " + nightcut_version()).strip(), style="Title.TLabel").pack(anchor="w")
    server_line = ttk.Label(frame, text="", style="Muted.TLabel")
    server_line.pack(anchor="w", pady=(2, 0))
    server_colors = {"ok": colors["success"], "direct": muted, "unknown": colors["warning"],
                     "mismatch": colors["warning"], "stale": colors["danger"], "offline": colors["danger"]}

    def show_server():
        data = read_json(ROOT / "production" / "server-status.json", {})
        if 0 <= time.time() - data.get("updated", 0) < 60:
            symbol = "●" if data.get("state") in ("ok", "direct") else "▲"
            message = data.get("text", "")
            if data.get("state") == "ok" and data.get("server"):
                message = f"Server verbunden · Serverversion {data['server']} passt zum Programm {program_version()}"
            server_line.configure(text=f"{symbol} {message}", foreground=server_colors.get(data.get("state"), muted))
        else:
            server_line.configure(text="▲ Statusdienst antwortet nicht", foreground=server_colors["stale"])
        root.after(5000, show_server)

    show_server()
    summary = ttk.Label(frame, text="Aufträge werden geladen …", style="Muted.TLabel", wraplength=1000)
    summary.pack(anchor="w", pady=(0, 4))
    # Meldungszeile: kurze Hinweise nach einer Aktion, verschwinden nach einigen Sekunden von selbst.
    notice = ttk.Label(frame, text="", style="Muted.TLabel", wraplength=1000)
    notice.pack(anchor="w", pady=(0, 10))
    notice_timer = [None]

    def notify(message, kind="info"):
        style = {"error": "Danger.TLabel", "warning": "Warning.TLabel", "success": "Success.TLabel"}.get(
            kind, "TLabel")
        notice.configure(text=("▲ " if kind in ("error", "warning") else "● ") + message, style=style)
        if notice_timer[0]:
            root.after_cancel(notice_timer[0])
        notice_timer[0] = root.after(NOTICE_SECONDS * 1000, lambda: notice.configure(text=""))

    jobs_header = ttk.Frame(frame)
    jobs_header.pack(fill="x", pady=(0, 6))
    ttk.Label(jobs_header, text="Aufträge", style="Section.TLabel").pack(side="left")
    listing = ttk.Frame(frame)
    listing.pack(fill="x")
    table = ttk.Treeview(listing, columns=("game", "status"), show="tree headings", height=8, selectmode="browse")
    table.heading("#0", text="AUFNAHME", anchor="w")
    table.column("#0", width=520, minwidth=160, stretch=True)
    for key, name, column_width in (("game", "PROFIL", 140), ("status", "STATUS", 340)):
        table.heading(key, text=name, anchor="w")
        table.column(key, width=column_width, minwidth=85)
    table.pack(side="left", fill="x", expand=True)
    table_scroll = ttk.Scrollbar(listing, orient="vertical", command=table.yview)
    table_scroll.pack(side="right", fill="y")
    table.configure(yscrollcommand=table_scroll.set)
    table.tag_configure("working", foreground=colors["warning"])
    table.tag_configure("review", foreground=colors["danger"])
    table.tag_configure("complete", foreground=colors["success"])
    table.tag_configure("group", background=colors["raised"], foreground=foreground, font=(theme.FONT, 10, "bold"))
    table.tag_configure("empty", foreground=muted)

    def toggle_group(event):
        """Ein Klick auf eine Gruppenzeile klappt sie auf oder zu; die gewaehlte Aufnahme bleibt erhalten."""
        item = table.identify_row(event.y)
        if item.startswith(GROUP):
            table.item(item, open=not table.item(item, "open"))
            return "break"

    table.bind("<Button-1>", toggle_group, add="+")
    ttk.Label(frame, text="Schnitt & Veröffentlichung", style="Section.TLabel").pack(anchor="w", pady=(15, 6))
    progress = ttk.Progressbar(frame, style="Render.Horizontal.TProgressbar", maximum=100)
    detail = ttk.Frame(frame)
    detail.pack(fill="both", expand=True, pady=(0, 12))
    text = tk.Text(detail, wrap="word", height=10, padx=14, pady=10, font=(theme.FONT, 11), spacing1=2)
    theme.style_text(text, colors)
    text.pack(side="left", fill="both", expand=True)
    text.tag_configure("title", font=(theme.FONT, 12, "bold"), spacing3=2)
    text.tag_configure("heading", foreground=accent, font=(theme.FONT, 9, "bold"), spacing1=12, spacing3=3)
    text.tag_configure("quiet", foreground=muted, font=(theme.FONT, 10))
    detail_scroll = ttk.Scrollbar(detail, orient="vertical", command=text.yview)
    detail_scroll.pack(side="right", fill="y")
    text.configure(yscrollcommand=detail_scroll.set)
    text.configure(state="disabled")
    rows, results = {}, Queue()
    samples = {}
    waiting = False
    shown = None
    needs_row = []  # Knöpfe, die nur mit ausgewähltem Auftrag sinnvoll sind

    def selected():
        keys = table.selection()
        return rows.get(keys[0]) if keys else None

    def profile_of(row):
        return next(item for item in profiles if Path(item["work"]) == row.work)

    def retry_selected():
        row = selected()
        if not row or not row.clips_retry:
            return
        try:
            queued = request_retry(row.work, row.key)
        except (OSError, sqlite3.Error) as error:
            messagebox.showerror("Hochkant-Clips", problem("Der neue Versuch konnte nicht angefordert werden.",
                                                           error, "Clips erneut versuchen"), parent=root)
            return
        retry_button.configure(state="disabled")
        if queued:
            notify("Neuer Versuch für die Hochkant-Clips angefordert.", "success")
        refresh()

    retry_button = ttk.Button(jobs_header, text="Hochkant-Clips erneut versuchen", command=retry_selected)
    retry_button.pack(side="right")

    def choose_cleanup(mode):
        row = selected()
        if not row:
            return
        if not row.cleanup_supported or row.cleanup_mode == "done" or (mode == "now" and not row.cleanup_verified):
            return
        if mode != "manual" and not messagebox.askyesno(
            "Exportdateien bereinigen",
            f"{row.name}\n\n"
            "Fertig gerenderte Folgen, Thumbnails und temporäre Exportdateien dieses Auftrags "
            "werden nach bestätigter YouTube-Prüfung dauerhaft vom PC und vom Server entfernt. "
            "Originalaufnahme, exportierte Hochkant-Clips und Uploadbelege bleiben erhalten.\n\n"
            + ("Automatische Bereinigung für diesen Auftrag aktivieren?" if mode == "auto"
               else "Exportdateien jetzt zur Bereinigung freigeben?"),
            parent=root, icon="warning",
        ):
            return
        try:
            request_cleanup(notices, row.key, mode)
        except (OSError, ValueError) as error:
            messagebox.showerror("Bereinigung", problem("Die Auswahl konnte nicht gespeichert werden.", error,
                                                        "Bereinigung"), parent=root)
            return
        notify({"auto": "Automatische Bereinigung eingeschaltet.", "manual": "Automatische Bereinigung ausgeschaltet.",
                "now": "Bereinigung angefordert."}[mode], "success")
        refresh()

    cleanup_status = ttk.Label(cleanup_bar, style="Muted.TLabel")
    cleanup_status.pack(side="left", padx=(0, 10))
    cleanup_auto = ttk.Button(cleanup_bar, text="Automatisch bereinigen", command=lambda: choose_cleanup("auto"))
    cleanup_auto.pack(side="right", padx=(theme.PAD_BUTTON, 0))
    cleanup_now = ttk.Button(cleanup_bar, text="Jetzt löschen", style="Danger.TButton",
                             command=lambda: choose_cleanup("now"))
    cleanup_now.pack(side="right", padx=(theme.PAD_BUTTON, 0))

    def show(event=None):
        nonlocal shown
        row = selected()
        if row and row.awaiting_mission:
            mission_button.pack(side="right", padx=(0, theme.PAD_BUTTON))
        else:
            mission_button.pack_forget()
        retry_button.configure(state="normal" if row and row.clips_retry else "disabled")
        for button in needs_row:
            button.configure(state="normal" if row else "disabled")
        view = cleanup_view(row)
        cleanup_status.configure(text=view["label"])
        cleanup_auto.configure(state="normal" if view["auto_enabled"] else "disabled", text=view["auto_text"],
                               command=lambda: choose_cleanup(view["auto_mode"]))
        cleanup_now.configure(state="normal" if view["now_enabled"] else "disabled")
        if row:
            content = describe(row)
        elif rows:
            content = "Wähle einen Auftrag aus der Liste."
        else:
            content = EMPTY_TEXT
        value = percent(row.detail) if row else None
        if value is not None:
            progress.configure(value=value)
            if not progress.winfo_manager():
                progress.pack(fill="x", pady=(0, 8), before=detail)
        elif progress.winfo_manager():
            progress.pack_forget()
        state = (row.key if row else None, content)
        if state == shown:
            return
        scroll = text.yview()[0] if shown and state[0] == shown[0] else 0
        shown = state
        text.configure(state="normal")
        text.delete("1.0", "end")
        text.insert("1.0", content)
        for tag in text.tag_names():
            if tag.startswith("preview-"):
                text.tag_delete(tag)
        for number, line in enumerate(content.splitlines(), 1):
            if row and number == 1:
                text.tag_add("title", f"{number}.0", f"{number}.end")
            elif line.startswith("Werkzeug dieser Phase") or not row:
                text.tag_add("quiet", f"{number}.0", f"{number}.end")
            elif line == "FOLGEN" or line.startswith("SCHNITTPLAN"):
                head = len(line.split(" · ")[0])
                text.tag_add("heading", f"{number}.0", f"{number}.{head}")
                text.tag_add("quiet", f"{number}.{head}", f"{number}.end")
        if row:
            for number, line in enumerate(content.splitlines(), 1):
                match = re.match(r"(\d+):(\d\d):(\d\d) bis ", line)
                if match:
                    hours, minutes, seconds = map(int, match.groups())
                    start = hours * 3600 + minutes * 60 + seconds
                    tag = f"preview-{number}"
                    text.tag_add(tag, f"{number}.0", f"{number}.{match.end() - 5}")
                    text.tag_configure(tag, foreground=colors["nav_selected_text"], underline=True)
                    text.tag_bind(tag, "<Enter>", lambda _: text.configure(cursor="hand2"))
                    text.tag_bind(tag, "<Leave>", lambda _: text.configure(cursor=""))
                    text.tag_bind(tag, "<Button-1>", lambda _, source=row.source, start=start: preview(source, start))
        text.yview_moveto(scroll)
        text.configure(state="disabled")

    def preview(source, start):
        player = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "VideoLAN/VLC/vlc.exe"
        try:
            if not source.is_file():
                raise FileNotFoundError(source)
            subprocess.Popen([str(player), "--no-one-instance", f"--start-time={start}", str(source)])
        except OSError:
            notify("VLC oder die Originaldatei ist derzeit nicht erreichbar.", "warning")

    def mark_mission():
        row = selected()
        if not row or not row.awaiting_mission:
            return
        value = simpledialog.askstring("Missionsbeginn", "Ab welcher Zeit beginnt die Mission? Beispiel 05:50",
                                       parent=root)
        if value is None:
            return
        try:
            seconds = mission_seconds(value.strip())  # ValueError mit verständlichem Satz
            source = row.source
            probe = Path(profile_of(row)["ffmpeg_directory"]) / "ffprobe.exe"
            length = subprocess.check_output(
                [str(probe), "-v", "error", "-show_entries", "format=duration", "-of",
                 "default=noprint_wrappers=1:nokey=1", str(source)], text=True, timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                total = float(length.strip())
            except ValueError:
                raise OSError(f"ffprobe lieferte keine Länge: {length!r}") from None
            if seconds >= total:
                raise ValueError("Der Missionsbeginn muss vor dem Ende der Aufnahme liegen.")
            marker = source.with_suffix(".start.txt")
            if marker.exists():
                raise ValueError("Für die Aufnahme ist bereits ein Startpunkt gesetzt.")
            write(marker, seconds)
            notify("Missionsbeginn gespeichert. Die Automatik schneidet ab dieser Stelle.", "success")
            refresh()
        except ValueError as error:
            messagebox.showerror("Missionsbeginn", str(error), parent=root)
        except (OSError, StopIteration, subprocess.SubprocessError) as error:
            messagebox.showerror("Missionsbeginn", problem(
                "Die Länge der Aufnahme konnte nicht ermittelt werden. Ist die Originaldatei erreichbar?",
                error, "Missionsbeginn"), parent=root)

    def subwindow(title, w, h, x=None, y=None):
        window = tk.Toplevel(root)
        window.title(title)
        w, h = min(w, width), min(h, height)
        if x is None:
            x = root.winfo_rootx() + max(0, (root.winfo_width() - w) // 2)
            y = root.winfo_rooty() + max(0, (root.winfo_height() - h) // 2)
        window.geometry(f"{w}x{h}{x:+d}{y:+d}")
        window.configure(background=colors["background"])
        window.transient(root)
        theme.close_on_escape(window)
        return window

    def show_history():
        row = selected()
        if not row:
            return
        window = subwindow("Auftragsverlauf · " + row.name, 790, 460)
        frame = ttk.Frame(window, padding=16)
        frame.pack(fill="both", expand=True)
        columns = ("time", "step", "detail")
        listing = ttk.Treeview(frame, columns=columns, show="headings")
        for column, label, size in zip(columns, ("ZEIT", "SCHRITT", "DETAIL"), (135, 205, 390)):
            listing.heading(column, text=label, anchor="w")
            listing.column(column, width=size, stretch=column == "detail")
        scroll = ttk.Scrollbar(frame, command=listing.yview)
        listing.configure(yscrollcommand=scroll.set)
        buttons = ttk.Frame(frame)
        buttons.pack(side="bottom", fill="x", pady=(8, 0))
        listing.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        try:
            events = history(row.work, row.key)
        except (OSError, sqlite3.Error) as error:
            problem("Verlauf nicht lesbar.", error, "Auftragsverlauf")
            events = []
        for notice_ in row.updates:
            number = notice_.get("job_id", "").rsplit("-ep", 1)[-1]
            for event in notice_.get("events", []):
                reason = event.get("reason")
                events.append((event.get("time", 0), UPLOAD.get(event.get("status"), "Upload"),
                               f"Folge {number} · {UPLOAD_REASON.get(reason, reason) or 'YouTube'}"))
        for stamp, step, detail_text in sorted(events, reverse=True):
            listing.insert("", "end", values=(timestamp(stamp), step, detail_text))
        if not events:
            listing.insert("", "end", values=("", row.detail, "Für diesen Auftrag liegt kein älterer Verlauf vor."))

        def again():
            try:
                retry_render(row.work, row.key)
            except ValueError as error:
                messagebox.showerror("Export erneut versuchen", str(error), parent=window)
                return
            except (OSError, sqlite3.Error) as error:
                messagebox.showerror("Export erneut versuchen", problem(
                    "Der Export konnte nicht neu angefordert werden.", error, "Export erneut versuchen"), parent=window)
                return
            window.destroy()
            notify("Export wird erneut versucht.", "success")
            refresh()

        # Immer sichtbar; ausgegraut, solange kein Export auf eine Prüfung wartet.
        retry_button = ttk.Button(buttons, text="Export erneut versuchen", command=again)
        retry_button.pack(side="left")
        if not row.needs_render_check:
            retry_button.state(["disabled"])
        ttk.Button(buttons, text="Schließen (Esc)", command=window.destroy).pack(side="right")
        listing.focus_set()

    def preview_episode():
        from PIL import Image, ImageTk

        row = selected()
        if not row:
            return
        exports = sorted(row.folder.glob(f"{row.key}-ep*.json"), key=lambda path: episode_number(path) or 0)
        if row.review:
            exports = [video.with_suffix(".json") for video in sorted(row.review[0].glob("*.mp4"))
                       if video.with_suffix(".json").is_file()] or exports
        if not exports:
            notify("Für diesen Auftrag liegt noch kein Folgenentwurf vor.", "warning")
            return
        preview_width, preview_height = min(800, width), min(750, height)
        x = max(0, min(root.winfo_rootx(), root.winfo_screenwidth() - preview_width - 20))
        y = max(0, min(root.winfo_rooty(), root.winfo_screenheight() - preview_height - 65))
        window = subwindow("Folgenvorschau · " + row.name, preview_width, preview_height, x, y)
        panel = ttk.Frame(window, padding=18)
        panel.pack(fill="both", expand=True)
        chooser = ttk.Combobox(panel, state="readonly", values=[
            f"Folge {episode_number(path):02d}" if episode_number(path) is not None
            else path.stem for path in exports
        ])
        chooser.pack(fill="x", pady=(0, 10))
        title = ttk.Label(panel, style="Section.TLabel", wraplength=690)
        title.pack(anchor="w")
        panel.bind("<Configure>", lambda event: title.configure(wraplength=max(200, event.width - 40)))
        state = ttk.Label(panel, style="Muted.TLabel")
        state.pack(anchor="w", pady=(0, 10))
        image = ttk.Label(panel)
        image.pack(anchor="w")
        actions = ttk.Frame(panel)
        actions.pack(fill="x", pady=(10, 0))
        edit = ttk.Frame(panel)
        edit.columnconfigure(1, weight=1)
        title_value, date_value = tk.StringVar(window), tk.StringVar(window)
        ttk.Label(edit, text="Titel").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(edit, textvariable=title_value).grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Label(edit, text="Termin · TT.MM.JJJJ HH:MM").grid(row=1, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(edit, textvariable=date_value).grid(row=1, column=1, sticky="ew", pady=3)
        description = tk.Text(panel, height=8, wrap="word", padx=8, pady=8)
        theme.style_text(description, colors)
        description.pack(fill="both", expand=True, pady=(10, 0))
        play = ttk.Button(actions, text="Gerenderte Folge öffnen")
        play.pack(side="left")
        approval_button = ttk.Button(actions, text="Für Upload freigeben")
        cover_button = ttk.Button(actions, text="Thumbnail wählen")
        retry_cover_button = ttk.Button(actions, text="Thumbnail erneut übertragen")
        studio_button = ttk.Button(actions, text="Diese Folge in YouTube Studio bearbeiten")

        def show_cover(path):
            try:
                with Image.open(path) as thumbnail:
                    thumbnail.thumbnail((min(480, width - 90), min(220, height // 3)))
                    image.photo = ImageTk.PhotoImage(thumbnail, master=window)
                image.configure(image=image.photo, text="")
            except (OSError, ValueError):
                image.configure(image="", text="Thumbnail derzeit nicht verfügbar")
                image.photo = None

        def open_export(video):
            try:
                os.startfile(video)
            except (OSError, AttributeError):
                state.configure(text="Die gerenderte Datei ist nicht erreichbar.")

        def display(event=None):
            sidecar = exports[chooser.current()]
            video = sidecar.with_suffix(".mp4")
            queued = read_json(sidecar.parent / "upload" / sidecar.name)
            metadata = queued or read_json(sidecar, {})
            draft = read_json(draft_path(video), {})
            can_approve = bool(draft and not queued and not approval_path(video).is_file())
            if can_approve:
                metadata = draft["metadata"]
            number = episode_number(sidecar)
            notices_ = row.updates
            notice_ = next((item for item in notices_ if item.get("job_id") == sidecar.stem
                            or number is not None and item.get("episode") == number),
                           notices_[0] if row.review and len(notices_) == 1 else {})
            reason = notice_.get("reason")
            state.configure(text="Prüfe Titel, Beschreibung, Thumbnail und Termin vor der Freigabe."
                            if can_approve else UPLOAD_REASON.get(reason) or
                            UPLOAD.get(notice_.get("status"), "Lokaler Folgenentwurf"))
            selected_cover = sidecar.with_suffix(".jpg")
            show_cover(selected_cover)
            description.configure(state="normal")
            description.delete("1.0", "end")
            description.insert("1.0", metadata.get("description") or "")
            title.configure(text=metadata.get("title", sidecar.stem))
            if can_approve:
                title.pack_forget()
                edit.pack(fill="x", before=state, pady=(0, 6))
                title_value.set(metadata.get("title", ""))
                stamp = metadata.get("publishAt")
                date_value.set(datetime.fromisoformat(stamp).astimezone().strftime("%d.%m.%Y %H:%M") if stamp else "")
                approval_button.pack(side="right")
                cover_button.pack(side="right", padx=theme.PAD_BUTTON)
            else:
                edit.pack_forget()
                title.pack(anchor="w", before=state)
                approval_button.pack_forget()
                cover_button.pack_forget()
                description.configure(state="disabled")
            if notice_.get("retry_thumbnail") is True and notice_.get("status") == "review":
                retry_cover_button.pack(side="right")
            else:
                retry_cover_button.pack_forget()
            video_id = notice_.get("video_id")
            if notice_.get("status") == "uploaded" and isinstance(video_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                studio_button.configure(command=lambda: webbrowser.open(f"https://studio.youtube.com/video/{video_id}/edit"))
                studio_button.pack(side="right", padx=theme.PAD_BUTTON)
            else:
                studio_button.pack_forget()

            def choose_cover():
                nonlocal selected_cover
                path = filedialog.askopenfilename(parent=window, filetypes=[("JPG oder PNG", "*.jpg *.jpeg *.png")])
                if path:
                    selected_cover = Path(path)
                    show_cover(selected_cover)

            def release():
                try:
                    config = profile_of(row)
                    local = parse_local_date(date_value.get())
                    stamp = berlin_slot(local.date(), local.hour, local.minute).isoformat() if local else None
                    upload_dir = Path(config["upload_incoming"])
                    _, occupied, _ = youtube_dates(upload_dir.parent / ".status" / "youtube-calendar.json")
                    if (upload_dir / f"{video.stem}.ready").exists() or (upload_dir.parent / ".status" / f"{video.stem}.json").exists():
                        raise ValueError("Diese Folge wurde bereits an den Server übergeben.")
                    approve(video, selected_cover, draft["file"],
                            {"title": title_value.get(), "description": description.get("1.0", "end-1c"),
                             "publishAt": stamp}, config["state"], occupied)
                except ValueError as error:
                    messagebox.showerror("Folge freigeben", str(error), parent=window)
                    return
                except (OSError, KeyError, StopIteration, sqlite3.Error) as error:
                    messagebox.showerror("Folge freigeben", problem("Die Folge konnte nicht freigegeben werden.",
                                                                    error, "Folge freigeben"), parent=window)
                    return
                window.destroy()
                notify("Folge freigegeben. Die Automatik übergibt sie an den Server.", "success")
                refresh()

            def retry_cover():
                key = notice_.get("job_id", "")
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", key):
                    return
                try:
                    (Path(profile_of(row)["upload_incoming"]) / f"{key}.retry-thumbnail").touch(exist_ok=True)
                except (OSError, StopIteration) as error:
                    messagebox.showerror("Thumbnail erneut übertragen", problem(
                        "Der neue Versuch konnte nicht angefordert werden.", error, "Thumbnail erneut"), parent=window)
                    return
                retry_cover_button.configure(state="disabled")
                state.configure(text="Neuer Thumbnail-Versuch angefordert.")

            cover_button.configure(command=choose_cover)
            approval_button.configure(command=release)
            retry_cover_button.configure(command=retry_cover, state="normal")
            play.configure(state="normal" if video.is_file() else "disabled", command=lambda: open_export(video))

        chooser.current(0)
        chooser.bind("<<ComboboxSelected>>", display)
        display()
        chooser.focus_set()

    def open_path(kind):
        row = selected()
        if not row:
            return
        if kind == "studio":
            video_id = next((n.get("video_id") for n in reversed(row.updates) if n.get("video_id")), "")
            if isinstance(video_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                webbrowser.open(f"https://studio.youtube.com/video/{video_id}/edit")
                return
            notify("Für diesen Auftrag ist noch keine YouTube-ID gespeichert.", "warning")
            return
        log_name = f"{row.key}.clips.log" if row.clips_retry else f"{row.key}.log"
        path = {"inbox": row.inbox, "output": row.review[0] if row.review else row.folder,
                "source": row.source, "log": row.work / log_name}[kind]
        if kind == "log" and row.review:
            path = next(iter(sorted(row.review[0].glob("render-*.log"), reverse=True)), path)
        try:
            os.startfile(path)
        except (OSError, AttributeError):
            notify("Diese Datei oder dieser Ordner ist derzeit nicht erreichbar.", "warning")

    def refresh(event=None):
        nonlocal waiting
        if waiting:
            return
        waiting = True

        def load():
            try:
                results.put(snapshot(profiles, samples))
            except (OSError, ValueError, TypeError, KeyError) as error:
                results.put(([], [problem("Der Status konnte nicht gelesen werden.", error, "Status lesen")]))

        Thread(target=load, daemon=True).start()

    def all_groups():
        found = []
        for top in table.get_children():
            found.append(top)
            found.extend(table.get_children(top))
        return [item for item in found if item.startswith(GROUP)]

    def add_row(parent, row):
        kind = row.bucket
        tag = "review" if kind == "todo" else "complete" if kind == "done" else "working"
        table.insert(parent, "end", iid=row.key, text=row.name, values=(row.series, row.detail), tags=(tag,))

    def poll():
        nonlocal waiting
        try:
            data, warnings = results.get_nowait()
        except Empty:
            pass
        else:
            waiting = False
            before = table.selection()
            scroll = table.yview()[0]
            opened = {item: bool(table.item(item, "open")) for item in all_groups()}
            rows.clear()
            rows.update((row.key, row) for row in data)
            table.delete(*table.get_children())
            buckets = grouped(data)
            for name, title, default_open in GROUPS:
                items = buckets[name]
                if not items:
                    continue
                top = GROUP + name
                table.insert("", "end", iid=top, text=f"{title} · {len(items)}", tags=("group",),
                             open=opened.get(top, default_open))
                if name != "done":
                    for row in items:
                        add_row(top, row)
                    continue
                for game, mine in done_by_game(items):
                    sub = f"{top}:{game}"
                    table.insert(top, "end", iid=sub, text=f"{game} · {len(mine)}", tags=("group",),
                                 open=opened.get(sub, False))
                    for row in mine:
                        add_row(sub, row)
            if rows:
                choice = preferred(data, before[0] if before else None)
                table.selection_set(choice)
                if before and choice == before[0]:
                    table.yview_moveto(scroll)  # gleiche Auswahl wie vorher: Ansicht und eingeklappte Gruppen bleiben
                else:
                    table.see(choice)
            else:
                table.insert("", "end", iid=GROUP + "empty", text=EMPTY_TEXT, tags=("empty",))
            if warnings:
                summary.configure(text="▲ " + " · ".join(warnings), style="Warning.TLabel")
            else:
                summary.configure(text=counts_text(buckets) + f"   ·   Aktualisiert {datetime.now():%H:%M:%S}",
                                  style="Muted.TLabel")
            show()
            root.after(10000, refresh)
        root.after(300, poll)

    ttk.Label(buttons, text="Öffnen", style="Muted.TLabel").pack(side="left", padx=(0, 8))
    for caption, kind in (("Eingang öffnen", "inbox"), ("Ausgabe öffnen", "output"),
                          ("Original ansehen", "source"), ("Protokoll öffnen", "log"),
                          ("YouTube Studio", "studio")):
        button = ttk.Button(buttons, text=caption, command=lambda action=kind: open_path(action))
        button.pack(side="left", padx=(0, theme.PAD_BUTTON))
        needs_row.append(button)
    preview_button = ttk.Button(jobs_header, text="Folgenvorschau", command=preview_episode)
    preview_button.pack(side="right", padx=(0, theme.PAD_BUTTON))
    history_button = ttk.Button(jobs_header, text="Verlauf", command=show_history)
    history_button.pack(side="right", padx=(0, theme.PAD_BUTTON))
    needs_row.extend((preview_button, history_button))
    mission_button = ttk.Button(jobs_header, text="Missionsbeginn", command=mark_mission)
    ttk.Button(buttons, text="Aktualisieren (F5)", command=refresh).pack(side="right")
    table.bind("<<TreeviewSelect>>", show)

    # Tastatur: F5 aktualisiert die sichtbare Seite, Alt+1/2/3 wechselt die Seite.
    def refresh_visible(event=None):
        if current_page[0] is calendar_page and hasattr(calendar_page, "refresh"):
            calendar_page.refresh()
        else:
            refresh()
        return "break"

    root.bind("<F5>", refresh_visible)
    for number, page in (("1", frame), ("2", calendar_page), ("3", profiles_page)):
        root.bind(f"<Alt-Key-{number}>", lambda _, target=page: (change_page(target), "break")[1])

    def bring_to_front():
        root.deiconify()
        if root.state() == "iconic":
            root.state("normal")
        root.lift()
        root.attributes("-topmost", True)  # Windows erlaubt sonst oft kein Nach-vorn-Holen
        root.after(250, lambda: root.attributes("-topmost", False))
        root.focus_force()

    def close():
        # Wie bei Steam: Laeuft der Tray, verschwindet das Fenster nur; sonst beendet das X das Programm.
        if not leave_profiles_ok():
            return
        if single_instance.tray_running(CONTROL):
            root.withdraw()
        else:
            root.destroy()

    def control():
        try:
            if single_instance.take_quit(CONTROL):
                root.destroy()
                return
            if single_instance.take_show(CONTROL):
                bring_to_front()
            elif root.state() == "withdrawn" and not single_instance.tray_running(CONTROL):
                bring_to_front()  # Tray ist weg: das versteckte Fenster nicht verlieren
        except tk.TclError:
            return
        root.after(400, control)

    root.protocol("WM_DELETE_WINDOW", close)
    show()
    refresh()
    root.after(300, poll)
    root.after(400, control)
    root.mainloop()


def run_tray():
    import pystray
    from PIL import Image

    tray_lock = single_instance.acquire_tray(CONTROL)
    if tray_lock is None:
        return  # Es gibt schon ein Tray-Symbol (z. B. Autostart und von Hand): kein zweites
    config = read_json(ROOT / "production/watcher.json", {})
    work = Path(config["work"])

    def open_window(icon, item):
        if single_instance.dashboard_running(CONTROL):
            single_instance.request_show(CONTROL)  # schon offen: nur nach vorn holen (auch bei Doppelklick)
            return
        if getattr(sys, "frozen", False):
            subprocess.Popen([sys.executable], cwd=ROOT)
        else:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve())], cwd=ROOT)

    app_dir = ROOT if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    script_dir = Path(__file__).resolve().parent if not getattr(sys, "frozen", False) else app_dir / "vodwerft"
    data_dir = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "VODWerft"

    def start_script(name, *arguments):
        pythonw = app_dir / "venv" / "Scripts" / "pythonw.exe"
        script = script_dir / name
        if pythonw.exists() and script.exists():
            subprocess.Popen([str(pythonw), "-X", "utf8", "-B", str(script), *arguments], cwd=script_dir)

    def open_settings(icon, item):
        start_script("settings_window.py", str(CONTROL))

    def open_setup(icon, item):
        start_script("setup_wizard.py")

    def open_data_folder(icon, item):
        data_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(data_dir))

    def quit_all(icon, item):
        single_instance.request_quit(CONTROL)  # offenes oder verstecktes Dashboard mit beenden
        icon.stop()

    def status():
        data = read_json(work / "tray-status.json", {})
        if 0 <= time.time() - data.get("updated", 0) < 45:
            return data.get("detail", "Status wird geladen")
        return "Statusdienst antwortet nicht"

    def watch(icon):
        icon.visible = True
        while icon.visible:
            server = read_json(work / "server-status.json", {})
            mark = "" if server.get("state") in ("ok", "direct", None) else " ▲Server"
            icon.title = ("VODWerft " + program_version() + " · " + status() + mark)[:127]
            time.sleep(5)

    with Image.open(ICON) as image:
        tray = pystray.Icon("VODWerft", image.copy(), "VODWerft",
                            pystray.Menu(pystray.MenuItem(lambda _: status(), None, enabled=False),
                                         pystray.MenuItem("VODWerft öffnen", open_window, default=True),
                                         pystray.MenuItem("Einstellungen", open_settings),
                                         pystray.MenuItem("Einrichtung öffnen", open_setup),
                                         pystray.MenuItem("Datenordner öffnen", open_data_folder),
                                         pystray.MenuItem("Beenden", quit_all)))
    tray.run(setup=watch)


if __name__ == "__main__":
    if "--tray" in sys.argv:
        run_tray()
    else:
        main()
