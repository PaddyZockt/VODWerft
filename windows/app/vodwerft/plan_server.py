"""Prüf-Weboberfläche für "Plan prüfen": kleiner lokaler Webserver (nur 127.0.0.1).

Warum ein Webserver statt Electron: kein zusätzliches Programm im Installer, der Browser
(Edge ist auf jedem Windows vorhanden) spielt per Grafikkarte ab, und derselbe Code läuft
später auch in VODWerft. Das Fenster ist `msedge --app=<Adresse>`.

Sicherheit: Der Server hört nur auf 127.0.0.1 und verlangt bei jeder Anfrage ein zufälliges
Token (steht nur in der Adresse, die wir selbst öffnen). Andere Webseiten im Browser können
den Server dadurch nicht ansprechen.

Die Logik (build_state, save_manual, byte_range) ist rein und getestet; HTTP ist nur die Hülle.
"""
import argparse
import json
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import traceback
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Der Nightcut-Kern liegt neben diesem Ordner (im Repo wie in der Installation)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "nightcut" / "src"))

import proxy  # noqa: E402
import theme  # noqa: E402
from nightcut import plan_review  # noqa: E402
from plan_status import work_folder  # noqa: E402

ORIGINAL_TYPES = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
                  ".mkv": "video/x-matroska", ".webm": "video/webm"}
UI_FILE = Path(__file__).with_name("plan_review_ui") / "index.html"


# ---- reine Logik --------------------------------------------------------------------------------

def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def mission_start(source):
    """Missionsbeginn in Sekunden aus <Aufnahme>.start.txt (vom Dashboard-Knopf "Missionsbeginn"), sonst None.
    Alles davor schneidet das Rendern ab (--trim-start). Die Prüfseite zeigt es, damit man es dort nicht vermisst."""
    try:
        text = Path(source).with_suffix(".start.txt").read_text(encoding="utf-8-sig").strip()
    except OSError:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        seconds = float(text)
    elif re.fullmatch(r"(?:\d{1,2}:)?\d{1,3}:[0-5]\d", text):
        seconds = float(sum(int(part) * 60 ** index for index, part in enumerate(reversed(text.split(":")))))
    else:
        return None
    return seconds if 0 < seconds < 86400 else None


def build_state(output, progress=None, audio_progress=None):
    """Alles, was die Seite braucht: Aufnahmen, automatische Entfernungen, Markierungen, Proxy-Stand."""
    work = work_folder(output)
    review = read_json(work / "plan_review.json", {})
    files = review.get("files", [])
    cuts = read_json(work / "cuts.json", [])
    manual = plan_review.read_manual(work, len(files))
    keep = plan_review.read_keep(work, len(files))
    progress, audio_progress = progress or {}, audio_progress or {}
    result = []
    for n, f in enumerate(files):
        removals = cuts[n]["removals"] if n < len(cuts) else []
        result.append({
            "name": Path(f["source"]).name, "duration": f["duration"],
            "auto": [{"start": r["start"], "end": r["end"], "label": r["label"]} for r in removals
                     if r["label"] != plan_review.LABEL],
            "manual": plan_review.clean_ranges(manual[n], f["duration"]),
            "keep": plan_review.clean_keeps(keep[n], f["duration"]),  # automatisch entfernt, aber vom Nutzer behalten
            # nur bei genau einer Aufnahme (so rendert auch --trim-start); zu spät gesetzte Werte begrenzen
            "mission_start": min(mission_start(f["source"]) or 0, f["duration"]) or None if len(files) == 1 else None,
            "proxy": proxy.proxy_path(work, n).is_file(),
            "progress": progress.get(n, 0.0),
            "audio": proxy.audio_path(work, n).is_file(),  # Mix-Ton aller Spuren (zum Original dazu)
            "audio_progress": audio_progress.get(n, 0.0),
        })
    return {"files": result, "confirmed": plan_review.is_confirmed(work)}


