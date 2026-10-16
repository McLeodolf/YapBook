"""Entry point for the standalone Windows application."""

import argparse
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import messagebox

from follow_reader import ReadingWindow, run_follow
from epub_document import EpubDocument
from reading_positions import PositionStore


def main():
    parser = argparse.ArgumentParser(description="YapBook · Read EPUBs aloud with synchronized sentence highlighting")
    parser.add_argument("epub", nargs="?", type=Path)
    parser.add_argument("--voice", default="en-US-AriaNeural")
    parser.add_argument("--rate", type=int, default=0)
    parser.add_argument("--chapter", type=int, help="start at this section instead of the saved position")
    parser.add_argument("--self-test", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.self_test:
            with tempfile.TemporaryDirectory(prefix="yapbook-self-test-") as folder:
                root = tk.Tk()
                root.withdraw()
                store = PositionStore(folder)
                window = ReadingWindow(root, position_store=store)
                document = EpubDocument.from_plain([('One', 'First sentence.'), ('Two', 'Second sentence.'), ('Three', 'Third sentence.')])
                window.chapters = window.reader.set_document(document)
                assert len(window.chapters) == 3
                window.book_id = "0" * 64
                window.section = 1
                window.chapter_box.configure(values=[title for title, _ in window.chapters])
                window._show_chapter()
                window._highlight((0, 16))
                root.update()
                window.close()
                assert store.get(window.book_id, window.chapters) == (1, 0, 16)
            args.self_test.write_text("OK: HTML renderer, three sections, highlighting, Windows audio and saved reading positions.\n", encoding="utf-8")
        else:
            run_follow(args.epub, args.voice, args.rate, args.chapter)
    except Exception as exc:
        if args.self_test:
            args.self_test.write_text(f"ERROR: {exc}\n", encoding="utf-8")
            raise SystemExit(1)
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("YapBook could not start", str(exc), parent=root)
        root.destroy()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
