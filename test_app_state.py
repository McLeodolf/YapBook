"""Persistence and playback regression coverage for reader conveniences."""

import asyncio
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from app_state import AppState, DEFAULT_VOICE, service_rate
from follow_reader import SentenceCue, request_audio
import test_follow_reader as fixtures


class AppStateTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'library.json'

    def test_defaults_validation_and_round_trip(self):
        state = AppState(self.path)
        self.assertEqual(state.settings['voice'], DEFAULT_VOICE)
        self.assertEqual(service_rate(state.settings['rate']), -15)
        self.assertEqual(service_rate(15), 0)
        self.assertEqual(service_rate(-50), -65)
        state.settings.update(voice='de-DE-KatjaNeural', rate=12, volume=34, font_size=28, follow=False, theme='dark')
        state.favorites = [DEFAULT_VOICE]
        state.save()
        loaded = AppState(self.path)
        self.assertEqual(loaded.settings, state.settings)
        self.assertEqual(loaded.favorites, state.favorites)
        self.path.write_text(json.dumps({'version': 1, 'settings': {'rate': True, 'volume': 800,
            'font_size': 'bad', 'voice': 'en-', 'follow': []}, 'recent': [None], 'favorites': [[], 1]}))
        self.assertEqual(AppState(self.path).settings, AppState(Path(self.folder.name) / 'missing').settings)
        self.path.write_text('broken')
        self.assertEqual(AppState(self.path).settings['voice'], DEFAULT_VOICE)

    def test_failed_write_preserves_existing_file(self):
        state = AppState(self.path)
        state.save()
        original = self.path.read_bytes()
        state.settings['volume'] = 40
        with patch.object(Path, 'replace', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                state.save()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(list(self.path.parent.glob('*.tmp')))

    def test_recent_books_deduplicate_on_move_and_bound_list(self):
        state = AppState(self.path)
        for i in range(25):
            state.remember_book(str(i), self.path.parent / f'book{i}.epub')
        self.assertEqual(len(state.recent), 20)
        state.remember_book('24', self.path.parent / 'renamed.epub')
        self.assertEqual(len(state.recent), 20)
        self.assertEqual(state.recent[0]['title'], 'renamed')
        state.save()
        self.assertEqual(AppState(self.path).recent, state.recent)

    def test_multiple_bookmarks_survive_reload_and_validate_text(self):
        state = AppState(self.path)
        chapters = [('First', 'Hello.\nWorld.'), ('Second', 'Another sentence.')]
        first = state.add_mark('book', (0, 0, 6), 'Opening', chapters)
        second = state.add_mark('book', (1, 0, 17), 'Later', chapters)
        state.save()
        loaded = AppState(self.path)
        self.assertEqual(len(loaded.marks_for('book', chapters)), 2)
        self.assertEqual(loaded.marks_for('book', [('First', 'Hello. World.'), chapters[1]])[0], first)
        self.assertEqual(loaded.marks_for('book', [('First', 'Changed text.'), chapters[1]]), [second])
        loaded.remove_mark('book', first['id'], chapters)
        self.assertEqual(loaded.marks_for('book', chapters), [second])
        self.assertEqual(loaded.marks_for('other', chapters), [])


class RequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_total_deadline_cancels_a_stalled_service(self):
        released = asyncio.Event()

        async def stalled(*args):
            try:
                await asyncio.sleep(10)
            finally:
                released.set()

        with patch('follow_reader.generate_audio', stalled):
            with self.assertRaisesRegex(TimeoutError, 'longer than'):
                await request_audio('Test.', DEFAULT_VOICE, -15, threading.Event(), timeout=0.02)
        self.assertTrue(released.is_set())

    async def test_stop_cancels_without_waiting_for_network_data(self):
        cancelled, released = threading.Event(), asyncio.Event()

        async def stalled(*args):
            try:
                await asyncio.sleep(10)
            finally:
                released.set()

        with patch('follow_reader.generate_audio', stalled):
            request = asyncio.create_task(request_audio('Test.', DEFAULT_VOICE, -15, cancelled))
            await asyncio.sleep(0.01)
            cancelled.set()
            self.assertIsNone(await asyncio.wait_for(request, 0.5))
        self.assertTrue(released.is_set())


class FeatureWindowTests(unittest.TestCase):
    setUp = fixtures.WindowTests.setUp
    tearDown = fixtures.WindowTests.tearDown
    poll_once = fixtures.WindowTests.poll_once
    wait_until = fixtures.WindowTests.wait_until
    queue_audio = fixtures.WindowTests.queue_audio

    def test_theme_toggle_preserves_playback_and_saved_preferences(self):
        self.queue_audio(b'audio', [SentenceCue(0, 1000, 0, 12)])
        self.poll_once()
        state, generation, position = self.app.state, self.app.generation, self.app.reading_position
        self.app.toggle_theme()
        self.assertEqual(self.app.theme, 'dark')
        self.assertTrue(self.app.reader.dark)
        self.assertEqual(self.app.state, state)
        self.assertEqual(self.app.generation, generation)
        self.assertEqual(self.app.reading_position, position)
        self.assertEqual(AppState(self.app.app_state.path).settings['theme'], 'dark')
        self.app.toggle_theme()
        self.assertEqual(self.app.theme, 'light')

    def test_default_voice_and_speed_reach_service(self):
        calls = []

        async def speech(text, voice, rate, cancelled, progress=None):
            calls.append((voice, rate))
            progress(2048)
            return b'audio', [SentenceCue(0, 1000, 0, len(text))]

        with patch('follow_reader.generate_audio', speech):
            self.app.toggle_play()
            self.wait_until(lambda: self.app.state == 'playing')
            self.app.stop()
        self.assertEqual(calls[0], (DEFAULT_VOICE, -15))
        self.assertEqual(self.app.rate_label.get(), '+0%')

    def test_filters_favorites_and_settings_persist(self):
        self.app.toggle_favorite()
        self.app.favorites_only.set(True)
        self.app._filter_voices()
        self.assertEqual(self.app.voice_box['values'], (DEFAULT_VOICE,))
        self.app.favorites_only.set(False)
        self.app.language.set('de-DE')
        self.app.voice.set('katja')
        from types import SimpleNamespace
        self.app._voice_edited(SimpleNamespace(keysym='a'))
        self.app._filter_voices()
        self.assertEqual(self.app.voice_box['values'], ('de-DE-KatjaNeural',))
        self.app.voice.set('de-DE-KatjaNeural')
        self.app.volume.set(42)
        self.app.rate.set(12)
        self.app.resize_font(4)
        self.app._save_settings()
        state = AppState(self.app.app_state.path)
        self.assertEqual(state.settings['font_size'], 24)
        self.assertEqual(state.settings['volume'], 42)
        self.assertEqual(state.settings['rate'], 12)
        self.assertEqual(state.settings['voice'], 'de-DE-KatjaNeural')
        self.assertEqual(state.favorites, [DEFAULT_VOICE])

    def test_preview_does_not_move_the_book_or_start_it_afterwards(self):
        self.app._prepare_parts(13)
        self.app._highlight((13, 26))
        before = (self.app.reading_position, list(self.app.parts), self.app.reader.highlighted_text)

        async def speech(text, voice, rate, cancelled, progress=None):
            return b'preview', [SentenceCue(0, 1000, 0, len(text))]

        with patch('follow_reader.generate_audio', speech):
            self.app.preview_voice()
            self.wait_until(lambda: self.app.state == 'playing')
            self.assertTrue(self.app.preview_active)
            self.assertTrue(self.app.play_button.instate(['disabled']))
            self.app.player.state = 'stopped'
            self.poll_once()
        self.assertEqual(self.app.state, 'idle')
        self.assertFalse(self.app.preview_active)
        self.assertEqual((self.app.reading_position, self.app.parts, self.app.reader.highlighted_text), before)

    def test_preview_can_be_stopped_and_late_result_is_ignored(self):
        with patch.object(self.app, '_start_audio_worker'):
            import queue
            self.app.audio_jobs = queue.Queue()
            self.app.preview_voice()
        token = self.app.generation
        self.app.stop()
        self.app.results.put((token, (-1, 0), (b'late', []), None))
        self.poll_once()
        self.assertEqual(self.app.state, 'idle')
        self.assertFalse(self.app.player.play_calls)

    def test_loading_status_reports_elapsed_time_and_received_bytes(self):
        self.app.waiting_for = (0, 0)
        self.app.loading_since = time.monotonic() - 12
        self.app.request_progress[(0, 0)] = 4096
        self.app._loading_status()
        self.assertIn('12s', self.app.status.get())
        self.assertIn('4.0 KB received', self.app.status.get())

    def test_previous_sentence_and_section_progress(self):
        self.app._highlight((13, 26))
        self.assertGreater(float(self.app.section_progress['value']), 0)
        with patch.object(self.app, '_request_part') as request:
            self.app.previous_sentence()
        request.assert_called_once()
        self.assertEqual(self.app.parts[0][0], 0)
        self.app.section = 1
        self.app._show_chapter()
        with patch.object(self.app, '_request_part'):
            self.app.previous_sentence()
        self.assertEqual(self.app.section, 0)
        self.assertEqual(self.app.parts[0][1], 'Dritter Satz.')

    def test_bookmark_jump_restores_highlight_without_autoplay_when_idle(self):
        self.app.book_id = 'book'
        self.app.position_store.directory = Path(self.folder.name) / 'positions'
        mark = self.app.app_state.add_mark('book', (0, 13, 26), 'My mark', self.app.chapters)
        self.app.go_to_bookmark(mark)
        self.assertEqual(self.app.highlighted, (13, 26))
        self.assertEqual(self.app.parts[0][0], 13)
        self.assertEqual(self.app.state, 'idle')
        self.assertEqual(self.app.position_store.get('book', self.app.chapters), (0, 13, 26))

    def test_timed_sleep_pauses_and_resume_keeps_audio_position(self):
        self.queue_audio(b'audio', [SentenceCue(0, 1000, 0, 12)])
        self.poll_once()
        self.app.player.position = 400
        self.app.sleep_choice.set('15 minutes')
        self.app.set_sleep_timer()
        self.assertGreater(self.app.sleep_deadline, time.monotonic() + 899)
        self.app.sleep_deadline = time.monotonic() - 1
        self.poll_once()
        self.assertEqual(self.app.state, 'paused')
        self.assertEqual(self.app.sleep_choice.get(), 'Off')
        self.app.toggle_play()
        self.assertEqual(self.app.player.position, 400)

    def test_sleep_during_loading_keeps_resume_sentence(self):
        self.app._prepare_parts(13)
        self.app._highlight((13, 26))
        self.app._set_state('loading')
        self.app.sleep_deadline = time.monotonic() - 1
        self.poll_once()
        self.assertEqual(self.app.state, 'idle')
        self.assertEqual(self.app.parts[0][0], 13)
        self.assertEqual(self.app.highlighted, (13, 26))

    def test_end_of_section_timer_stops_before_next_section_audio(self):
        self.queue_audio(b'audio', [SentenceCue(0, 1000, 0, 12)])
        self.poll_once()
        self.app.sleep_choice.set('End of section')
        self.app.set_sleep_timer()
        self.app.player.state = 'stopped'
        self.poll_once()
        self.assertEqual(self.app.state, 'idle')
        self.assertEqual(self.app.section, 1)
        self.assertEqual(len(self.app.player.play_calls), 1)
        self.assertEqual(self.app.sleep_choice.get(), 'Off')

    def test_failure_retains_sentence_for_retry_and_ignores_stale_progress(self):
        self.app._prepare_parts(13)
        self.app._highlight((13, 26))
        self.app._set_state('loading')
        old_token = self.app.generation
        with patch('follow_reader.messagebox.showerror'):
            self.app._error('Test timeout')
        self.assertEqual(self.app.parts[0][0], 13)
        self.app.progress_events.put((old_token, (0, 13), 1000))
        self.poll_once()
        self.assertFalse(self.app.request_progress)


if __name__ == '__main__':
    unittest.main()
