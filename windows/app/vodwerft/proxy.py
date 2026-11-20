"""Proxys und Mix-Ton: Hilfsdateien für die Prüfoberfläche "Plan prüfen".

Zwei Dinge können nötig sein:
- Mix-Ton: alle Tonspuren zu einer gemischt (ein Browser spielt sonst nur die erste Spur, bei OBS meist
  nur das Mikrofon). Das geht schnell (rund 60-fache Geschwindigkeit) und wird immer erzeugt.
- Proxy: ein kleines 720p-H.264-Video, wenn der Browser das Original nicht abspielen kann (z. B. HEVC).
  Läuft bevorzugt auf der Grafikkarte (NVIDIA, NVDEC + NVENC) und fällt sonst auf den Prozessor zurück.

Der finale Schnitt nutzt weiterhin das Original; beides dient nur zum Ansehen.

Wichtig: Die Zeitbasis bleibt gleich (keine Bildraten-Umrechnung, Audio nicht verschoben),
damit eine Markierung bei 1:21:00 in der Vorschau auch im Original bei 1:21:00 liegt.

Reine Logik ohne Tk. Nur `create` und `create_audio` starten ffmpeg; Befehlsbau und Fortschritt sind testbar.
"""
import functools
import json
import re
import subprocess
import tempfile
from pathlib import Path

PROXY_HEIGHT = 720
# Dieses Programm läuft ohne Konsole (pythonw). Ohne diese Marke öffnet Windows für jedes ffmpeg/ffprobe
# ein eigenes schwarzes Konsolenfenster.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def proxy_path(work, n):
    """Ablageort des Proxys der n-ten Aufnahme (n zählt ab 0) im Arbeitsordner eines Auftrags."""
    return Path(work) / "proxy" / f"proxy_{int(n):02d}.mp4"


def audio_path(work, n):
    """Ablageort des Mix-Tons der n-ten Aufnahme."""
    return Path(work) / "proxy" / f"audio_{int(n):02d}.m4a"


def _mix(audio_streams):
    """(filter_complex-Teil, map-Ziel) für den Ton: eine Spur direkt, mehrere gemischt."""
    if audio_streams == 1:
        return None, "0:a:0"
    inputs = "".join(f"[0:a:{i}]" for i in range(audio_streams))
    return f"{inputs}amix=inputs={audio_streams}:normalize=0[mix]", "[mix]"


def build_command(src, dst, *, height=None, audio_streams=1, ffmpeg="ffmpeg", gpu=False):
    """ffmpeg-Aufruf für einen Proxy.

    height: Höhe des Originals. Ist sie bekannt und kleiner als 720, wird nicht hochskaliert.
    audio_streams: Anzahl der Tonspuren des Originals; mehrere werden zu einer Spur gemischt.
    gpu: NVIDIA-Grafikkarte zum Entschlüsseln, Verkleinern und Verschlüsseln benutzen.
    """
    if audio_streams < 0:
        raise ValueError("Die Zahl der Tonspuren darf nicht negativ sein.")
    small = bool(height and height <= PROXY_HEIGHT)
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    if gpu:
        cmd += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
    cmd += ["-i", str(src), "-map", "0:v:0"]
    if gpu:
        # format=nv12: auch 10-Bit-Quellen werden für H.264 auf 8 Bit gebracht
        target = height if small else PROXY_HEIGHT
        cmd += ["-vf", f"scale_cuda=-2:{target}:format=nv12"]
        cmd += ["-c:v", "h264_nvenc", "-preset", "p1", "-rc", "vbr", "-cq", "32", "-b:v", "0",
                "-maxrate", "4M", "-bufsize", "8M", "-g", "30"]
    else:
        if not small:
            cmd += ["-vf", f"scale=-2:{PROXY_HEIGHT}"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p", "-g", "30"]
    # passthrough: keine Bilder doppeln oder auslassen, damit die Zeitstempel 1:1 bleiben
    cmd += ["-fps_mode", "passthrough"]
    if audio_streams:
        graph, target = _mix(audio_streams)
        if graph:
            cmd += ["-filter_complex", graph]
        cmd += ["-map", target, "-c:a", "aac", "-b:a", "128k", "-ac", "2"]
    cmd += ["-movflags", "+faststart", "-progress", "pipe:1", "-f", "mp4", str(dst)]
    return cmd


def build_audio_command(src, dst, *, audio_streams=1, ffmpeg="ffmpeg"):
    """ffmpeg-Aufruf für den Mix-Ton (nur Ton, alle Spuren zu einer gemischt)."""
    if audio_streams < 1:
        raise ValueError("Die Aufnahme hat keine Tonspur.")
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(src), "-vn"]
    graph, target = _mix(audio_streams)
    if graph:
        cmd += ["-filter_complex", graph]
    return cmd + ["-map", target, "-c:a", "aac", "-b:a", "128k", "-ac", "2",
                  "-movflags", "+faststart", "-progress", "pipe:1", "-f", "mp4", str(dst)]


def parse_probe(text):
    """Höhe und Zahl der Tonspuren aus der JSON-Ausgabe von ffprobe (-show_streams)."""
    streams = json.loads(text).get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    return {"height": int(video.get("height") or 0) or None,
            "audio_streams": sum(1 for s in streams if s.get("codec_type") == "audio")}


