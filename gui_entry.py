"""Entry point for the standalone Windows application."""

import argparse
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

from follow_reader import ReadingWindow, run_follow
from epub_document import EpubDocument


def main():
    parser = argparse.ArgumentParser(description="YapBook · Read EPUBs aloud with synchronized sentence highlighting")
    parser.add_argument("epub", nargs="?", type=Path)
    parser.add_argument("--voice", default="en-US-AriaNeural")
    parser.add_argument("--rate", type=int, default=0)
    parser.add_argument("--chapter", type=int, default=1)
    parser.add_argument("--self-test", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.self_test:
            root = tk.Tk()
            root.withdraw()
            window = ReadingWindow(root)
            document = EpubDocument.from_plain([('One', 'First sentence.'), ('Two', 'Second sentence.'), ('Three', 'Third sentence.')])
            window.reader.set_document(document)
            assert len(window.reader.chapters) == 3
            window.reader.highlight(1, (0, 16))
            root.update()
            window.close()
            args.self_test.write_text("OK: HTML renderer, three sections, highlighting and Windows audio initialized.\n", encoding="utf-8")
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
