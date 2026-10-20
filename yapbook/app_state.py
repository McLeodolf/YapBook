"""Validated, atomic local preferences, recent books and named bookmarks."""

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

from .kokoro_tts import DEFAULT_VOICE as DEFAULT_KOKORO_VOICE, VOICES as KOKORO_VOICES


DEFAULT_VOICE = "en-US-BrianMultilingualNeural"
DEFAULT_SETTINGS = {"voice": DEFAULT_VOICE, "rate": 0, "volume": 100,
                    "font_size": 20, "follow": True, "theme": "light", "read_citations": True,
                    "engine": "edge", "kokoro_voice": DEFAULT_KOKORO_VOICE}


def service_rate(display_rate):
    """The reader's comfortable zero point is 15 percentage points slower."""
    return round(display_rate) - 15


def valid_voice(value, engine="edge"):
    if engine == "kokoro":
        return isinstance(value, str) and any(voice["ShortName"] == value for voice in KOKORO_VOICES)
    return isinstance(value, str) and bool(re.fullmatch(r"[a-z]{2,3}-[A-Z]{2}-.+Neural", value))


def text_hash(text):
    return hashlib.sha256(text.replace("\n", " ").encode("utf-8")).hexdigest()


class AppState:
    def __init__(self, path=None):
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        self.path = Path(path) if path is not None else local / "YapBook" / "library.json"
        self.settings = DEFAULT_SETTINGS.copy()
        self.favorites = []
        self.recent = []
        self.bookmarks = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") != 1:
                return
            settings = data.get("settings", {})
            if isinstance(settings, dict):
                if valid_voice(settings.get("voice")):
                    self.settings["voice"] = settings["voice"]
                if settings.get("engine") in ("edge", "kokoro"):
                    self.settings["engine"] = settings["engine"]
                if valid_voice(settings.get("kokoro_voice"), "kokoro"):
                    self.settings["kokoro_voice"] = settings["kokoro_voice"]
                for name, low, high in (("rate", -50, 100), ("volume", 0, 100), ("font_size", 14, 36)):
                    value = settings.get(name)
                    if type(value) is int and low <= value <= high:
                        self.settings[name] = value
                if type(settings.get("follow")) is bool:
                    self.settings["follow"] = settings["follow"]
                if type(settings.get("read_citations")) is bool:
                    self.settings["read_citations"] = settings["read_citations"]
                if settings.get("theme") in ("light", "dark"):
                    self.settings["theme"] = settings["theme"]
            favorites = data.get("favorites", [])
            if isinstance(favorites, list):
                self.favorites = sorted({value for value in favorites if valid_voice(value) or valid_voice(value, "kokoro")})
            recent = data.get("recent", [])
            if isinstance(recent, list):
                self.recent = [item for item in recent if isinstance(item, dict)
                               and all(isinstance(item.get(key), str) and item[key]
                                       for key in ("id", "path", "title"))][:20]
            if isinstance(data.get("bookmarks"), dict):
                self.bookmarks = data["bookmarks"]
        except (OSError, ValueError, TypeError):
            pass

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".library-", suffix=".tmp", delete=False) as output:
                temporary = Path(output.name)
                json.dump({"version": 1, "settings": self.settings, "favorites": self.favorites,
                           "recent": self.recent, "bookmarks": self.bookmarks}, output, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def remember_book(self, book_id, path):
        path = Path(path).resolve()
        self.recent = [{"id": book_id, "path": str(path), "title": path.stem}] + [
            item for item in self.recent if item["id"] != book_id and item["path"] != str(path)]
        self.recent = self.recent[:20]

    def marks_for(self, book_id, chapters):
        result = []
        entries = self.bookmarks.get(book_id, [])
        if not isinstance(entries, list):
            return result
        for item in entries:
            if not isinstance(item, dict):
                continue
            section, start, end = (item.get(key) for key in ("section", "start", "end"))
            if not all(type(value) is int for value in (section, start, end)):
                continue
            if not (0 <= section < len(chapters) and 0 <= start < end <= len(chapters[section][1])):
                continue
            if not all(isinstance(item.get(key), str) and item[key] for key in ("id", "label")):
                continue
            if item.get("text_hash") == text_hash(chapters[section][1]):
                result.append(item)
        return result

    def add_mark(self, book_id, position, label, chapters):
        section, start, end = position
        mark = {"id": uuid.uuid4().hex, "section": section, "start": start, "end": end,
                "label": label.strip()[:120], "text_hash": text_hash(chapters[section][1])}
        self.bookmarks[book_id] = self.marks_for(book_id, chapters) + [mark]
        return mark

    def remove_mark(self, book_id, mark_id, chapters):
        self.bookmarks[book_id] = [mark for mark in self.marks_for(book_id, chapters) if mark["id"] != mark_id]
