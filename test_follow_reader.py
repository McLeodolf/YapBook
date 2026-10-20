"""Offline tests: python -m unittest test_follow_reader -v."""

import gc
from concurrent.futures import wait
from pathlib import Path
import tempfile
import tkinter as tk
import threading
import time
import unittest
from unittest.mock import patch

from ebooklib import epub

from follow_reader import ReadingWindow, SentenceCue, align_sentences, cue_at, generate_audio, sentence_spans, text_parts
from epub_document import EpubDocument
from app_state import AppState
from read_epub import prepare_speech, read_chapters, speech_chunks


class SentenceTests(unittest.TestCase):
    def test_cli_keeps_block_breaks_and_inline_words(self):
        chapter = epub.EpubHtml(title='One', file_name='one.xhtml')
        chapter.content = ('<h1>Chapter 2</h1><p>A small\n bird <em>landed</em>.</p>'
                           '<table><tr><td>Left</td><td>Right</td></tr></table>')
        book = epub.EpubBook()
        book.add_item(chapter)
        book.spine = [(chapter.id, 'yes')]
        with patch('read_epub.epub.read_epub', return_value=book):
            chapters = read_chapters('generated-test.epub')
        self.assertEqual(chapters[0][1], 'Chapter 2\nA small bird landed.\nLeft\nRight')

    def test_headings_and_explicit_breaks_are_separate_click_targets(self):
        text = 'Chapter 2\nExploring the Quiet Garden\nA small bird landed. Another sentence.'
        self.assertEqual([text[a:b] for a, b in sentence_spans(text)],
                         ['Chapter 2', 'Exploring the Quiet Garden', 'A small bird landed.', 'Another sentence.'])

    def test_speech_punctuation_does_not_duplicate_existing_endings(self):
        text = 'A heading\nA question?\n“Quoted sentence.”\nLast paragraph.'
        spoken, offsets = prepare_speech(text)
        self.assertEqual(spoken, 'A heading.\nA question?\n“Quoted sentence.”\nLast paragraph.')
        self.assertEqual(len(spoken), len(offsets))
        self.assertEqual(text[offsets[spoken.index('Last')]:], 'Last paragraph.')

    def test_chunking_preserves_paragraphs_and_source_offsets(self):
        text = 'Chapter 2\nA short title\n' + 'One sentence. Another sentence. ' * 25
        chunks = list(speech_chunks(text, limit=90))
        self.assertTrue(chunks[0].startswith('Chapter 2\nA short title\n'))
        self.assertTrue(all(len(chunk) <= 90 for chunk in chunks))
        self.assertEqual(' '.join(' '.join(chunks).split()), ' '.join(text.split()))
        for start, chunk in text_parts(text):
            self.assertEqual(text[start:start + len(chunk)], chunk)
        long_word = 'x' * 100
        self.assertEqual(list(speech_chunks(long_word + ' end', limit=20)), [long_word, 'end'])

    def test_repeated_sentences_and_unicode_preserve_source_offsets(self):
        text = '„Grüße 👋!“ Grüße 👋! Noch ein Satz.'
        events = [dict(text='"Grüße 👋!"', offset=1000000, duration=10000000),
                  dict(text='Grüße 👋!', offset=11000000, duration=10000000),
                  dict(text='Noch ein Satz.', offset=21000000, duration=10000000)]
        cues = align_sentences(text, events)
        self.assertEqual([text[c.start_char:c.end_char] for c in cues],
                         ['„Grüße 👋!“', 'Grüße 👋!', 'Noch ein Satz.'])
        self.assertEqual(cue_at(cues, 1200), cues[1])
        self.assertIsNone(cue_at(cues, 50))
        self.assertIsNone(cue_at(cues, 4000))

    def test_audio_parts_are_individual_sentences_with_source_offsets(self):
        text = 'A sentence in a long chapter. ' * 250
        parts = list(text_parts(text, 29))
        self.assertLessEqual(len(parts[0][1]), 350)
        self.assertEqual(parts[0][1], 'A sentence in a long chapter.')
        self.assertTrue(all(len(chunk) <= 700 for _, chunk in parts))
        self.assertEqual(' '.join(chunk for _, chunk in parts), text[29:].strip())
        for start, chunk in parts:
            self.assertEqual(text[start:start + len(chunk)], chunk)

    def test_local_sentence_start_handles_abbreviations_and_decimals(self):
        text = 'Dr. Weber liest z. B. 3.14 Seiten. „Hallo!“ Danach geht es weiter.'
        self.assertEqual([text[a:b] for a, b in sentence_spans(text)],
                         ['Dr. Weber liest z. B. 3.14 Seiten.', '„Hallo!“', 'Danach geht es weiter.'])

    def test_missing_or_incompatible_metadata_is_not_silently_guessed(self):
        with self.assertRaises(ValueError):
            align_sentences('Hallo.', [])
        with self.assertRaises(ValueError):
            align_sentences('Hallo.', [dict(text='Andere Worte.', offset=0, duration=10)])

    def test_internal_periods_keep_a_sentence_in_one_audio_request(self):
        sentences = [
            'Im 17. Jahrhundert entstand ein kleines Dorf.',
            'Wir feiern ihren 105. Geburtstag.',
            'wir feiern ihren 105. geburtstag.',
            'Am 3. Mai feiern wir den 1000. Geburtstag.',
            'Am 3. 5. 2024 wurde er geboren.',
            'Matthew C. Perry arrived in Japan.',
            'J. R. R. Tolkien wrote a book.',
            'Dr. Smith met Mr. Brown.',
            'Dr. Weber liest z. B. 3.14 Seiten.',
            'Das ist z.B. ein Beispiel bzw. eine Erklärung.',
            'The U.S. economy grew.',
            'Im 17.\u00a0Jahrhundert lebte Matthew C.\u00a0Perry.',
        ]
        for sentence in sentences:
            with self.subTest(sentence=sentence):
                text = '  ' + sentence + ' Danach geht es weiter.  '
                self.assertEqual([text[a:b] for a, b in sentence_spans(text)],
                                 [sentence, 'Danach geht es weiter.'])
                parts = list(text_parts(text))
                self.assertEqual([part for _, part in parts], [sentence, 'Danach geht es weiter.'])
                for start, part in parts:
                    self.assertEqual(text[start:start + len(part)], part)

    def test_real_sentence_ends_and_newlines_still_split(self):
        cases = [
            ['Er wurde 17.', 'Danach ging er nach Hause.'],
            ['He was 105.', 'Then they celebrated.'],
            ['This is plan A.', 'Then we try again.'],
            ['Bring pens etc.', 'Then we start.'],
            ['He lives in the U.S.', 'The next visitor is from Japan.'],
            ['“Matthew C. Perry arrived.”', 'Another visitor followed.'],
        ]
        for expected in cases:
            with self.subTest(expected=expected):
                text = ' '.join(expected)
                self.assertEqual([text[a:b] for a, b in sentence_spans(text)], expected)
        text = '17.\nJahrhundert\nDr.\nSmith\n105.\nGeburtstag'
        self.assertEqual([text[a:b] for a, b in sentence_spans(text)], text.splitlines())

    def test_service_fragments_merge_into_one_complete_highlight(self):
        for fragments in [
            ['Im 17.', 'Jahrhundert entstand ein kleines Dorf.'],
            ['Wir feiern ihren 105.', 'Geburtstag.'],
            ['Matthew C.', 'Perry arrived in Japan.'],
        ]:
            with self.subTest(fragments=fragments):
                events = [dict(text=part, offset=1_000_000 + index * 20_000_000, duration=15_000_000)
                          for index, part in enumerate([*fragments, 'Another sentence.'])]
                sentence = ' '.join(fragments)
                text = '  ' + sentence + ' Another sentence.'
                cues = align_sentences(text, events)
                self.assertEqual([text[c.start_char:c.end_char] for c in cues], [sentence, 'Another sentence.'])
                self.assertEqual((cues[0].start_ms, cues[0].end_ms), (100, 3600))
                self.assertEqual(cue_at(cues, 1800), cues[0])
                self.assertEqual(cue_at(cues, 4200), cues[1])


class SpeechPreparationTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_heading_cues_map_back_to_unmodified_book_text(self):
        text = 'Chapter 2\nExploring the Quiet Garden\nA small bird landed.'

        class Speech:
            async def stream(self):
                yield dict(type='audio', data=b'fake mp3')
                for index, sentence in enumerate(('Chapter 2.', 'Exploring the Quiet Garden.', 'A small bird landed.')):
                    yield dict(type='SentenceBoundary', text=sentence, offset=index * 20_000_000, duration=15_000_000)

        with patch('follow_reader.edge_tts.Communicate', return_value=Speech()) as communicate:
            audio, cues = await generate_audio(text, 'en-US-AriaNeural', 0, threading.Event())
        self.assertEqual(audio, b'fake mp3')
        self.assertEqual(communicate.call_args.args[0], 'Chapter 2.\nExploring the Quiet Garden.\nA small bird landed.')
        self.assertEqual([text[cue.start_char:cue.end_char] for cue in cues],
                         ['Chapter 2', 'Exploring the Quiet Garden', 'A small bird landed.'])
        self.assertEqual([cue.start_ms for cue in cues], [0, 2000, 4000])


class FakeAudio:
    def __init__(self):
        self.position = 0
        self.state = 'stopped'
        self.seek_calls = []
        self.volume = None
        self.play_calls = []

    def play(self, _path, volume=1000):
        self.position = 0
        self.state = 'playing'
        self.play_calls.append(_path.read_bytes())
        self.set_volume(volume)

    def set_volume(self, volume):
        if self.state in ('playing', 'paused'):
            self.volume = volume

    def close(self):
        self.state = 'stopped'

    def pause(self):
        self.state = 'paused'

    def resume(self):
        self.state = 'playing'

    def seek(self, position):
        self.position = position
        self.seek_calls.append(position)
        self.state = 'playing'

    def position_ms(self):
        return self.position

    def mode(self):
        return self.state