def save_manual(output, payload):
    """Markierungen aus der Seite speichern (zusätzlich entfernen und trotz Automatik behalten).
    Gibt die bereinigte Fassung zurück."""
    work = work_folder(output)
    files = read_json(work / "plan_review.json", {}).get("files", [])
    sent = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(sent, list) or len(sent) != len(files):
        raise ValueError("Die Zahl der Aufnahmen passt nicht.")
    cleaned = [plan_review.clean_ranges(r if isinstance(r, list) else [], f["duration"])
               for r, f in zip(sent, files)]
    if "keep" in payload:
        kept = payload["keep"]
        if not isinstance(kept, list) or len(kept) != len(files):
            raise ValueError("Die Zahl der Aufnahmen passt nicht.")
        kept = [plan_review.clean_keeps(r if isinstance(r, list) else [], f["duration"])
                for r, f in zip(kept, files)]
    else:  # ältere Seite ohne Behalten-Liste: vorhandene Angaben nicht verlieren
        kept = [plan_review.clean_keeps(r, f["duration"])
                for r, f in zip(plan_review.read_keep(work, len(files)), files)]
    plan_review.write_manual(work, cleaned, kept)
    return {"files": cleaned, "keep": kept}


def confirm_plan(output):
    work = work_folder(output)
    if not (work / "plan_review.json").is_file():
        raise ValueError("Dieser Auftrag wartet nicht auf eine Prüfung.")
    plan_review.confirm(work)


def byte_range(header, size):
    """HTTP-Range-Kopf ("bytes=a-b") -> (start, ende) inklusive; None = ganze Datei; ValueError = ungültig.
    Ohne Range-Unterstützung ließe sich im Video nicht springen."""
    if not header:
        return None
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
    if not match or not (match.group(1) or match.group(2)):
        raise ValueError("Range")
    if match.group(1):
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else size - 1
    else:  # "bytes=-500": die letzten 500 Bytes
        start, end = max(0, size - int(match.group(2))), size - 1
    end = min(end, size - 1)
    if start > end or start >= size:
        raise ValueError("Range")
    return start, end


def theme_css(name="system"):
    """CSS-Variablen aus den Farbpaletten des Programms (theme.py): VODWerft bekommt seine Markenfarben
    (Schwarz, Anthrazit, Rot), VODWerft seine. So gibt es nur eine Quelle für Farben.

    name: "dunkel", "hell" oder "system" (folgt dem Farbschema von Windows bzw. des Browsers)."""
    block = lambda colors: ";".join(f"--{key.replace('_', '-')}:{value}" for key, value in colors.items())
    if name == "hell":
        return ":root{" + block(theme.LIGHT) + "}"
    if name == "dunkel":
        return ":root{" + block(theme.DARK) + "}"
    return (":root{" + block(theme.DARK) + "}"
            "@media (prefers-color-scheme: light){:root{" + block(theme.LIGHT) + "}}")


def page_html(theme_name="system"):
    return UI_FILE.read_text(encoding="utf-8").replace("/*BRAND*/", theme_css(theme_name))


# ---- Proxys im Hintergrund erzeugen -------------------------------------------------------------

class ProxyJob(threading.Thread):
    """Erzeugt im Hintergrund den Mix-Ton (immer) und den Proxy (nur wenn die Seite ihn anfordert)."""

    def __init__(self, output, ffmpeg_dir=None):
        super().__init__(daemon=True)
        self.output, self.progress, self.audio_progress, self.error = output, {}, {}, None
        self.want_proxy = threading.Event()  # die Seite kann das Original nicht abspielen
        exe = lambda name: str(Path(ffmpeg_dir) / name) if ffmpeg_dir else shutil.which(name) or name
        self.ffmpeg, self.ffprobe = exe("ffmpeg"), exe("ffprobe")

    def run(self):
        work = work_folder(self.output)
        try:
            files = read_json(work / "plan_review.json", {}).get("files", [])
            infos = []
            for n, f in enumerate(files):
                info = proxy.probe(f["source"], self.ffprobe)
                infos.append(info)
                if info["audio_streams"]:
                    proxy.create_audio(f["source"], proxy.audio_path(work, n), f["duration"],
                                       audio_streams=info["audio_streams"], ffmpeg=self.ffmpeg,
                                       on_progress=lambda x, n=n: self.audio_progress.__setitem__(n, x))
                self.audio_progress[n] = 1.0
            # Der Proxy kostet bei langen Aufnahmen Zeit und wird nur gebraucht, wenn das Original nicht abspielbar ist.
            self.want_proxy.wait()
            for n, f in enumerate(files):
                proxy.create(f["source"], proxy.proxy_path(work, n), f["duration"], height=infos[n]["height"],
                             audio_streams=infos[n]["audio_streams"], ffmpeg=self.ffmpeg,
                             on_progress=lambda x, n=n: self.progress.__setitem__(n, x))
                self.progress[n] = 1.0
        except Exception as error:  # in der Seite anzeigen statt still zu sterben
            self.error = f"{type(error).__name__}: {str(error)[:200]}"


