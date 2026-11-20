"""Read and edit the Windows watcher's game profiles."""
import hashlib
import json
import re
from pathlib import Path

import yaml

import description_template
import transitions
import youtube_fields
from atomic import atomic_write
from game_library import find as find_preset
from retention import write
from thumbnail_theme import sanitize_theme

# Schlüssel des Clip-Stils (Vertrag mit dem Profil-Editor). Die Werte prüft und begrenzt
# nightcut.shorts.caption_style beim Rendern; hier wird nur die Form gesichert.
CAPTION_STYLE_KEYS = ("font", "font_size", "primary_color", "highlight_color", "outline_color", "outline",
                      "box", "box_color", "box_opacity", "words_per_caption", "position", "uppercase")
THUMBNAIL_THEME_KEYS = ("accent", "text_color", "background", "font", "show_bar", "duration_badge")
# Programmweite Angaben stehen nur in der Hauptdatei; Zusatzprofile erben sie, wenn sie dort fehlen.
# upload_incoming gehört bewusst nicht dazu: Fehlt es in einem Profil, heißt das "nicht hochladen".
INHERITED_KEYS = ("ffmpeg_directory", "ollama")


UNCHANGED = object()  # Aufrufer, die den Übergang nicht kennen, lassen ihn, wie er ist