class WindowTests(unittest.TestCase):
    def test_normal_playback_prepares_both_following_sentences_while_current_is_pending(self):
        self.use_chapters([('One','First sentence. Second sentence. Third sentence. Fourth sentence.')])
        calls, release = [], threading.Event()
        async def speech(text, voice, rate, cancelled, progress=None):
            calls.append(text)
            if text == 'First sentence.':release.wait(3)
            return text.encode(), [SentenceCue(0,1000,0,len(text))]
        with patch('follow_reader.generate_audio',speech):
            try:
                self.app.toggle_play()
                self.wait_until(lambda:len(calls)==3 and len(self.app.audio_cache)==2)
                self.assertEqual(self.app.state,'loading')
                release.set()
                self.wait_until(lambda:self.app.state=='playing')
                self.app.player.state='stopped'
                self.poll_once()
                self.assertEqual(self.app.state,'playing')
                self.assertEqual(self.app.player.play_calls[-1],b'Second sentence.')
                self.wait_until(lambda:len(self.app.audio_cache)==2)
                self.app.player.state='stopped'
                self.poll_once()
                self.assertEqual(self.app.player.play_calls[-1],b'Third sentence.')
                self.assertCountEqual(calls,['First sentence.','Second sentence.','Third sentence.','Fourth sentence.'])
            finally:
                release.set();self.app.stop()

    def test_citation_toggle_filters_speech_without_altering_visible_sentence(self):
        original='The garden (Smith et al., 2021) is quiet [12]. Another sentence.'
        self.use_chapters([('One',original)])
        self.app.read_citations.set(False)
        self.app._citations_changed()
        calls=[]
        async def speech(text, voice, rate, cancelled, progress=None):
            calls.append(text);return text.encode(),[SentenceCue(0,1000,0,len(text))]
        with patch('follow_reader.generate_audio',speech):
            self.app.toggle_play()
            self.wait_until(lambda:self.app.state=='playing' and len(self.app.audio_cache)==1)
            self.poll_once()
            self.assertCountEqual(calls,['The garden is quiet.','Another sentence.'])
            self.assertEqual(self.app.reader.highlighted_text,'The garden (Smith et al., 2021) is quiet [12].')
            self.assertEqual(self.app.chapters[0][1],original)
            self.app.stop()

    def test_search_selection_crosses_sections_without_starting_paused_audio(self):
        self.use_chapters([('One','First sentence.'),('Two','A unique search target.')])
        self.app.search_book()
        self.app.search_entry.insert(0,'unique search')
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            self.root.update();time.sleep(0.01)
            # Trigger the same debounced UI path used when typing.
            trees=[child for frame in self.app.search_window.winfo_children() for child in frame.winfo_children()
                   if child.winfo_class()=='Treeview']
            if trees and trees[0].get_children():break
        self.assertEqual(len(trees[0].get_children()),1)
        trees[0].selection_set('0');self.root.update()
        self.assertEqual(self.app.section,1)
        self.assertEqual(self.app.state,'idle')
        self.app.search_window.destroy()

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.withdraw()
        with patch('follow_reader.WindowsAudio', FakeAudio):
            self.app = ReadingWindow(self.root, app_state=AppState(Path(self.folder.name) / 'library.json'))
        self.app.chapters = [('Kapitel 1', 'Erster Satz. Zweiter Satz. Dritter Satz.'),
                             ('Kapitel 2', 'Noch ein Kapitel.')]
        self.app.chapter_box.configure(values=['Kapitel 1', 'Kapitel 2'])
        self.app._show_chapter()

    def tearDown(self):
        self.app.close()
        # Started requests deliberately finish into the shared cache after Stop.
        with self.app.speech_cache.lock:
            pending = list(self.app.speech_cache.pending.values())
        wait(pending, timeout=5)
        self.app = self.root = None
        # Tk objects must be collected here, not in a later audio worker thread.
        gc.collect()
        self.folder.cleanup()

    def poll_once(self):
        self.root.after_cancel(self.app.timer)
        self.app._poll()

    def wait_until(self, condition):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.poll_once()
            if condition():
                return
            time.sleep(0.005)
        self.fail('Timed out waiting for the audio worker')

    def queue_audio(self, audio, cues):
        # These fixtures supply an MP3 for a complete section; worker tests
        # below exercise real per-sentence partitioning and prefetch separately.
        self.app.parts = [(0, self.app.chapters[self.app.section][1])]
        self.app.part = 0
        key = (self.app.section, self.app.parts[self.app.part][0])
        self.app.audio_requested.add(key)
        self.app.waiting_for = key
        self.app._set_state('loading')
        self.app.results.put((self.app.generation, key, (audio, cues), None))

    def use_chapters(self, chapters):
        self.app.stop()
        self.app.chapters = chapters
        self.app.section = 0
        self.app.reader.set_document(EpubDocument.from_plain(chapters))
        self.app.chapter_box.configure(values=[title for title, _ in chapters])
        self.app._show_chapter()

    def test_click_in_loaded_audio_seeks_and_resumes(self):
        self.app.cues = [SentenceCue(100, 1000, 0, 12), SentenceCue(1000, 2000, 13, 26)]
        self.app._set_state('paused')
        self.app.seek_to_character(18)
        self.assertEqual(self.app.player.seek_calls, [1000])
        self.assertEqual(self.app.state, 'playing')
        self.assertEqual(self.app.highlighted, (13, 26))

    def test_click_in_unloaded_text_starts_from_that_sentence(self):
        old_token = self.app.generation
        with patch.object(self.app, '_request_part') as request:
            self.app.seek_to_character(18)
        self.assertEqual(self.app.parts[0], (13, 'Zweiter Satz.'))
        self.assertEqual(self.app.highlighted, (13, 26))
        self.assertGreater(self.app.generation, old_token)
        request.assert_called_once()
        self.app.stop()
        self.assertEqual(self.app.parts[0][0], 0)

    def test_obsolete_download_never_starts_playback(self):
        obsolete = self.app.generation
        self.app.stop()
        self.app.results.put((obsolete, (0, 0), None, 'Old request must be discarded'))
        self.app.results.put((obsolete, (0, 0), (b'old audio', []), None))
        with patch('follow_reader.messagebox.showerror') as error:
            self.poll_once()
        self.assertEqual(self.app.state, 'idle')
        self.assertEqual(self.app.player.state, 'stopped')
        self.assertFalse(self.app.audio_cache)
        error.assert_not_called()

    def test_pause_resume_keeps_position_and_highlight(self):
        self.app.cues = [SentenceCue(100, 1000, 0, 12)]
        self.app.player.position = 500
        self.app.player.state = 'playing'
        self.app._set_state('playing')
        self.poll_once()
        self.app.toggle_play()
        self.assertEqual(self.app.state, 'paused')
        self.assertEqual(self.app.highlighted, (0, 12))
        self.app.toggle_play()
        self.assertEqual(self.app.player.position, 500)
        self.assertEqual(self.app.state, 'playing')

    def test_chapter_change_cancels_download_and_updates_text(self):
        old_cancel = self.app.cancelled
        self.app.chapter_box.current(1)
        self.app.select_chapter()
        self.assertTrue(old_cancel.is_set())
        self.assertEqual(self.app.section, 1)
        self.assertIn('Noch ein Kapitel.', self.app.reader.get_page_text())
        self.assertIn('Erster Satz.', self.app.reader.get_page_text())

    def test_volume_slider_applies_live_and_survives_pause_seek_and_section_change(self):
        cues = [SentenceCue(0, 1000, 0, 12), SentenceCue(1000, 2000, 13, 26)]
        self.app.volume_slider.set(35)
        self.queue_audio(b'fake audio', cues)
        self.poll_once()
        self.assertEqual(self.app.player.volume, 350)
        self.assertEqual(self.app.volume_label.get(), '35%')

        self.app.volume_slider.set(0)
        self.assertEqual(self.app.player.volume, 0)
        self.app.toggle_play()
        self.app.volume_slider.set(42)
        self.assertEqual(self.app.player.volume, 420)
        self.assertEqual(self.app.state, 'paused')
        self.app.toggle_play()
        self.app.seek_to_character(18)
        self.assertEqual(self.app.player.volume, 420)

        self.app.player.state = 'stopped'
        with patch.object(self.app, '_request_part') as request:
            self.poll_once()
        self.assertEqual(self.app.section, 1)
        request.assert_called_once()
        self.queue_audio(b'next audio', [SentenceCue(0, 1000, 0, 16)])
        self.poll_once()
        self.assertEqual(self.app.player.volume, 420)
        self.assertEqual(self.app.volume.get(), 42)
        self.app.volume_slider.set(100)
        self.assertEqual(self.app.player.volume, 1000)

    def test_prefetch_is_bounded_and_cached_section_starts_immediately(self):
        chapters = [(f'Section {i}', f'Sentence number {i}.') for i in range(5)]
        self.use_chapters(chapters)
        calls = []

        async def speech(text, voice, rate, cancelled, progress=None):
            calls.append((text, voice, rate))
            return text.encode(), [SentenceCue(0, 1000, 0, len(text))]

        self.app.speed_slider.set(15.4)
        self.assertEqual(self.app.rate_label.get(), '+15%')
        with patch('follow_reader.generate_audio', speech):
            try:
                self.app.toggle_play()
                # Prefetch can finish before the current sentence's UI event.
                self.wait_until(lambda: len(self.app.audio_cache) == 2 and len(self.app.player.play_calls) == 1)
                self.assertCountEqual([call[0] for call in calls], [text for _, text in chapters[:3]])
                self.assertTrue(all(call[2] == 0 for call in calls))
                self.assertEqual(len(self.app.player.play_calls), 1)
                self.assertTrue(self.app.speed_slider.instate(['disabled']))

                self.app.player.state = 'stopped'
                self.poll_once()
                self.assertEqual(self.app.section, 1)
                self.assertEqual(self.app.state, 'playing')
                self.assertEqual(self.app.player.play_calls[-1], chapters[1][1].encode())
                self.wait_until(lambda: len(self.app.audio_cache) == 2)
                self.assertEqual(len(calls), 4)
                self.assertLessEqual(len(self.app.audio_requested), 3)
            finally:
                self.app.stop()
        self.assertTrue(self.app.speed_slider.instate(['!disabled']))

    def test_prefetch_within_one_section_keeps_character_offsets(self):
        self.use_chapters([('Long section', 'A sentence to read. ' * 750)])
        self.assertGreaterEqual(len(self.app.parts), 4)
        calls = []

        async def speech(text, voice, rate, cancelled, progress=None):
            calls.append(text)
            return text.encode(), [SentenceCue(0, 1000, 0, len(text))]

        with patch('follow_reader.generate_audio', speech):
            try:
                self.app.toggle_play()
                self.wait_until(lambda: len(self.app.audio_cache) == 2)
                self.assertEqual(len(calls), 1, 'Identical sentences at different offsets reuse one synthesis')
                second_start, second_text = self.app.parts[1]
                self.app.player.state = 'stopped'
                self.poll_once()
                self.assertEqual(self.app.part, 1)
                self.assertEqual(self.app.state, 'playing')
                self.poll_once()
                self.assertEqual(self.app.highlighted, (second_start, second_start + len(second_text)))
                self.assertEqual(self.app.player.play_calls[-1], second_text.encode())
            finally:
                self.app.stop()

    def test_prefetch_finishes_during_pause_without_starting_playback(self):
        self.use_chapters([('One', 'First sentence.'), ('Image', ''), ('Two', 'Second sentence.')])
        release = threading.Event()
        calls = []

        async def speech(text, voice, rate, cancelled, progress=None):
            calls.append(text)
            if text == 'Second sentence.':
                release.wait(3)
            return text.encode(), [SentenceCue(0, 1000, 0, len(text))]

        with patch('follow_reader.generate_audio', speech):
            try:
                self.app.toggle_play()
                self.wait_until(lambda: self.app.state == 'playing')
                self.app.toggle_play()
                release.set()
                self.wait_until(lambda: (2, 0) in self.app.audio_cache)
                self.assertEqual(self.app.state, 'paused')
                self.assertEqual(len(self.app.player.play_calls), 1)
                self.assertCountEqual(calls, ['First sentence.', 'Second sentence.'])
                self.app.toggle_play()
                self.app.player.state = 'stopped'
                self.poll_once()
                self.assertEqual(self.app.section, 2)
                self.assertEqual(self.app.state, 'playing')
                self.app.player.state = 'stopped'
                self.poll_once()
                self.assertEqual(self.app.state, 'idle')
                self.assertIsNone(self.app.audio_jobs)
                self.assertFalse(self.app.audio_cache)
            finally:
                release.set()
                self.app.stop()

    def test_stop_detaches_playback_but_keeps_completed_prefetch_for_restart(self):
        self.use_chapters([(str(i), f'Sentence {i}.') for i in range(4)])
        release, finished = threading.Event(), threading.Event()
        calls = []

        async def speech(text, voice, rate, cancelled, progress=None):
            calls.append(text)
            if text == 'Sentence 1.':
                release.wait(3)
                finished.set()
            return text.encode(), [SentenceCue(0, 1000, 0, len(text))]

        with patch('follow_reader.generate_audio', speech):
            try:
                self.app.toggle_play()
                self.wait_until(lambda: self.app.state == 'playing' and len(calls) == 3)
                cancelled = self.app.cancelled
                self.app.stop()
                release.set()
                self.assertTrue(finished.wait(3))
                self.poll_once()
                self.assertTrue(cancelled.is_set())
                self.assertEqual(self.app.state, 'idle')
                self.assertFalse(self.app.audio_cache)
                self.assertIsNone(self.app.audio_jobs)
                self.assertEqual(len(self.app.player.play_calls), 1)
                self.assertCountEqual(calls, ['Sentence 0.', 'Sentence 1.', 'Sentence 2.'])
                self.app.toggle_play()
                self.wait_until(lambda: self.app.state == 'playing' and len(self.app.audio_cache) == 2)
                self.assertEqual(len(calls), 3, 'Restart joins/reuses all three original requests')
            finally:
                release.set()
                self.app.stop()

    def test_prefetch_failure_does_not_interrupt_the_current_chunk(self):
        self.use_chapters([('One', 'First sentence.'), ('Two', 'Second sentence.')])
        async def speech(text, voice, rate, cancelled, progress=None):
            if text == self.app.chapters[1][1]:
                raise OSError('Simulated service failure')
            return text.encode(), [SentenceCue(0, 1000, 0, len(text))]

        with patch('follow_reader.generate_audio', speech), patch('follow_reader.messagebox.showerror') as error:
            try:
                self.app.toggle_play()
                self.wait_until(lambda: (1, 0) in self.app.audio_cache and self.app.state == 'playing')
                self.assertEqual(self.app.state, 'playing')
                error.assert_not_called()
                self.app.player.state = 'stopped'
                self.poll_once()
                error.assert_called_once()
                self.assertEqual(self.app.state, 'idle')
                self.assertFalse(self.app.audio_cache)
            finally:
                self.app.stop()

    def test_unicode_highlight_matches_python_character_offsets(self):
        text = 'Hallo 👋. Grüße danach.'
        self.app.chapters = [('Unicode', text)]
        self.app.reader.set_document(EpubDocument.from_plain(self.app.chapters))
        self.app._show_chapter()
        self.app._highlight((9, len(text)))
        self.assertEqual(self.app.reader.highlighted_text, text[9:])

    def test_click_in_next_section_switches_audio_without_replacing_document(self):
        before = self.app.reader.get_page_text()
        with patch.object(self.app, '_request_part') as request:
            self.app.seek_to_character(3, section=1)
        self.assertEqual(self.app.section, 1)
        self.assertEqual(self.app.parts[0][1], 'Noch ein Kapitel.')
        self.assertEqual(self.app.reader.get_page_text(), before)
        request.assert_called_once()


if __name__ == '__main__':
    unittest.main()
