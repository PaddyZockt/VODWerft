"""Calendar for reserving Nightcut episode dates before upload."""
import calendar
import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from release_slots import read_manual, reserve_manual_batch
from game_profiles import recording_settings
from dashboard_data import problem
import theme

MONTHS = ("Januar", "Februar", "März", "April", "Mai", "Juni",
          "Juli", "August", "September", "Oktober", "November", "Dezember")


def episodes(profiles):
    entries = {}
    for profile in profiles:
        work = Path(profile["work"])
        db_path = work / "jobs.sqlite3"
        if not db_path.is_file():
            continue
        with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)) as db:
            batches = db.execute("SELECT key,status FROM recordings "
                                 "WHERE status IN ('processing','ready','review','stopped')").fetchall()
            handoffs = dict(db.execute("SELECT episode,status FROM handoffs"))
        series_db = Path(profile["state"])
        if not series_db.is_file():
            continue
        with closing(sqlite3.connect(series_db.as_uri() + "?mode=ro", uri=True)) as db:
            planned = read_manual(db)
            starts = dict(db.execute("SELECT name,first_episode FROM batches WHERE series=?",
                                     (profile["series"],)))
        for key, status in batches:
            if not recording_settings(profile, key).get("manual_release"):
                continue
            folder = work / key
            if status == "ready":
                numbers = [int(video.stem.rsplit("-ep", 1)[1]) for video in folder.glob(f"{key}-ep*.mp4")
                           if video.stem.rsplit("-ep", 1)[1].isdigit() and video.with_suffix(".json").is_file()
                           and video.with_suffix(".jpg").is_file()]
            else:
                if key not in starts:
                    continue
                try:
                    plan = json.loads((folder / "nightcut" / "episodes.json").read_text(encoding="utf-8"))
                    indices = [ep["n"] for ep in plan]
                    if indices != list(range(1, len(indices) + 1)):
                        continue
                except (OSError, ValueError, TypeError, KeyError):
                    continue
                numbers = [starts[key] + index - 1 for index in indices]
            for number in sorted(numbers):
                stem = f"{key}-ep{number:02d}"
                stamp = planned.get(stem)
                if status in ("review", "stopped") and not stamp:
                    continue
                title = f"{profile['series']} · Folge {number:02d}"
                try:
                    title = json.loads((folder / f"{stem}.json").read_text(encoding="utf-8"))["title"]
                except (OSError, ValueError, KeyError):
                    pass
                entries[stem] = (profile, title, stamp, handoffs.get(stem), status)
    return entries


def youtube_dates(path):
    if path is None:
        return {}, set(), "YouTube-Abgleich noch nicht eingerichtet."
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        updated = datetime.fromisoformat(snapshot["updated"]).astimezone()
        today = datetime.now(timezone.utc)
        dates, slots = {}, set()
        for video in snapshot["videos"]:
            stamp = datetime.fromisoformat(video["publish_at"])
            if stamp <= today:
                continue
            local = stamp.astimezone()
            dates.setdefault(local.date(), []).append((local, video["title"], "YouTube bestätigt"))
            slots.add(stamp.astimezone(timezone.utc).isoformat())
    except (OSError, ValueError, TypeError, KeyError):
        return {}, set(), "YouTube-Abgleich derzeit nicht verfügbar."
    age = " · möglicherweise veraltet" if today - updated > timedelta(hours=2) else ""
    return dates, slots, f"YouTube-Abgleich: {updated:%d.%m.%Y, %H:%M} Uhr{age}"


def clock_value(hour, minute):
    """Uhrzeit aus den beiden Feldern (Text) -> (Stunde, Minute). Fehler als verständlicher Satz."""
    try:
        hour, minute = int(str(hour).strip()), int(str(minute).strip())
    except ValueError:
        hour = minute = -1
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Bitte eine gültige Uhrzeit wählen: Stunde 0 bis 23, Minute 0 bis 59.")
    return hour, minute


