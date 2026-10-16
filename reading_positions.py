"""Local, atomic reading-position storage, keyed by EPUB contents."""

import hashlib
import json
import os
from pathlib import Path
import tempfile


def book_fingerprint(path):
    with Path(path).open("rb") as book:
        return hashlib.file_digest(book, "sha256").hexdigest()


class PositionStore:
    def __init__(self, directory=None):
        if directory is None:
            local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
            directory = local / "YapBook" / "positions"
        self.directory = Path(directory)

    def get(self, book_id, chapters):
        try:
            record = json.loads((self.directory / f"{book_id}.json").read_text(encoding="utf-8"))
            if not isinstance(record, dict) or record.get("version") != 1:
                return None
            section, start, end = (record[name] for name in ("section", "start", "end"))
            if not all(type(value) is int for value in (section, start, end)):
                return None
            if not 0 <= section < len(chapters):
                return None
            text = chapters[section][1]
            if not (0 <= start < end <= len(text) or start == end == len(text) == 0):
                return None
            if record.get("text_hash") != hashlib.sha256(text.encode("utf-8")).hexdigest():
                return None
            return section, start, end
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def save(self, book_id, position, chapters):
        section, start, end = position
        record = {"version": 1, "section": section, "start": start, "end": end,
                  "text_hash": hashlib.sha256(chapters[section][1].encode("utf-8")).hexdigest()}
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory,
                                             prefix=".position-", suffix=".tmp", delete=False) as saved:
                temporary = Path(saved.name)
                json.dump(record, saved)
                saved.flush()
                os.fsync(saved.fileno())
            temporary.replace(self.directory / f"{book_id}.json")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
