"""YouTube-Anmeldung fuer den Direkt-Modus (ohne Zusatzprogramm).

Standard-Verfahren fuer Desktop-Programme: Der Browser oeffnet die Google-Anmeldung, Google ruft danach
http://127.0.0.1:<Port> auf diesem Rechner auf. Das Passwort sieht dieses Programm nie. Gespeichert wird nur das
Anmelde-Token (request.token) im Ordner neben client_secrets.json. Berechtigung: Videos hochladen/Vorschaubilder setzen (mit --playlists zusätzlich Playlists verwalten).
Aufruf:  python youtube_login.py <Ordner mit client_secrets.json> [--playlists]
"""
import base64
import hashlib
import json
import secrets
import sys
import threading
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from resumable_upload import request

SCOPE = "https://www.googleapis.com/auth/youtube.upload"
# Mit diesem Recht kann der Upload-Dienst ein Video auch einer Playlist zuordnen (Profil: "Playlist")
SCOPE_PLAYLISTS = "https://www.googleapis.com/auth/youtube"
PAGE = ("<html><meta charset='utf-8'><body style='font-family:sans-serif;margin:3em'>"
        "<h2>{}</h2><p>Du kannst dieses Fenster schliessen.</p></body></html>")


def load_client(directory):
    data = json.loads((Path(directory) / "client_secrets.json").read_text(encoding="utf-8"))
    client = data.get("installed")
    if not client:
        raise ValueError("client_secrets.json ist kein Client vom Typ 'Desktop-App'")
    for key in ("client_id", "client_secret", "auth_uri", "token_uri"):
        if not client.get(key):
            raise ValueError(f"client_secrets.json: Eintrag {key} fehlt")
    return client


def login(directory, *, opener=webbrowser.open, transport=request, timeout=300, scope=SCOPE):
    directory = Path(directory)
    client = load_client(directory)
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    received = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query)
            ok = query.get("state", [None])[0] == state and "code" in query
            if ok:
                received["code"] = query["code"][0]
            elif "error" in query or "state" in query:
                received["error"] = query.get("error", ["falscher Zustand"])[0]
            else:
                self.send_response(404); self.end_headers(); return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(PAGE.format("Anmeldung erfolgreich" if ok else "Anmeldung abgebrochen").encode())
            done.set()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    redirect = f"http://127.0.0.1:{server.server_port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        opener(client["auth_uri"] + "?" + urlencode({
            "client_id": client["client_id"], "redirect_uri": redirect, "response_type": "code", "scope": scope,
            "access_type": "offline", "prompt": "consent", "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256"}))
        if not done.wait(timeout):
            raise TimeoutError("Keine Anmeldung innerhalb von fuenf Minuten")
    finally:
        server.shutdown()
        server.server_close()
    if "code" not in received:
        raise PermissionError("Anmeldung abgebrochen: " + received.get("error", "unbekannt"))
    body = urlencode({"grant_type": "authorization_code", "code": received["code"], "redirect_uri": redirect,
                      "client_id": client["client_id"], "client_secret": client["client_secret"],
                      "code_verifier": verifier}).encode()
    code, _, raw = transport("POST", client["token_uri"], body=body,
                             headers={"Content-Type": "application/x-www-form-urlencoded"})
    if code != 200:
        raise PermissionError(f"Google hat den Code nicht angenommen (HTTP {code})")
    token = json.loads(raw)
    if not token.get("refresh_token"):
        raise PermissionError("Google hat kein dauerhaftes Token geliefert. Bitte die Anmeldung wiederholen "
                              "und alle Berechtigungen zulassen.")
    expiry = datetime.now(timezone.utc) + timedelta(seconds=int(token.get("expires_in", 3600)))
    saved = {"access_token": token.get("access_token", ""), "token_type": token.get("token_type", "Bearer"),
             "refresh_token": token["refresh_token"], "expiry": expiry.isoformat()}
    target = directory / "request.token"
    temp = target.with_name("request.token.tmp")
    temp.write_text(json.dumps(saved), encoding="utf-8")
    temp.chmod(0o600)
    temp.replace(target)
    return target


if __name__ == "__main__":
    arguments = [a for a in sys.argv[1:] if a != "--playlists"]
    if len(arguments) != 1:
        sys.exit(__doc__)
    try:
        # "--playlists": zusätzlich das Recht, Videos Playlists zuzuordnen
        print("Token gespeichert:", login(arguments[0], scope=SCOPE_PLAYLISTS if "--playlists" in sys.argv else SCOPE))
    except (OSError, ValueError, PermissionError, TimeoutError) as error:
        sys.exit(f"Anmeldung fehlgeschlagen: {error}")
