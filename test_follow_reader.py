"""Offline tests: python -m unittest test_follow_reader -v."""

import tkinter as tk
import unittest
from unittest.mock import patch

from follow_reader import ReadingWindow, SentenceCue, align_sentences, cue_at, sentence_spans
from epub_document import EpubDocument


class SentenceTests(unittest.TestCase):
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

    def test_local_sentence_start_handles_abbreviations_and_decimals(self):
        text = 'Dr. Weber liest z. B. 3.14 Seiten. „Hallo!“ Danach geht es weiter.'
        self.assertEqual([text[a:b] for a, b in sentence_spans(text)],
                         ['Dr. Weber liest z. B. 3.14 Seiten.', '„Hallo!“', 'Danach geht es weiter.'])

    def test_missing_or_incompatible_metadata_is_not_silently_guessed(self):
        with self.assertRaises(ValueError):
            align_sentences('Hallo.', [])
        with self.assertRaises(ValueError):
            align_sentences('Hallo.', [dict(text='Andere Worte.', offset=0, duration=10)])


class FakeAudio:
    def __init__(self):
        self.position = 0
        self.state = 'stopped'
        self.seek_calls = []
        self.volume = None

    def play(self, _path, volume=1000):
        self.state = 'playing'
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
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        with patch('follow_reader.WindowsAudio', FakeAudio):
            self.app = ReadingWindow(self.root)
        self.app.chapters = [('Kapitel 1', 'Erster Satz. Zweiter Satz. Dritter Satz.'),
                             ('Kapitel 2', 'Noch ein Kapitel.')]
        self.app.chapter_box.configure(values=['Kapitel 1', 'Kapitel 2'])
        self.app._show_chapter()

    def tearDown(self):
        self.app.close()

    def poll_once(self):
        self.root.after_cancel(self.app.timer)
        self.app._poll()

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
        self.assertEqual(self.app.parts[0], (13, 'Zweiter Satz. Dritter Satz.'))
        self.assertEqual(self.app.highlighted, (13, 26))
        self.assertGreater(self.app.generation, old_token)
        request.assert_called_once()
        self.app.stop()
        self.assertEqual(self.app.parts[0][0], 0)

    def test_obsolete_download_never_starts_playback(self):
        obsolete = self.app.generation
        self.app.stop()
        self.app.results.put((obsolete, None, 'Old request must be discarded'))
        with patch('follow_reader.messagebox.showerror') as error:
            self.poll_once()
        self.assertEqual(self.app.state, 'idle')
        self.assertEqual(self.app.player.state, 'stopped')
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
        self.app.results.put((self.app.generation, (b'fake audio', cues), None))
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
        self.app.results.put((self.app.generation, (b'next audio', [SentenceCue(0, 1000, 0, 16)]), None))
        self.poll_once()
        self.assertEqual(self.app.player.volume, 420)
        self.assertEqual(self.app.volume.get(), 42)
        self.app.volume_slider.set(100)
        self.assertEqual(self.app.player.volume, 1000)

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
