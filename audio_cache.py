"""Persistent speech cache; running requests survive a playback seek or stop."""

from concurrent.futures import Future
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading


class AudioCache:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'YapBook' / 'speech.sqlite3'
        self.lock = threading.Lock()
        self.pending = {}
        self.capacity = threading.BoundedSemaphore(3)
        self.warning = ''

    @contextmanager
    def _database(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.execute('CREATE TABLE IF NOT EXISTS speech (key TEXT PRIMARY KEY, audio BLOB NOT NULL, cues TEXT NOT NULL)')
            with connection:
                yield connection
        finally:
            connection.close()

    def get(self, text, voice, rate, load):
        key = hashlib.sha256(json.dumps([1, text, voice, rate], ensure_ascii=False).encode('utf-8')).hexdigest()
        with self.lock:
            future = self.pending.get(key)
            owner = future is None
            if owner:
                future = self.pending[key] = Future()
        if not owner:
            return future.result()
        try:
            row = None
            try:
                with self._database() as database:
                    row = database.execute('SELECT audio, cues FROM speech WHERE key=?', (key,)).fetchone()
                if row:
                    result = (row[0], json.loads(row[1]))
            except (OSError, sqlite3.Error, ValueError):
                row = None
                self.warning = 'Audio is cached only for this session because local storage is unavailable.'
            if not row:
                with self.capacity:
                    result = load()
                try:
                    with self._database() as database:
                        database.execute('INSERT OR REPLACE INTO speech VALUES (?, ?, ?)', (key, result[0], json.dumps(result[1])))
                except (OSError, sqlite3.Error):
                    self.warning = 'Audio is cached only for this session because local storage is unavailable.'
            future.set_result(result)
            if not self.warning:
                with self.lock:
                    for old_key, old in list(self.pending.items()):
                        if len(self.pending) <= 32:
                            break
                        if old.done() and old.exception() is None:
                            del self.pending[old_key]
            return result
        except BaseException as error:
            future.set_exception(error)
            raise

    def retry_failed(self):
        with self.lock:
            self.pending = {key: value for key, value in self.pending.items()
                            if not value.done() or value.exception() is None}
