"""Persist YouTube resumable sessions and receipts on the uploader volume."""
import json
import mimetypes
import re
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


API = "https://www.googleapis.com"
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
CHUNK_SIZE = 8 * 1024 * 1024


class UploadError(Exception):
    def __init__(self, reason, *, retry=False, auth=False):
        super().__init__(reason)
        self.reason, self.retry, self.auth = reason, retry, auth


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def request(method, url, *, headers=None, body=None):
    try:
        response = build_opener(NoRedirect()).open(
            Request(url, data=body, headers=headers or {}, method=method), timeout=90)
    except HTTPError as error:
        response = error
    except (URLError, TimeoutError, OSError, HTTPException):
        raise UploadError("network_interrupted", retry=True) from None
    with response:
        try:
            return response.code, response.headers, response.read(1024 * 1024)
        except (OSError, TimeoutError, HTTPException):
            raise UploadError("network_interrupted", retry=True) from None


def payload(raw):
    try:
        value = json.loads(raw)
        if isinstance(value, dict):
            return value
    except (ValueError, UnicodeError):
        pass
    return {}


def require(code, raw, operation):
    if code in (200, 201):
        return
    if code == 401 or payload(raw).get("error") in ("invalid_grant", "invalid_client"):
        raise UploadError("youtube_auth_required", auth=True)
    error = payload(raw).get("error")
    reasons = {item.get("reason") for item in error.get("errors", []) if isinstance(item, dict)} if isinstance(error, dict) else set()
    if code in (408, 429, 500, 502, 503, 504) or reasons.intersection({"rateLimitExceeded", "userRateLimitExceeded"}):
        raise UploadError("youtube_temporarily_unavailable", retry=True)
    raise UploadError(f"{operation}_http_{code}")


def session_url(url):
    if not isinstance(url, str):
        return False
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.netloc == "www.googleapis.com"
            and parsed.path == "/upload/youtube/v3/videos" and bool(parsed.query)
            and not parsed.fragment)


def video_resource(meta):
    snippet = {key: meta[key] for key in ("title", "description", "categoryId", "tags") if key in meta}
    if meta.get("language"):
        snippet["defaultLanguage"] = meta["language"]
        snippet["defaultAudioLanguage"] = meta["language"]
    status = {key: meta[key] for key in ("privacyStatus", "publishAt", "embeddable",
                                        "license", "publicStatsViewable", "selfDeclaredMadeForKids",
                                        "containsSyntheticMedia") if key in meta}
    result = {"snippet": snippet, "status": status}
    if meta.get("recordingDate"):
        date = meta["recordingDate"]
        result["recordingDetails"] = {"recordingDate": date + "T00:00:00Z" if len(date) == 10 else date}
    return result


class YouTube:
    def __init__(self, token_path, client_path, transport=request):
        self.token_path, self.client_path, self.transport = token_path, client_path, transport
        self.access = None
        self.expiry = datetime.min.replace(tzinfo=timezone.utc)

    def authorization(self):
        now = datetime.now(timezone.utc)
        if self.access and self.expiry > now + timedelta(seconds=120):
            return {"Authorization": "Bearer " + self.access}
        try:
            token = json.loads(self.token_path.read_text(encoding="utf-8"))
            clients = json.loads(self.client_path.read_text(encoding="utf-8"))
            client = clients.get("installed") or clients["web"]
            body = urlencode({"grant_type": "refresh_token", "refresh_token": token["refresh_token"],
                              "client_id": client["client_id"], "client_secret": client["client_secret"]}).encode()
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise UploadError("youtube_auth_required", auth=True) from None
        code, _, raw = self.transport("POST", "https://oauth2.googleapis.com/token", body=body,
                                      headers={"Content-Type": "application/x-www-form-urlencoded"})
        require(code, raw, "token_refresh")
        response = payload(raw)
        try:
            self.access = response["access_token"]
            self.expiry = now + timedelta(seconds=int(response["expires_in"]))
            if not isinstance(self.access, str) or not self.access:
                raise ValueError
        except (KeyError, ValueError, TypeError):
            raise UploadError("token_response_invalid", retry=True) from None
        return {"Authorization": "Bearer " + self.access}

    def call(self, method, url, *, headers=None, body=None):
        return self.transport(method, url, headers={**self.authorization(), **(headers or {})}, body=body)

    def thumbnail(self, video_id, cover):
        if not VIDEO_ID.fullmatch(video_id):
            raise UploadError("receipt_invalid")
        mime = mimetypes.guess_type(cover.name)[0] or "application/octet-stream"
        code, _, raw = self.call("POST", f"{API}/upload/youtube/v3/thumbnails/set?"
                                 + urlencode({"videoId": video_id, "uploadType": "media"}),
                                 headers={"Content-Type": mime}, body=cover.read_bytes())
        require(code, raw, "thumbnail")