# ---- HTTP-Hülle ---------------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, app, **kwargs):
        self.app = app
        super().__init__(*args, **kwargs)

    def log_message(self, *args):  # keine Konsolenausgabe
        pass

    def send_bytes(self, status, body, kind, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data, status=200):
        self.send_bytes(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json")

    def authorized(self):
        query = parse_qs(urlparse(self.path).query)
        return secrets.compare_digest(query.get("token", [""])[0], self.app.token)

    def do_GET(self):
        if not self.authorized():
            return self.send_json({"error": "Nicht erlaubt"}, 403)
        self.app.last_seen = time.monotonic()  # Lebenszeichen: die Seite ist offen
        path = urlparse(self.path).path
        if path == "/api/ping":
            return self.send_json({"ok": True})
        if path == "/":
            return self.send_bytes(200, page_html(self.app.theme).encode("utf-8"), "text/html; charset=utf-8")
        if path == "/api/state":
            state = build_state(self.app.output, self.app.job.progress, self.app.job.audio_progress)
            state["error"] = self.app.job.error
            return self.send_json(state)
        match = re.fullmatch(r"/(proxy|audio|original)/(\d+)", path)
        if match:
            return self.send_media(match.group(1), int(match.group(2)))
        self.send_json({"error": "Nicht gefunden"}, 404)

    def send_media(self, kind, n):
        """Proxy, Mix-Ton oder Original der n-ten Aufnahme, mit Range-Unterstützung (nötig zum Springen)."""
        work = work_folder(self.app.output)
        if kind == "proxy":
            file, mime = proxy.proxy_path(work, n), "video/mp4"
        elif kind == "audio":
            file, mime = proxy.audio_path(work, n), "audio/mp4"
        else:  # Original: nur eine Aufnahme, die in plan_review.json steht (kein freier Dateipfad)
            files = read_json(work / "plan_review.json", {}).get("files", [])
            if not 0 <= n < len(files):
                return self.send_json({"error": "Nicht gefunden"}, 404)
            file = Path(files[n]["source"])
            mime = ORIGINAL_TYPES.get(file.suffix.lower(), "application/octet-stream")
        if not file.is_file():
            return self.send_json({"error": "Datei noch nicht fertig"}, 404)
        size = file.stat().st_size
        try:
            span = byte_range(self.headers.get("Range"), size)
        except ValueError:
            return self.send_bytes(416, b"", "text/plain", {"Content-Range": f"bytes */{size}"})
        start, end = span or (0, size - 1)
        self.send_response(206 if span else 200)
        self.send_header("Content-Type", mime)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if span:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        try:
            with file.open("rb") as handle:
                handle.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = handle.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (ConnectionError, OSError):
            pass  # der Browser bricht beim Springen laufend Anfragen ab

    def do_POST(self):
        if not self.authorized():
            return self.send_json({"error": "Nicht erlaubt"}, 403)
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > 1_000_000:
                raise ValueError("Anfrage zu groß")
            body = json.loads(self.rfile.read(length) or b"{}")
            if path == "/api/manual":
                return self.send_json(save_manual(self.app.output, body))
            if path == "/api/proxy":  # die Seite kann das Original nicht abspielen: Proxy erzeugen
                self.app.job.want_proxy.set()
                return self.send_json({"ok": True})
            if path == "/api/confirm":
                if isinstance(body, dict) and "files" in body:
                    save_manual(self.app.output, body)  # letzten Stand mitnehmen
                confirm_plan(self.app.output)
                self.send_json({"ok": True})
                threading.Thread(target=self.app.server.shutdown, daemon=True).start()
                return
        except (ValueError, KeyError) as error:
            return self.send_json({"error": str(error)}, 400)
        self.send_json({"error": "Nicht gefunden"}, 404)


class App:
    def __init__(self, output, ffmpeg_dir=None, theme_name="system"):
        self.output, self.token, self.theme = Path(output), secrets.token_urlsafe(24), theme_name
        self.job = ProxyJob(self.output, ffmpeg_dir)
        self.started = time.monotonic()
        self.last_seen = None  # Zeitpunkt der letzten Anfrage der Seite (Lebenszeichen), None = noch nie geöffnet
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, app=self))

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}/?token={self.token}"


