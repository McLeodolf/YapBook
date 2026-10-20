import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from audio_cache import AudioCache
from reader_text import search_book, speech_projection
from follow_reader import sentence_spans


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
            self.assertEqual(AudioCache(path).get('Same.','voice',-15,load), first.result())
            self.assertEqual(len(calls),1)
            cache.get('Same.','other',-15,load);cache.get('Same.','voice',-10,load)
            self.assertEqual(len(calls),3)

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
