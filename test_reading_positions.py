"""Reading-position persistence using generated EPUBs and isolated local storage."""

import hashlib
import html
import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from ebooklib import epub

from follow_reader import ReadingWindow, SentenceCue
from reading_positions import PositionStore, book_fingerprint
from app_state import AppState
from test_follow_reader import FakeAudio


def make_epub(path, identifier="first-book"):
    book = epub.EpubBook()
    book.set_identifier(identifier)
    book.set_title("Generated test book")
    book.set_language("en")
    sections = []
    for index, text in enumerate(("Opening sentence. Another opening sentence.",
                                   "First sentence. Second sentence with an emoji 👋. Last sentence.")):
        section = epub.EpubHtml(title=f"Section {index + 1}", file_name=f"section-{index}.xhtml", lang="en")
        section.content = "<p>" + html.escape(text) + "</p>"
        book.add_item(section)
        sections.append(section)
    book.add_item(epub.EpubNav())
    book.toc = tuple(sections)
    book.spine = ["nav", *sections]
    epub.write_epub(str(path), book)


class PositionStoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = PositionStore(Path(self.folder.name) / "positions")
        self.book_id = "a" * 64
        self.chapters = [("One", "First. Second.")]

    def test_missing_corrupt_and_invalid_records_are_ignored(self):
        self.assertIsNone(self.store.get(self.book_id, self.chapters))
        self.store.directory.mkdir()
        path = self.store.directory / f"{self.book_id}.json"
        for content in ('{broken', '[]', '{"version": 99}'):
            path.write_text(content, encoding="utf-8")
            self.assertIsNone(self.store.get(self.book_id, self.chapters))
        valid = {"version": 1, "section": 0, "start": 7, "end": 14,
                 "text_hash": hashlib.sha256(self.chapters[0][1].encode()).hexdigest()}
        for invalid in ({"section": -1}, {"section": 1}, {"start": True},
                        {"start": -1}, {"end": 99}, {"text_hash": "changed"}):
            path.write_text(json.dumps(valid | invalid), encoding="utf-8")
            self.assertIsNone(self.store.get(self.book_id, self.chapters))

    def test_atomic_save_failure_preserves_previous_position(self):
        self.store.save(self.book_id, (0, 0, 6), self.chapters)
        with patch.object(Path, "replace", side_effect=OSError("Simulated write failure")):
            with self.assertRaises(OSError):
                self.store.save(self.book_id, (0, 7, 14), self.chapters)
        self.assertEqual(self.store.get(self.book_id, self.chapters), (0, 0, 6))
        self.assertFalse(list(self.store.directory.glob("*.tmp")))

    def test_positions_from_before_paragraph_pauses_remain_valid(self):
        old_text = 'Chapter 2 Exploring the Quiet Garden A small bird landed.'
        new_text = 'Chapter 2\nExploring the Quiet Garden\nA small bird landed.'
        start = old_text.index('A small')
        position = (0, start, len(old_text))
        self.store.save(self.book_id, position, [('One', old_text)])
        self.assertEqual(self.store.get(self.book_id, [('One', new_text)]), position)
        self.store.save(self.book_id, position, [('One', new_text)])
        self.assertEqual(self.store.get(self.book_id, [('One', old_text)]), position)

    def test_position_does_not_store_book_text_or_path(self):
        self.store.save(self.book_id, (0, 7, 14), self.chapters)
        content = (self.store.directory / f"{self.book_id}.json").read_text(encoding="utf-8")
        self.assertNotIn("First", content)
        self.assertNotIn(self.folder.name, content)
        self.assertEqual(self.store.get(self.book_id, self.chapters), (0, 7, 14))
        self.assertIsNone(self.store.get(self.book_id, [("One", "Changed text.")]))


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.directory = Path(self.folder.name)
        self.store = PositionStore(self.directory / "positions")
        self.book = self.directory / "book.epub"
        make_epub(self.book)
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            if not window.closed:
                window.close()
        self.folder.cleanup()

    def open_book(self, path=None, chapter=None):
        root = tk.Tk()
        root.withdraw()
        with patch("follow_reader.WindowsAudio", FakeAudio):
            window = ReadingWindow(root, position_store=self.store, app_state=AppState(self.directory / 'library.json'))
        self.windows.append(window)
        window.load_book(path or self.book, chapter)
        self.assertEqual(len(window.chapters), 2)
        return window

    def read_second_sentence(self, window, state="playing"):
        window.section = 1
        window._show_chapter()
        text = window.chapters[1][1]
        start = text.index("Second")
        end = text.index(" Last")
        window.cues = [SentenceCue(0, 900, 0, start - 1), SentenceCue(1000, 2000, start, end)]
        window.player.position = 1500
        window.player.state = state
        window._set_state(state)
        window._highlight((0, start - 1))
        return 1, start, end

    def assert_restored(self, window, expected):
        section, start, end = expected
        self.assertEqual(window.section, section)
        self.assertEqual(window.parts[0][0], start)
        self.assertEqual(window.highlighted, (start, end))
        self.assertEqual(window.reader.highlighted_text, window.chapters[section][1][start:end])
        self.assertEqual(window.state, "idle")
        self.assertFalse(window.player.play_calls)
        self.assertIsNone(window.audio_jobs)

    def test_close_and_reopen_restores_actual_audio_position_without_autoplay(self):
        for state in ("playing", "paused"):
            with self.subTest(state=state):
                first = self.open_book()
                expected = self.read_second_sentence(first, state)
                first.close()
                with patch("follow_reader.generate_audio") as speech:
                    reopened = self.open_book()
                    self.assert_restored(reopened, expected)
                    speech.assert_not_called()
                reopened.close()

    def test_stop_then_close_keeps_last_read_sentence(self):
        first = self.open_book()
        expected = self.read_second_sentence(first)
        first.stop()
        self.assertEqual(first.parts[0][0], 0)
        first.close()
        self.assert_restored(self.open_book(), expected)

    def test_switching_books_preserves_a_separate_position_for_each(self):
        second_book = self.directory / "other.epub"
        make_epub(second_book, "second-book")
        window = self.open_book()
        first_position = self.read_second_sentence(window)
        window.load_book(second_book)
        self.assertEqual(window.section, 0)
        window._highlight((18, len(window.chapters[0][1])))
        second_position = window.reading_position
        window.load_book(self.book)
        self.assert_restored(window, first_position)
        window.load_book(second_book)
        self.assert_restored(window, second_position)

    def test_renamed_copy_resumes_but_a_different_epub_does_not(self):
        window = self.open_book()
        expected = self.read_second_sentence(window)
        window.close()
        renamed = self.directory / "renamed.epub"
        renamed.write_bytes(self.book.read_bytes())
        self.assertEqual(book_fingerprint(renamed), book_fingerprint(self.book))
        self.assert_restored(self.open_book(renamed), expected)
        make_epub(renamed, "different-edition")
        self.assertNotEqual(book_fingerprint(renamed), book_fingerprint(self.book))
        self.assertEqual(self.open_book(renamed).section, 0)

    def test_explicit_section_overrides_saved_position(self):
        window = self.open_book()
        self.read_second_sentence(window)
        window.close()
        reopened = self.open_book(chapter=1)
        self.assertEqual(reopened.section, 0)
        self.assertEqual(reopened.parts[0][0], 0)

    def test_close_during_loading_restores_selected_sentence(self):
        window = self.open_book()
        text = window.chapters[0][1]
        start = text.index("Another")
        with patch.object(window, "_request_part", side_effect=lambda: window._set_state("loading")):
            window.seek_to_character(start + 2)
        expected = window.reading_position
        window.close()
        self.assert_restored(self.open_book(), expected)

    def test_save_failure_warns_once_and_does_not_prevent_closing(self):
        window = self.open_book()
        self.read_second_sentence(window)
        with patch.object(self.store, "save", side_effect=OSError("Read only")), patch("follow_reader.messagebox.showwarning") as warning:
            window.stop()
            window.close()
            warning.assert_called_once()
        self.assertTrue(window.closed)


if __name__ == "__main__":
    unittest.main()