def find_browser():
    """Edge (auf jedem Windows 10/11), sonst Chrome."""
    for name in ("msedge", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    for base in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                 r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                 r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        if Path(base).is_file():
            return base
    return None


def main():
    parser = argparse.ArgumentParser(description="Plan prüfen: Fenster zum Entfernen von Bereichen")
    parser.add_argument("output", type=Path, help="Ausgabeordner des Auftrags (enthält den Ordner nightcut)")
    parser.add_argument("--ffmpeg-dir")
    parser.add_argument("--theme", choices=("dunkel", "hell", "system"), default="system",
                        help="Farbschema wie im Dashboard")
    parser.add_argument("--no-window", action="store_true", help="Nur Adresse ausgeben (Tests)")
    args = parser.parse_args()
    if not (work_folder(args.output) / "plan_review.json").is_file():
        sys.exit("Dieser Auftrag wartet nicht auf eine Prüfung.")
    log_file = work_folder(args.output) / "plan-server.log"  # unter pythonw gibt es keine Konsole: Fehler gehören in eine Datei
    try:
        app = App(args.output, args.ffmpeg_dir, args.theme)
        app.job.start()
        write_log(log_file, "Gestartet: " + app.url.split("?")[0])
        if sys.stdout:  # pythonw hat keine Ausgabe
            print(app.url, flush=True)
        browser = None if args.no_window else find_browser()
        if browser:
            # eigener Profilordner, damit das App-Fenster nicht in ein laufendes Edge-Fenster übergeht
            profile = Path(args.output) / "nightcut" / "browser-profile"
            subprocess.Popen([browser, f"--app={app.url}", f"--user-data-dir={profile}",
                              "--window-size=1280,860", "--no-first-run"])
            # Nicht auf den Edge-Prozess warten: Edge startet sich unter Administratorrechten neu und der erste
            # Prozess endet sofort, obwohl das Fenster offen bleibt. Maßgeblich ist das Lebenszeichen der Seite.
            threading.Thread(target=watchdog, args=(app, log_file), daemon=True).start()
        try:
            app.server.serve_forever()
        finally:
            proxy.stop_all()  # keine ffmpeg-Waisen hinterlassen (sie würden das Update blockieren)
            write_log(log_file, "Beendet.")
    except Exception:
        write_log(log_file, traceback.format_exc())
        raise
    return


def write_log(path, text):
    try:
        with Path(path).open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%H:%M:%S')} {text}\n")
    except OSError:
        pass


def watchdog(app, log_file, *, tick=5.0, closed_after=90.0, never_opened_after=600.0):
    """Beendet den Server, wenn die Seite zu ist (kein Lebenszeichen mehr) oder nie geöffnet wurde."""
    while True:
        time.sleep(tick)
        now = time.monotonic()
        if app.last_seen is None:
            if now - app.started > never_opened_after:
                write_log(log_file, "Seite wurde nie geöffnet: Server beendet.")
                break
        elif now - app.last_seen > closed_after:
            write_log(log_file, "Kein Lebenszeichen der Seite mehr: Server beendet.")
            break
    app.server.shutdown()


if __name__ == "__main__":
    main()