def read_settings(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def profile_paths(main):
    settings = read_settings(main)
    return [main, *(Path(name) for name in settings.get("additional_profiles", []))]


def load_profiles(main):
    profiles = [read_settings(path) for path in profile_paths(main)]
    root = profiles[0]
    for profile in profiles[1:]:
        for key in INHERITED_KEYS:
            if key in root and key not in profile:
                profile[key] = root[key]
    return profiles


def recording_settings(config, key, *, save=False):
    path = Path(config["work"]) / f"{key}.profile.json"
    if path.is_file():
        return read_settings(path)
    if save:
        write(path, config)
    return config


def render_settings(config):
    data = yaml.safe_load(Path(config["nightcut_config"]).read_text(encoding="utf-8-sig"))
    return data["letsplay"]


def save_profile(main, path, *, minutes, mode, audio_track, split, style, manual, weekdays,
                 approval=False, mission_start=False, plan_review=False, transition=UNCHANGED, clone_name=None, caption_style=None, thumbnail_theme=None,
                 youtube=UNCHANGED):
    """Speichert ein Profil. caption_style: None lässt den vorhandenen Clip-Stil unverändert (beim Klonen wird
    er mitkopiert), ein Dict ersetzt ihn, ein leeres Dict entfernt ihn (Standard-Stil)."""
    if caption_style is not None and not isinstance(caption_style, dict):
        raise ValueError("Der Clip-Stil hat ein ungültiges Format.")
    if (mode not in ("by_length", "per_recording") or not 5 <= minutes <= 180
            or not 0 <= audio_track <= 15 or style not in ("numbered", "project")
            or not manual and not weekdays or any(day not in range(7) for day in weekdays)):
        raise ValueError("Bitte Folgenlänge, Tonspur und Wochentage prüfen.")
    config = read_settings(path)
    root = read_settings(main)
    if clone_name is not None:
        name = clone_name.strip()
        if (not re.fullmatch(r"[\w][\w .&()+’'-]{0,69}", name) or name.endswith(".")
                or re.fullmatch(r"(?i)(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?", name)):
            raise ValueError("Bitte einen gültigen Spielnamen als Ordnernamen angeben.")
        if any(other["series"].casefold() == name.casefold() for other in load_profiles(main)):
            raise ValueError("Ein Profil mit diesem Namen ist bereits vorhanden.")
        prefix = "g" + hashlib.sha256(name.casefold().encode()).hexdigest()[:8]
        work = Path(root["work"]) / prefix
        inbox = Path(root["input"]).parent / name
        clips = Path(root["upload_incoming"]).parent / "Clips" / name
        path = main.parent / f"{prefix}.json"
        if path.exists() or work.exists() or inbox.exists() or clips.exists():
            raise ValueError("Ein zugehöriger Ordner oder ein Profil existiert bereits.")
        # Copy processing defaults and avoid carrying over game-specific release or mission rules.
        for key in ("additional_profiles", "initial_recording", "mission_export", "description", "title_suffix",
                    "publish_after_date", "recording_date", "retention_hold", "retention_enabled", "upload_gate",
                    "youtube_playlist", "youtube_tags", "collab_partners"):
            config.pop(key, None)
        game = work / "game.yaml"
        config.update(series=name, job_prefix=prefix, input=str(inbox), work=str(work),
                      clips_output=str(clips), first_episode=1, profile=str(game),
                      upload_gate=root.get("upload_gate"))
        work.mkdir()
        inbox.mkdir()
        clips.mkdir(parents=True)  # der Sammelordner "Clips" fehlt bei einer frischen Installation noch
        preset = find_preset(name)
        if preset:
            # Fertiges Profil aus der Spiele-Bibliothek; der Entwickler wandert in die Profildatei.
            if preset.get("developer"):
                config["developer"] = preset["developer"]
            profile = {key: value for key, value in preset.items() if key != "developer"}
            profile["name"] = name
        else:
            profile = {"name": name, "keywords": {}, "vision_hints": name}
        game.write_text(yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8")
        # Neue Spiele bekommen gleich eine eigene Beschreibungsvorlage (bearbeitbar im Profil-Editor).
        description = main.parent / f"{prefix}-description.txt"
        description_template.write_text(description, description_template.default_text(name, config.get("developer")))
        config["description"] = str(description)
    elif config.get("mission_export") and mode != "per_recording":
        raise ValueError("Das vorhandene Missionsprofil erstellt genau eine Folge pro Aufnahme.")
    if split and not config.get("split_clips_config"):
        config["split_clips_config"] = str(main.parent.parent / "obs-six-track-clips.yaml")
    source = Path(config["nightcut_config"])
    data = yaml.safe_load(source.read_text(encoding="utf-8-sig"))
    data["letsplay"].update(episodes=mode, episode_minutes=minutes)
    contents = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    revision = hashlib.sha256(contents.encode()).hexdigest()[:16]
    revisions = main.parent / "profile-revisions"
    revisions.mkdir(exist_ok=True)
    effective = revisions / f"{revision}.yaml"
    if not effective.exists():
        atomic_write(effective, contents)
    config.update(nightcut_config=str(effective), audio_track=audio_track, obs_split_audio=split,
                  thumbnail_style=style, manual_release=manual, publish_weekdays=weekdays,
                  require_approval=approval, require_mission_start=bool(mission_start and config.get("mission_export")))
    # Übergang an Schnitten: None = "wie in den Einstellungen" (Schlüssel entfernen), sonst die Art; UNCHANGED lässt ihn
    if transition is not UNCHANGED:
        if transition is None:
            config.pop("uebergang", None)
        elif transitions.valid(transition):
            config["uebergang"] = transition
        else:
            raise ValueError("Unbekannter Übergang.")
    # "Plan prüfen": nur ein Haken schreibt den Schlüssel. Ohne Haken und ohne früheren Eintrag gilt die globale
    # Einstellung weiter; wer den Haken wieder entfernt, bekommt ein ausdrückliches "aus" für dieses Spiel.
    if plan_review:
        config["plan_pruefen"] = True
    elif "plan_pruefen" in config:
        config["plan_pruefen"] = False
    # YouTube-Angaben (Playlist, feste Tags, Collab-Partner): leer entfernt den Eintrag, UNCHANGED lässt ihn
    # (beim Duplizieren zeigt der Editor die Angaben des Quellprofils: das neue Spiel bekommt sie nie)
    if youtube is not UNCHANGED and clone_name is None:
        if not isinstance(youtube, dict):
            raise ValueError("Die YouTube-Angaben haben ein ungültiges Format.")
        playlist = (youtube.get("playlist") or "").strip()
        if playlist and not youtube_fields.playlist_id(playlist):
            raise ValueError("Die Playlist-Kennung oder der Link ist ungültig. "
                             "Beispiel: https://www.youtube.com/playlist?list=PL…")
        if any("=" not in part for part in re.split(r"[;\n]", youtube.get("collab") or "") if part.strip()):
            raise ValueError("Collab-Partner: bitte „Suchtext = Kanalname“ schreiben, mehrere mit Semikolon.")
        for key, value in (("youtube_playlist", youtube_fields.playlist_id(playlist)),
                           ("youtube_tags", youtube_fields.parse_tags(youtube.get("tags"))),
                           ("collab_partners", youtube_fields.parse_collab(youtube.get("collab")))):
            if value:
                config[key] = value
            else:
                config.pop(key, None)
    if caption_style is not None:
        block = {key: caption_style[key] for key in CAPTION_STYLE_KEYS if key in caption_style}
        if block:
            config["caption_style"] = block
        else:
            config.pop("caption_style", None)
    if thumbnail_theme is not None:
        if not isinstance(thumbnail_theme, dict):
            raise ValueError("Der Thumbnail-Stil muss ein Objekt sein")
        block = sanitize_theme(thumbnail_theme)
        if block:
            config["thumbnail_theme"] = block
        else:
            config.pop("thumbnail_theme", None)
    write(path, config)
    if clone_name is not None:
        root.setdefault("additional_profiles", []).append(str(path))
        write(main, root)
    return path
