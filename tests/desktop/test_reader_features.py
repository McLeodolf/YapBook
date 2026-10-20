import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import patch
from pathlib import Path

from yapbook.audio_cache import AudioCache
from yapbook.reader_text import search_book, speech_projection
from yapbook.follow_reader import sentence_spans


class ReaderFeaturesTests(unittest.TestCase):
    def test_citation_sentences(self):
        for sentence in ('Smith et al. (2021) found this.', 'Evidence (Smith et al., 2021) supports it.',
                         'Smith et al. 2021 supports it.', 'Smith et al. reported this.'):
            text = sentence + ' Then we continued.'
            self.assertEqual([text[a:b] for a,b in sentence_spans(text)], [sentence, 'Then we continued.'])
        text = 'We consulted Smith et al. Then we left.'
        self.assertEqual([text[a:b] for a,b in sentence_spans(text)], ['We consulted Smith et al.', 'Then we left.'])

    def test_citation_projection(self):
        text = 'Evidence (Smith et al., 2021) supports this [12]. A note¹ matters. x² = 4 in 2020.'
        marked = [(text.index('¹'), text.index('¹')+1)]
        spoken, offsets = speech_projection(text, False, marked)
        self.assertEqual(spoken, 'Evidence supports this. A note matters. x² = 4 in 2020.')
        self.assertEqual(''.join(text[i] for i in offsets), spoken)
        self.assertEqual(speech_projection(text, True, marked)[0], text)
        self.assertEqual(speech_projection('[12]', False)[0], '')
        self.assertEqual(speech_projection('Smith et al. (2021) found a pattern.', False)[0], 'found a pattern.')
        self.assertEqual(speech_projection('“A quote.” It was cold (in 2021).',False)[0], '“A quote.” It was cold (in 2021).')

    def test_full_book_literal_search(self):
        chapters = [('One','X [12] text.'),('Two','X\n[12] more.')]
        hits = search_book(chapters,'x [12]')
        self.assertEqual([chapters[s][1][a:b] for s,a,b in hits], ['X [12]','X\n[12]'])
        self.assertEqual(search_book(chapters,'  '), [])

    def test_parallel_dedup_and_persistent_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'speech.db'
            cache, calls, entered, release = AudioCache(path), [], threading.Event(), threading.Event()
            def load():
                calls.append('request');entered.set();self.assertTrue(release.wait(3));return b'mp3', [[0,10,0,5]]
            with ThreadPoolExecutor(3) as workers:
                first = workers.submit(cache.get,'Same.','voice',-15,load)
                self.assertTrue(entered.wait(3))
                second = workers.submit(cache.get,'Same.','voice',-15,load)
                release.set();self.assertEqual(first.result(),second.result())
            self.assertTrue(cache.flush(timeout=3))
            self.assertEqual(AudioCache(path).get('Same.','voice',-15,load), first.result())
            self.assertEqual(len(calls),1)
            cache.get('Same.','other',-15,load);cache.get('Same.','voice',-10,load)
            self.assertEqual(len(calls),3)
            self.assertTrue(cache.flush(timeout=3))

    def test_failure_is_not_automatically_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            cache, calls = AudioCache(Path(directory)/'speech.db'), []
            def fail():
                calls.append(1);raise ValueError('failed')
            for _ in range(2):
                with self.assertRaises(ValueError):cache.get('a','v',0,fail)
            self.assertEqual(len(calls),1)
            cache.retry_failed()
            with self.assertRaises(ValueError):cache.get('a','v',0,fail)
            self.assertEqual(len(calls),2)

    def test_ready_audio_does_not_wait_for_disk_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'speech.db'
            cache = AudioCache(path)
            database = cache._database
            saving, release = threading.Event(), threading.Event()
            calls = []

            @contextmanager
            def slow_database():
                with database() as connection:
                    class Connection:
                        def execute(self, statement, parameters=()):
                            if statement.startswith('INSERT'):
                                saving.set()
                                if not release.wait(5):
                                    raise OSError('Test storage did not resume')
                            return connection.execute(statement, parameters)
                    yield Connection()

            def load():
                calls.append('request')
                return b'mp3', [[0, 10, 0, 5]]

            with patch.object(cache, '_database', slow_database):
                try:
                    with ThreadPoolExecutor(2) as workers:
                        first = workers.submit(cache.get, 'Same.', 'voice', -15, load)
                        self.assertTrue(saving.wait(3))
                        second = workers.submit(cache.get, 'Same.', 'voice', -15, load)
                        self.assertEqual(first.result(timeout=1), second.result(timeout=1))
                        self.assertEqual(calls, ['request'])
                        self.assertFalse(cache.flush(timeout=0.01))
                finally:
                    release.set()
                    self.assertTrue(cache.flush(timeout=3))
            self.assertEqual(AudioCache(path).get('Same.', 'voice', -15, load), first.result())
            self.assertEqual(calls, ['request'])

    def test_unsaved_audio_is_retained_until_persistence_finishes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'speech.db'
            cache = AudioCache(path)
            database = cache._database
            saving, release = threading.Event(), threading.Event()
            calls = []

            @contextmanager
            def slow_database():
                with database() as connection:
                    class Connection:
                        def execute(self, statement, parameters=()):
                            if statement.startswith('INSERT'):
                                saving.set()
                                if not release.wait(10):
                                    raise OSError('Test storage did not resume')
                            return connection.execute(statement, parameters)
                    yield Connection()

            def load():
                calls.append('request')
                return b'mp3', []

            with patch.object(cache, '_database', slow_database):
                try:
                    cache.get('First.', 'voice', -15, load)
                    self.assertTrue(saving.wait(3))
                    for number in range(40):
                        cache.get(f'Sentence {number}.', 'voice', -15, load)
                    self.assertEqual(len(cache.pending), 41)
                    self.assertEqual(cache.get('First.', 'voice', -15, load), (b'mp3', []))
                    self.assertEqual(len(calls), 41)
                finally:
                    release.set()
                    self.assertTrue(cache.flush(timeout=5))
            self.assertLessEqual(len(cache.pending), 32)
            self.assertEqual(cache.get('First.', 'voice', -15, load), (b'mp3', []))
            self.assertEqual(len(calls), 41)

    def test_failed_storage_keeps_session_audio_without_duplicate_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = AudioCache(Path(directory) / 'speech.db')
            calls = []

            @contextmanager
            def unavailable_database():
                raise OSError('Storage unavailable')
                yield

            def load():
                calls.append('request')
                return b'mp3', []

            with patch.object(cache, '_database', unavailable_database):
                for number in range(40):
                    cache.get(f'Sentence {number}.', 'voice', -15, load)
                self.assertTrue(cache.flush(timeout=3))
                self.assertIn('only for this session', cache.warning)
                self.assertEqual(len(cache.pending), 40)
                for number in range(40):
                    self.assertEqual(cache.get(f'Sentence {number}.', 'voice', -15, load), (b'mp3', []))
                self.assertEqual(len(calls), 40)

    def test_configured_capacity_allows_six_parallel_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = AudioCache(Path(directory) / 'speech.db', max_requests=6)
            entered, release = threading.Event(), threading.Event()
            calls, lock = [], threading.Lock()

            def load():
                with lock:
                    calls.append('request')
                    if len(calls) == 6:
                        entered.set()
                if not release.wait(5):
                    raise RuntimeError('Test requests did not resume')
                return b'mp3', []

            try:
                with ThreadPoolExecutor(6) as workers:
                    futures = [workers.submit(cache.get, f'Sentence {number}.', 'voice', -15, load) for number in range(6)]
                    try:
                        self.assertTrue(entered.wait(3))
                        self.assertEqual(len(calls), 6)
                    finally:
                        release.set()
                    for future in futures:
                        self.assertEqual(future.result(timeout=3), (b'mp3', []))
            finally:
                release.set()
                self.assertTrue(cache.flush(timeout=5))

    def test_ready_result_can_be_flushed_before_owner_returns(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'speech.db'
            cache = AudioCache(path)
            loading, release = threading.Event(), threading.Event()
            observed = []

            def load():
                loading.set()
                if not release.wait(5):
                    raise RuntimeError('Test request did not resume')
                return b'mp3', []

            def unexpected_load():
                raise AssertionError('Completed audio was not queued for persistence')

            def when_ready(future):
                try:
                    if not cache.flush(timeout=3):
                        raise AssertionError('Completed audio did not finish persisting')
                    observed.append(AudioCache(path).get('Same.', 'voice', -15, unexpected_load))
                except Exception as error:
                    observed.append(error)

            try:
                with ThreadPoolExecutor(1) as workers:
                    owner = workers.submit(cache.get, 'Same.', 'voice', -15, load)
                    try:
                        self.assertTrue(loading.wait(3))
                        with cache.lock:
                            future = next(iter(cache.pending.values()))
                        future.add_done_callback(when_ready)
                    finally:
                        release.set()
                    self.assertEqual(owner.result(timeout=5), (b'mp3', []))
            finally:
                release.set()
                self.assertTrue(cache.flush(timeout=3))
            self.assertEqual(observed, [(b'mp3', [])])
