"""Persistent speech cache; running requests survive a playback seek or stop."""

from collections import deque
from concurrent.futures import Future
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading


class AudioCache:
    def __init__(self, path=None, max_requests=3):
        self.path = Path(path) if path else Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'YapBook' / 'speech.sqlite3'
        self.lock = threading.Lock()
        self.pending = {}
        self.persisted = set()
        self.capacity = threading.BoundedSemaphore(max_requests)
        self.warning = ''
        self.writes = deque()
        self.writer = None

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

    def _prune(self):
        # A playable result must stay in memory until its disk copy is committed.
        for key, future in list(self.pending.items()):
            if len(self.pending) <= 32:
                break
            if key in self.persisted and future.done() and future.exception() is None:
                del self.pending[key]
                self.persisted.remove(key)

    def _save_later(self, key, result):
        with self.lock:
            self.writes.append((key, result))
            if self.writer is None:
                self.writer = threading.Thread(target=self._write_pending, daemon=True)
                self.writer.start()

    def _write_pending(self):
        while True:
            with self.lock:
                if not self.writes:
                    self.writer = None
                    return
                key, result = self.writes.popleft()
            try:
                with self._database() as database:
                    database.execute('INSERT OR REPLACE INTO speech VALUES (?, ?, ?)', (key, result[0], json.dumps(result[1])))
            except (OSError, sqlite3.Error, TypeError, ValueError):
                self.warning = 'Audio is cached only for this session because local storage is unavailable.'
            else:
                with self.lock:
                    self.persisted.add(key)
                    self._prune()

    def flush(self, timeout=1.0):
        """Wait briefly for queued saves; return False if they are still running."""
        with self.lock:
            writer = self.writer
        if writer is None:
            return True
        writer.join(max(0, timeout))
        return not writer.is_alive()

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
                self._save_later(key, result)
            future.set_result(result)
            with self.lock:
                if row:
                    self.persisted.add(key)
                self._prune()
            return result
        except BaseException as error:
            if not future.done():
                future.set_exception(error)
            raise

    def retry_failed(self):
        with self.lock:
            self.pending = {key: value for key, value in self.pending.items()
                            if not value.done() or value.exception() is None}
