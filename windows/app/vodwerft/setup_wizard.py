"""Einrichtungsassistent (Fenster). Die Logik steht in setup_assistant.py.

Ablauf: 1 Prüfung des Rechners, 2 Upload-Weg, 3 Ordner, 4 Spiele, 5 YouTube (nur Direkt-Upload),
6 Zusammenfassung und Speichern. Farben und Abstände kommen aus theme.py.
"""
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import brand
import game_library
import setup_assistant as logic
import theme

DAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


class Wizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Einrichtung")
        theme.set_icon(self)
        self.geometry("660x580")
        self.colors = theme.apply(self, theme.palette(brand.FIRST_RUN_THEME))
        self.env = logic.detect_environment()
        self.data_dir = tk.StringVar(value=str(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "VODWerft"))
        self.share = tk.StringVar()
        self.mode = tk.StringVar(value="direct")  # "server" (Docker-Server) oder "direct" (Upload vom PC)
        self.channel = tk.StringVar()
        self.recordings = tk.StringVar(value=str(Path.home() / "Videos"))
        self.ffmpeg = tk.StringVar(value=self.env["ffmpeg_directory"] or "")
        self.ollama = tk.StringVar(value=self.env["ollama"] or "")
        presets = logic.parse_presets(sys.argv[1:])  # Vorgaben aus dem Installer
        if presets.get("mode"):
            self.mode.set(presets["mode"])
        if presets.get("data_dir"):
            self.data_dir.set(presets["data_dir"])
        if presets.get("share"):
            self.share.set(presets["share"])
        self.games = []  # Liste aus (Name, Minuten, Tage-Variablen)
        self.pages = [self.page_check, self.page_mode, self.page_folders, self.page_games, self.page_youtube, self.page_finish]
        self.index = 0
        top = ttk.Frame(self, padding=(theme.PAD_WINDOW, theme.PAD_BLOCK, theme.PAD_WINDOW, 0))
        top.pack(fill="x")
        self.step_label = ttk.Label(top, style="Brand.TLabel")
        self.step_label.pack(anchor="w")
        bar = ttk.Frame(self, padding=(theme.PAD_WINDOW, 0, theme.PAD_WINDOW, theme.PAD_BLOCK))
        bar.pack(side="bottom", fill="x")
        self.body = ttk.Frame(self, padding=(theme.PAD_WINDOW, 6, theme.PAD_WINDOW, theme.PAD_BLOCK))
        self.body.pack(fill="both", expand=True)
        self.back = ttk.Button(bar, text="◀ Zurück", command=lambda: self.go(-1))
        self.back.pack(side="left")
        self.next = ttk.Button(bar, text="Weiter ▶", command=lambda: self.go(1))
        self.next.pack(side="right")
        ttk.Label(bar, text="Alt+← / Alt+→ blättert", style="Small.Muted.TLabel").pack(side="right", padx=12)
        self.bind("<Alt-Right>", lambda _: self.go(1))
        self.bind("<Alt-Left>", lambda _: self.go(-1) if self.index else None)
        self.show()

    # --- Navigation
    def show(self):
        for child in self.body.winfo_children():
            child.destroy()
        self.pages[self.index]()
        visible = self.visible_pages()
        self.step_label.configure(text=f"SCHRITT {visible.index(self.pages[self.index]) + 1} VON {len(visible)}")
        self.back.state(["!disabled" if self.index else "disabled"])
        self.next.config(text="Speichern" if self.index == len(self.pages) - 1 else "Weiter ▶")
        self.next.focus_set()

    def visible_pages(self):
        """Seiten, die bei der aktuellen Auswahl gezeigt werden (YouTube-Anmeldung nur beim Direkt-Upload)."""
        return [page for page in self.pages if page != self.page_youtube or self.mode.get() == "direct"]

    def go(self, step):
        if step > 0:
            problem = self.check_page()
            if problem:
                messagebox.showwarning("Bitte prüfen", problem, parent=self)
                return
            if self.index == len(self.pages) - 1:
                return self.save()
        self.index = max(0, min(len(self.pages) - 1, self.index + step))
        while self.pages[self.index] == self.page_youtube and self.mode.get() != "direct":  # nur im Direkt-Modus
            self.index += 1 if step > 0 else -1
        self.show()

    def check_page(self):
        page = self.pages[self.index]
        if page == self.page_folders:
            checks = [("Datenordner", self.data_dir), ("ffmpeg-Ordner", self.ffmpeg), ("Ollama", self.ollama)]
            if self.mode.get() == "server":
                checks.insert(1, ("Server-Freigabe", self.share))
            for label, var in checks:
                if not var.get().strip():
                    return f"{label} fehlt."
            if self.mode.get() == "server" and not (Path(self.share.get()) / ".upload").is_dir():
                return "In der Server-Freigabe gibt es keinen Ordner „.upload“. Ist der Upload-Server eingerichtet und das Laufwerk verbunden?"
        if page == self.page_games:
            try:
                logic.validate(self.answers())
            except ValueError as error:
                return str(error)
            except tk.TclError:  # halb getippte Zahl im Feld „Folge ca.“
                return "Bitte die Folgenlänge als ganze Zahl zwischen 5 und 180 Minuten eingeben."
        return None

    # --- Seiten
    def heading(self, text, hint=""):
        ttk.Label(self.body, text=text, style="Heading.TLabel").pack(anchor="w")
        if hint:
            ttk.Label(self.body, text=hint, style="Muted.TLabel", wraplength=600,
                      justify="left").pack(anchor="w", pady=(4, 10))

    def page_check(self):
        self.heading("Rechner prüfen", "Das braucht die Videoverarbeitung auf diesem Rechner.")
        problems = logic.check_requirements(self.env)
        gpu = f"{self.env['gpu']} ({self.env['vram_mb'] // 1024} GB)" if self.env["gpu"] else "nicht erkannt"
        for text, ok in (("ffmpeg", bool(self.env["ffmpeg_directory"])), ("Ollama", bool(self.env["ollama"])),
                         (f"Grafikkarte: {gpu}", bool(self.env["vram_mb"]) and self.env["vram_mb"] >= logic.MIN_VRAM_MB)):
            ttk.Label(self.body, text=("✔ " if ok else "✘ ") + text,
                      style="Success.TLabel" if ok else "Danger.TLabel").pack(anchor="w", pady=1)
        if problems:
            ttk.Label(self.body, text="\nHinweise:\n- " + "\n- ".join(problems), style="Warning.TLabel",
                      wraplength=600, justify="left").pack(anchor="w")
            ttk.Label(self.body, text="\nDu kannst trotzdem weitermachen und das später nachholen.").pack(anchor="w")

    def page_mode(self):
        self.heading("Wie soll hochgeladen werden?")
        for value, text, hint in (
                ("direct", "Direkt von diesem PC (einfach)",
                 "Kein Server nötig. Der PC lädt die fertigen Folgen selbst zu YouTube hoch. Er muss nur beim Hochladen an sein, "
                 "nicht zur Veröffentlichungszeit."),
                ("manual", "Von Hand hochladen (ohne YouTube-Projekt)",
                 "Am einfachsten für den Start: Kein Google-Projekt, keine Anmeldung. VODWerft bereitet Video, Titel, Beschreibung "
                 "und Vorschaubild vor und öffnet YouTube Studio. Du ziehst die Datei dort selbst hinein."),
                ("server", "Über einen Server (Docker)",
                 "Für Dauerbetrieb: Der Server lädt rund um die Uhr hoch, die YouTube-Zugangsdaten liegen nicht auf dem Spiele-PC. "
                 "Der Server muss vorher eingerichtet sein.")):
            ttk.Radiobutton(self.body, text=text, value=value, variable=self.mode).pack(anchor="w", pady=(8, 0))
            ttk.Label(self.body, text=hint, style="Muted.TLabel", wraplength=560, justify="left").pack(anchor="w", padx=22)

    def page_youtube(self):
        self.heading("YouTube-Anmeldung", "Einmalig. Dein Passwort sieht dieses Programm nie, es speichert nur ein Anmelde-Token auf diesem PC. "
                     "Die Zugangsdatei (client_secrets.json) erstellst du in der Google Cloud Console, die Anleitung steht im Handbuch.")
        self.yt_state = tk.StringVar()
        ttk.Label(self.body, textvariable=self.yt_state, font=(theme.FONT, 11, "bold")).pack(anchor="w", pady=6)
        ttk.Button(self.body, text="Zugangsdatei auswählen …", command=self.pick_client).pack(anchor="w", pady=3)
        self.login_button = ttk.Button(self.body, text="Bei YouTube anmelden", command=self.start_login)
        self.login_button.pack(anchor="w", pady=3)
        ttk.Label(self.body, text="Du kannst das auch später nachholen: Der Upload bleibt gesperrt, bis die Anmeldung steht.",
                  wraplength=560, justify="left").pack(anchor="w", pady=10)
        self.refresh_youtube()

    def refresh_youtube(self):
        state = logic.youtube_state(self.data_dir.get().strip())
        self.yt_state.set({"fehlt": "✘ Zugangsdatei fehlt", "client": "✔ Zugangsdatei da, noch nicht angemeldet",
                           "angemeldet": "✔ Bei YouTube angemeldet"}[state])
        self.login_button.state(["!disabled" if state != "fehlt" else "disabled"])

    def pick_client(self):
        path = filedialog.askopenfilename(title="client_secrets.json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            logic.install_client_secrets(self.data_dir.get().strip(), path)
        except ValueError as error:
            return messagebox.showerror("Zugangsdatei", f"Die Datei passt nicht: {error}", parent=self)
        except OSError:
            return messagebox.showerror("Zugangsdatei", "Die Datei konnte nicht gelesen oder kopiert werden. "
                                        "Liegt sie auf einem erreichbaren Laufwerk?", parent=self)
        self.refresh_youtube()

    def start_login(self):
        import threading
        from youtube_login import login
        self.login_button.state(["disabled"])
        self.yt_state.set("Browser öffnet sich … bitte dort anmelden")

        def work():
            try:
                login(logic.secrets_dir(self.data_dir.get().strip()))
                message = None
            except (ValueError, PermissionError, TimeoutError) as error:
                message = str(error)
            except OSError:
                message = ("Die Anmeldung konnte nicht abgeschlossen werden. Bitte die Internetverbindung prüfen "
                           "und es erneut versuchen.")
            self.after(0, lambda: self.login_done(message))
        threading.Thread(target=work, daemon=True).start()

    def login_done(self, message):
        if message:
            messagebox.showerror("Anmeldung", message, parent=self)
        self.refresh_youtube()

    def row(self, label, var, folder=True, file=False):
        frame = ttk.Frame(self.body)
        frame.pack(fill="x", pady=3)
        ttk.Label(frame, text=label, width=24).pack(side="left")
        ttk.Entry(frame, textvariable=var).pack(side="left", fill="x", expand=True)
        if folder or file:
            pick = filedialog.askopenfilename if file else filedialog.askdirectory
            ttk.Button(frame, text="Durchsuchen …", style="Compact.TButton",
                       command=lambda: var.set(pick(parent=self) or var.get())).pack(side="left", padx=(theme.PAD_BUTTON, 0))

    def page_folders(self):
        self.heading("Ordner", "Die Server-Freigabe ist der Ordner, in dem dein Upload-Server arbeitet (mit „.upload“, „Fertig“ und „Pruefen“)."
                     if self.mode.get() == "server" else "Der Datenordner enthält Einstellungen, Zwischendateien und die fertigen Folgen.")
        self.row("Datenordner", self.data_dir)
        if self.mode.get() == "server":
            self.row("Server-Freigabe", self.share)
        self.row("Aufnahmen (Oberordner)", self.recordings)
        self.row("ffmpeg-Ordner", self.ffmpeg)
        self.row("Ollama (ollama.exe)", self.ollama, folder=False, file=True)
        self.row("Dein YouTube-Kanal (Link)", self.channel, folder=False)

    def page_games(self):
        self.heading("Spiele", "Pro Spiel ein eigener Aufnahmeordner unter „Aufnahmen“. Eigene Namen sind möglich, ohne Sonderzeichen wie : / \\ ? * \" < > |.")
        choice = tk.StringVar()
        top = ttk.Frame(self.body)
        top.pack(fill="x")
        box = ttk.Combobox(top, textvariable=choice, values=game_library.names())
        box.pack(side="left", fill="x", expand=True)
        box.bind("<Return>", lambda _: self.add_game(choice))
        ttk.Button(top, text="Hinzufügen", command=lambda: self.add_game(choice)).pack(side="left", padx=theme.PAD_BUTTON)
        self.list = ttk.Frame(self.body)
        self.list.pack(fill="both", expand=True, pady=8)
        self.draw_games()

    def add_game(self, choice):
        name = choice.get().strip()
        if not name:
            return
        if not logic.valid_game_name(name):
            return messagebox.showwarning("Spielname", "Dieser Name enthält nicht erlaubte Zeichen.", parent=self)
        if any(game["name"].casefold() == name.casefold() for game in self.games):
            return
        self.games.append({"name": name, "minutes": tk.IntVar(value=25),
                           "days": [tk.BooleanVar(value=index in (0, 3)) for index in range(7)]})
        choice.set("")
        self.draw_games()

    def draw_games(self):
        for child in self.list.winfo_children():
            child.destroy()
        if not self.games:
            ttk.Label(self.list, text="Noch kein Spiel hinzugefügt. Wähle oben ein Spiel aus der Liste oder tippe "
                      "einen eigenen Namen ein und klicke auf „Hinzufügen“.", style="Muted.TLabel",
                      wraplength=580, justify="left").pack(anchor="w", pady=8)
        for game in self.games:
            frame = ttk.LabelFrame(self.list, text=game["name"], padding=6)
            frame.pack(fill="x", pady=3)
            first, second = ttk.Frame(frame), ttk.Frame(frame)
            first.pack(fill="x")
            second.pack(fill="x", pady=(4, 0))
            ttk.Label(first, text="Folge ca.").pack(side="left")
            ttk.Spinbox(first, from_=5, to=180, width=5, textvariable=game["minutes"]).pack(side="left", padx=4)
            ttk.Label(first, text="Minuten").pack(side="left")
            ttk.Button(first, text="Entfernen", style="Compact.TButton",
                       command=lambda g=game: self.remove(g)).pack(side="right")
            ttk.Label(second, text="Veröffentlichung:").pack(side="left", padx=(0, 4))
            for label, var in zip(DAYS, game["days"]):
                ttk.Checkbutton(second, text=label, variable=var).pack(side="left")

    def remove(self, game):
        self.games.remove(game)
        self.draw_games()

    def answers(self):
        return {
            "data_dir": self.data_dir.get().strip(), "share": self.share.get().strip(), "mode": self.mode.get(),
            "recordings_dir": self.recordings.get().strip(), "channel_url": self.channel.get().strip(),
            "ffmpeg_directory": self.ffmpeg.get().strip(), "ollama": self.ollama.get().strip(),
            "games": [{"name": game["name"], "minutes": game["minutes"].get(),
                       "weekdays": [i for i, var in enumerate(game["days"]) if var.get()]} for game in self.games],
        }

    def page_finish(self):
        self.heading("Fertig zum Speichern", "Es wird nichts hochgeladen, bevor du es freigibst. Jede Folge wartet auf deine Freigabe.")
        for game in self.games:
            days = ", ".join(DAYS[i] for i, var in enumerate(game["days"]) if var.get())
            ttk.Label(self.body, text=f"• {game['name']}: {game['minutes'].get()} Min, {days}").pack(anchor="w")
        ttk.Label(self.body, justify="left", wraplength=590, text=(
            ("\nDie YouTube-Anmeldung findest du im Menü des Tray-Symbols unter „Einrichtung öffnen“, falls du sie übersprungen hast."
             if self.mode.get() == "direct" else
             "\nVon Hand hochladen: Im Tray-Menü gibt es den Eintrag „Manuell hochladen“. Dort liegen fertige Folgen bereit, "
             "mit Titel, Beschreibung und Vorschaubild zum Kopieren."
             if self.mode.get() == "manual" else
             "\nNoch von Hand (einmalig): die YouTube-Anmeldung. Dafür brauchst du ein eigenes Google-Projekt mit YouTube-Zugang "
             "und legst die Zugangsdatei im Server-Ordner ab. Die genaue Anleitung steht im Benutzerhandbuch."))).pack(anchor="w")

    def save(self):
        try:
            path = logic.write(self.answers())
        except FileExistsError:
            if not messagebox.askyesno("Einrichtung vorhanden", "Es gibt schon eine Einrichtung. Ersetzen? "
                                       "Die alten Dateien werden gesichert.", parent=self):
                return
            try:
                path = logic.write(self.answers(), overwrite=True)
            except (ValueError, OSError) as error:
                return self.save_failed(error)
        except (ValueError, OSError) as error:
            return self.save_failed(error)
        start = Path(__file__).resolve().parent.parent / "start.ps1"
        if os.name == "nt" and start.is_file():  # Dienste (Automatik, Status) jetzt starten
            subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                              "-File", str(start)], creationflags=0x08000000)
        messagebox.showinfo("Gespeichert", f"Einrichtung gespeichert:\n{path}", parent=self)
        self.destroy()

    def save_failed(self, error):
        if isinstance(error, ValueError):
            message = str(error)
        else:
            message = ("Die Einrichtung konnte nicht gespeichert werden. Ist der Datenordner beschreibbar und das "
                       "Laufwerk verbunden?")
        messagebox.showerror("Speichern nicht möglich", message, parent=self)


def main():
    Wizard().mainloop()


if __name__ == "__main__":
    main()