def probe(src, ffprobe="ffprobe"):
    out = subprocess.run([ffprobe, "-v", "error", "-show_streams", "-of", "json", str(src)],
                         capture_output=True, text=True, encoding="utf-8", check=True,
                         creationflags=NO_WINDOW).stdout
    return parse_probe(out)


def progress_fraction(line, duration):
    """Anteil 0..1 aus einer ffmpeg-Fortschrittszeile (`out_time_us=…`), sonst None."""
    match = re.fullmatch(r"out_time_(?:us|ms)=(\d+)", line.strip())
    if not match or duration <= 0:
        return None
    # beide Felder liefert ffmpeg in Mikrosekunden (out_time_ms heißt nur so)
    return max(0.0, min(1.0, int(match.group(1)) / 1e6 / duration))


@functools.lru_cache(maxsize=None)
def has_nvenc(ffmpeg="ffmpeg"):
    """Kennt dieses ffmpeg den NVIDIA-Encoder? (Ob die Karte wirklich nutzbar ist, zeigt erst der Versuch.)"""
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=20, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "h264_nvenc" in out


_running = set()    # laufende ffmpeg-Prozesse dieses Programms
_stopping = False   # wird beim Beenden gesetzt: keine neuen Versuche mehr


def stop_all():
    """Alle laufenden ffmpeg-Prozesse beenden. Beim Schließen des Prüffensters sonst als Waisen weiterlaufen:
    Sie belegen Prozessor und Grafikkarte und blockieren sogar das Update ("es läuft gerade eine Bearbeitung")."""
    global _stopping
    _stopping = True
    for process in list(_running):
        try:
            process.kill()
        except OSError:
            pass


def _run(cmd, part, duration, on_progress):
    """ffmpeg starten, Fortschritt melden. Bei Fehler: RuntimeError mit dem Ende der Fehlermeldung."""
    if _stopping:
        raise RuntimeError("abgebrochen")
    # Fehlermeldungen in eine Temp-Datei statt in eine zweite Pipe: Wer erst stdout bis zum Ende liest und danach
    # stderr, blockiert ffmpeg, sobald es mehr als den Pipe-Puffer (ca. 4 KB) an Fehlern schreibt (beschädigte
    # Aufnahme) - die Vorschau bliebe dann für immer bei x % stehen.
    errors = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errors, text=True, encoding="utf-8",
                               creationflags=NO_WINDOW)
    _running.add(process)
    try:
        for line in process.stdout:
            fraction = progress_fraction(line, duration)
            if fraction is not None and on_progress:
                on_progress(fraction)
        if process.wait() != 0:
            errors.seek(0)
            raise RuntimeError(errors.read().strip()[-300:] or f"ffmpeg Code {process.returncode}")
    except BaseException:
        process.kill()
        Path(part).unlink(missing_ok=True)
        raise
    finally:
        _running.discard(process)
        errors.close()


def _finish(part, dst, on_progress):
    part.replace(dst)
    if on_progress:
        on_progress(1.0)
    return dst


def create(src, dst, duration, *, height=None, audio_streams=1, on_progress=None, ffmpeg="ffmpeg", gpu="auto"):
    """Proxy erzeugen. Schreibt erst in eine .part-Datei, damit nie ein halber Proxy als fertig gilt.

    gpu: "auto" (Grafikkarte versuchen, bei Fehler Prozessor), True (nur Grafikkarte), False (nur Prozessor).
    """
    dst = Path(dst)
    if dst.is_file() and dst.stat().st_size > 0:
        return dst  # schon vorhanden (z. B. nach einem Neustart)
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_name(dst.name + ".part")
    if gpu == "auto":
        attempts = [True, False] if has_nvenc(ffmpeg) else [False]
    else:
        attempts = [bool(gpu)]
    error = None
    for use_gpu in attempts:
        cmd = build_command(src, part, height=height, audio_streams=audio_streams, ffmpeg=ffmpeg, gpu=use_gpu)
        try:
            _run(cmd, part, duration, on_progress)
            return _finish(part, dst, on_progress)
        except RuntimeError as failure:
            error = failure  # Grafikkarte ging nicht (Treiber, Codec): nächster Versuch auf dem Prozessor
            if _stopping:
                break  # Programm wird beendet: kein zweiter Versuch
            if on_progress:
                on_progress(0.0)
    raise RuntimeError(f"Proxy konnte nicht erzeugt werden: {error}")


def create_audio(src, dst, duration, *, audio_streams=1, on_progress=None, ffmpeg="ffmpeg"):
    """Mix-Ton erzeugen (über .part, wie beim Proxy)."""
    dst = Path(dst)
    if dst.is_file() and dst.stat().st_size > 0:
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_name(dst.name + ".part")
    try:
        _run(build_audio_command(src, part, audio_streams=audio_streams, ffmpeg=ffmpeg), part, duration, on_progress)
    except RuntimeError as failure:
        raise RuntimeError(f"Mix-Ton konnte nicht erzeugt werden: {failure}") from None
    return _finish(part, dst, on_progress)


def remove_proxies(work):
    """Proxys und Mix-Ton eines Auftrags löschen (nach dem Rendern). Gibt die freigegebenen Bytes zurück."""
    folder = Path(work) / "proxy"
    freed = 0
    if folder.is_dir():
        for file in folder.iterdir():
            if file.is_file():
                freed += file.stat().st_size
                file.unlink()
        folder.rmdir()
    return freed