def build(parent, profiles, blocked, snapshot_path=None):
    theme.ensure(parent)
    frame = ttk.Frame(parent, padding=(theme.PAD_WINDOW, 12))
    ttk.Label(frame, text="Veröffentlichung planen", style="Section.TLabel").pack(anchor="w")
    ttk.Label(frame, text="Folgen sind ab fertigem Schnittplan auswählbar. Der Upload wartet auf den Export.",
              style="Muted.TLabel").pack(anchor="w", pady=(4, 10))
    selector = ttk.Combobox(frame, state="readonly", width=75)
    selector.pack(anchor="w", fill="x")
    chosen = date.today() + timedelta(days=2)
    month = chosen.replace(day=1)
    content = ttk.Frame(frame)
    content.pack(fill="x", pady=(14, 8))
    dates = ttk.Frame(content)
    dates.pack(side="left", anchor="n", padx=(0, 28))
    controls = ttk.Frame(content)
    controls.pack(side="left", anchor="n", fill="x", expand=True)
    bar = ttk.Frame(dates)
    bar.pack(anchor="w", pady=(8, 4))
    grid = ttk.Frame(dates)
    grid.pack(anchor="w")
    caption = ttk.Label(bar, width=20, anchor="center")
    selected_day = ttk.Label(controls, style="Section.TLabel")
    options = []
    appointments = {}
    youtube_slots = set()

    def draw():
        caption.configure(text=f"{MONTHS[month.month - 1]} {month.year}")
        for child in grid.winfo_children():
            child.destroy()
        for col, day in enumerate(("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")):
            ttk.Label(grid, text=day, anchor="center").grid(row=0, column=col, sticky="ew")
        for row, week in enumerate(calendar.Calendar().monthdatescalendar(month.year, month.month), 1):
            for col, day in enumerate(week):
                if day.month == month.month:
                    busy = day in appointments
                    text = f"{day.day} •" if busy else str(day.day)
                    style = "Day.Selected.TButton" if day == chosen else "Day.Busy.TButton" if busy else "Day.TButton"
                    ttk.Button(grid, text=text, width=5, command=lambda value=day: choose(value), style=style,
                               state="normal" if day >= date.today() else "disabled").grid(row=row, column=col,
                                                                                          padx=1, pady=1)
        selected_day.configure(text=f"{chosen:%d.%m.%Y}")
        listing.delete(*listing.get_children())
        for local, title, source in sorted(appointments.get(chosen, [])):
            listing.insert("", "end", values=(local.strftime("%H:%M"), title, source))
        listing_title.configure(text=f"Termine am {chosen:%d.%m.%Y} · {len(appointments.get(chosen, []))}")

    def choose(day):
        nonlocal chosen
        chosen = day
        draw()

    def move(days):
        nonlocal month
        month = (month + timedelta(days=days)).replace(day=1)
        draw()

    ttk.Button(bar, text="‹", width=3, command=lambda: move(-1)).pack(side="left")
    caption.pack(side="left")
    ttk.Button(bar, text="›", width=3, command=lambda: move(32)).pack(side="left")
    # Legende unter dem Monat
    legend = ttk.Frame(dates)
    legend.pack(side="bottom", anchor="w", pady=(8, 0))
    for sample, style, meaning in (("12", "Day.Selected.TButton", "gewählter Tag"),
                                   ("12 •", "Day.Busy.TButton", "Termin vorhanden"),
                                   ("12", "Day.TButton", "frei")):
        ttk.Button(legend, text=sample, width=5, style=style, takefocus=0).pack(side="left")
        ttk.Label(legend, text=meaning, style="Small.Muted.TLabel").pack(side="left", padx=(4, 12))
    ttk.Label(controls, text="VERÖFFENTLICHUNG", style="Brand.TLabel").pack(anchor="w", pady=(8, 4))
    selected_day.pack(anchor="w", pady=(0, 10))
    ttk.Label(controls, text="Uhrzeit in Deutschland", style="Muted.TLabel").pack(anchor="w")
    clock = ttk.Frame(controls)
    clock.pack(anchor="w", pady=(4, 10))
    hour_value, minute_value = tk.StringVar(frame, "19"), tk.StringVar(frame, "00")
    ttk.Spinbox(clock, from_=0, to=23, wrap=True, width=4, format="%02.0f", textvariable=hour_value).pack(side="left")
    ttk.Label(clock, text="Std", style="Muted.TLabel").pack(side="left", padx=(4, 10))
    ttk.Spinbox(clock, from_=0, to=55, increment=5, wrap=True, width=4, format="%02.0f",
                textvariable=minute_value).pack(side="left")
    ttk.Label(clock, text="Min", style="Muted.TLabel").pack(side="left", padx=(4, 0))
    weekly = tk.BooleanVar(value=False)
    ttk.Checkbutton(controls, text="Wöchentlich für diese Aufnahme", variable=weekly).pack(anchor="w", pady=(0, 8))
    actions = ttk.Frame(controls)
    actions.pack(anchor="w")
    listing_title = ttk.Label(frame, style="Section.TLabel")
    listing_title.pack(anchor="w", pady=(4, 3))
    sync_label = ttk.Label(frame, style="Muted.TLabel")
    sync_label.pack(anchor="w", pady=(0, 4))
    schedule_list = ttk.Frame(frame)
    schedule_list.pack(fill="both", expand=True)
    listing = ttk.Treeview(schedule_list, columns=("time", "title", "source"), show="headings", height=4)
    for key, title, width in (("time", "UHRZEIT", 70), ("title", "VIDEO", 510), ("source", "STATUS", 180)):
        listing.heading(key, text=title, anchor="w")
        listing.column(key, width=width, stretch=key == "title", minwidth=60)
    scroll = ttk.Scrollbar(schedule_list, orient="vertical", command=listing.yview)
    listing.configure(yscrollcommand=scroll.set)
    listing.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    def refresh():
        nonlocal appointments, youtube_slots
        appointments, youtube_slots, summary = youtube_dates(snapshot_path)
        sync_label.configure(text=summary, style="Muted.TLabel")
        try:
            data = episodes(profiles)
        except (OSError, ValueError, KeyError, sqlite3.Error) as error:
            sync_label.configure(text=problem("Die lokalen Folgen konnten nicht gelesen werden.", error,
                                              "Kalender: lokale Folgen"), style="Danger.TLabel")
            draw()
            return
        old = selector.current()
        previous = options[old][0] if 0 <= old < len(options) else None
        options[:] = [(key, profile, title, status) for key, (profile, title, stamp, _, status) in data.items()
                      if not stamp]
        labels = tuple(f"{title}  [{key.rsplit('-ep', 1)[-1]}] "
                       f"{'· in Bearbeitung' if status == 'processing' else ''}"
                       for key, _, title, status in options)
        if labels != tuple(selector.cget("values")):
            selector.configure(values=labels)
            if options:
                selector.current(next((i for i, item in enumerate(options) if item[0] == previous), 0))
            else:
                selector.set("")
        if not options:
            selector.set("Keine Folge zum Einplanen vorhanden. Folgen erscheinen hier, sobald ihr Schnittplan fertig ist.")
        plan_button.configure(state="normal" if options else "disabled")
        for _, title, stamp, handoff, processing in data.values():
            if not stamp or stamp in youtube_slots:
                continue
            local = datetime.fromisoformat(stamp).astimezone()
            if local > datetime.now().astimezone():
                status = {
                    "processing": "Wartet auf Export",
                    "review": "Bearbeitung prüfen",
                    "stopped": "Gestoppt",
                    "ready": "An den Server übergeben" if handoff == "sent" else "Übergabe ausstehend",
                }[processing]
                appointments.setdefault(local.date(), []).append((local, title, status))
        draw()

    def schedule():
        choice = selector.current()
        if choice < 0:
            messagebox.showinfo("Kalender", "Wähle eine Folge mit fertigem Schnittplan.", parent=parent)
            return
        key, profile, title, _ = options[choice]
        try:
            hour, minute = clock_value(hour_value.get(), minute_value.get())
            when = datetime(2000, 1, 1, hour, minute)
            batch, _, first = key.rpartition("-ep")
            selected = [(key, chosen)]
            if weekly.get():
                for other, _, _, _ in options:
                    other_batch, _, number = other.rpartition("-ep")
                    if other_batch == batch and int(number) > int(first):
                        selected.append((other, chosen + timedelta(weeks=int(number) - int(first))))
            dates_text = "\n".join(f"Folge {episode.rsplit('-ep', 1)[-1]} · {day:%d.%m.%Y}"
                                   for episode, day in selected)
            if len(selected) > 12:
                dates_text = (f"{len(selected)} Folgen vom {selected[0][1]:%d.%m.%Y} "
                              f"bis {selected[-1][1]:%d.%m.%Y}, jeweils im Wochenabstand.")
            if not messagebox.askyesno(
                    "YouTube-Termin bestätigen",
                    f"{title}\n\n{dates_text}\n\nJeweils um {when:%H:%M} Uhr (Deutschland) einplanen?",
                    parent=parent):
                return
            _, latest, _ = youtube_dates(snapshot_path)
            reserve_manual_batch(profile["state"], selected, when.hour, when.minute, (*blocked, *latest))
        except ValueError as error:  # Hinweise zur Eingabe (Termin belegt, zu früh ...)
            messagebox.showerror("Termin konnte nicht gespeichert werden", str(error), parent=parent)
            return
        except (OSError, KeyError, sqlite3.Error) as error:
            messagebox.showerror("Termin konnte nicht gespeichert werden",
                                 problem("Die Terminplanung ist gerade nicht erreichbar.", error, "Termin einplanen"),
                                 parent=parent)
            return
        refresh()

    plan_button = ttk.Button(actions, text="Für YouTube einplanen", command=schedule)
    plan_button.pack(side="left")
    ttk.Button(actions, text="Aktualisieren (F5)", command=refresh).pack(side="left", padx=theme.PAD_BUTTON + 2)
    frame.bind("<Map>", lambda _: refresh())
    def periodic_refresh():
        if frame.winfo_ismapped():
            refresh()
        frame.after(15000, periodic_refresh)

    frame.after(15000, periodic_refresh)
    refresh()
    frame.refresh = refresh
    return frame