def upload(api, video, meta, job, write_json, progress=lambda _offset, _total: None):
    receipt = job / "receipt.json"
    if receipt.is_file():
        result = payload(receipt.read_bytes())
        if not VIDEO_ID.fullmatch(str(result.get("id", ""))):
            raise UploadError("receipt_invalid")
        return result

    fingerprint = video.stat()
    total = fingerprint.st_size
    identity = [total, fingerprint.st_mtime_ns, fingerprint.st_ino]
    if not total:
        raise UploadError("empty_video")
    session = job / "session.json"
    mime = mimetypes.guess_type(video.name)[0] or "application/octet-stream"
    if session.is_file():
        saved = payload(session.read_bytes())
        url = saved.get("url")
        if not session_url(url) or saved.get("file") != identity or saved.get("metadata") != meta:
            raise UploadError("saved_session_does_not_match")
        response = api.call("PUT", url, headers={"Content-Range": f"bytes */{total}"}, body=b"")
    else:
        resource = video_resource(meta)
        query = urlencode({"part": ",".join(resource), "uploadType": "resumable", "notifySubscribers": "false"})
        code, headers, raw = api.call(
            "POST", f"{API}/upload/youtube/v3/videos?{query}",
            headers={"Content-Type": "application/json", "X-Upload-Content-Type": mime,
                     "X-Upload-Content-Length": str(total)}, body=json.dumps(resource).encode())
        require(code, raw, "session_start")
        url = headers.get("Location")
        if not session_url(url):
            raise UploadError("session_location_invalid")
        write_json(session, {"url": url, "file": identity, "metadata": meta}, mode=0o600)
        response = (308, {}, b"")

    offset = None
    with video.open("rb") as source:
        while True:
            code, headers, raw = response
            if code in (200, 201):
                result = payload(raw)
                if not VIDEO_ID.fullmatch(str(result.get("id", ""))):
                    raise UploadError("youtube_confirmation_missing", retry=True)
                write_json(receipt, result, mode=0o600)
                progress(total, total)
                return result
            if code in (404, 410):
                raise UploadError("youtube_session_expired_or_unknown")
            if code != 308:
                require(code, raw, "upload")
            received = headers.get("Range")
            match = re.fullmatch(r"bytes=0-(\d+)", received or "")
            confirmed = int(match[1]) + 1 if match else 0
            if received and not match or not (offset or 0) <= confirmed <= total:
                raise UploadError("youtube_offset_invalid")
            if confirmed == total or confirmed == offset:
                raise UploadError("youtube_confirmation_pending", retry=True)
            progress(confirmed, total)
            source.seek(confirmed)
            chunk = source.read(min(CHUNK_SIZE, total - confirmed))
            current = video.stat()
            if len(chunk) != min(CHUNK_SIZE, total - confirmed) or identity != [
                    current.st_size, current.st_mtime_ns, current.st_ino]:
                raise UploadError("upload_file_changed")
            offset = confirmed
            response = api.call("PUT", url, headers={"Content-Type": mime, "Content-Range":
                                f"bytes {confirmed}-{confirmed + len(chunk) - 1}/{total}"}, body=chunk)
