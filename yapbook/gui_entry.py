"""Entry point for the standalone Windows application."""

import argparse
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import messagebox

from .app_branding import apply_app_icon
from .app_state import AppState
from .follow_reader import ReadingWindow, run_follow
from . import kokoro_tts
from .epub_document import EpubDocument
from .reading_positions import PositionStore


def require_self_test(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description="YapBook · Read EPUBs aloud with synchronized sentence highlighting")
    parser.add_argument("epub", nargs="?", type=Path)
    parser.add_argument("--voice")
    parser.add_argument("--rate", type=int, help="speed adjustment; 0 uses the comfortable -15%% baseline")
    parser.add_argument("--chapter", type=int, help="start at this section instead of the saved position")
    parser.add_argument("--self-test", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--self-test-kokoro", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.self_test_kokoro and not args.self_test:
        parser.error("--self-test-kokoro requires --self-test")
    if args.rate is not None and not -50 <= args.rate <= 100:
        parser.error("--rate must be between -50 and 100")
    try:
        if args.self_test:
            with tempfile.TemporaryDirectory(prefix="yapbook-self-test-") as folder:
                root = tk.Tk()
                root.withdraw()
                store = PositionStore(folder)
                window = ReadingWindow(root, position_store=store, app_state=AppState(Path(folder) / "library.json"))
                require_self_test((window.app_logo.width(), window.app_logo.height()) == (40, 40), "Incorrect app icon size")
                require_self_test(root.tk.call(str(window.app_logo), "transparency", "get", 0, 0), "App icon lost transparency")
                document = EpubDocument.from_plain([('One', 'First sentence.'), ('Two', 'Second sentence.'), ('Three', 'Third sentence.')])
                window.chapters = window.reader.set_document(document)
                require_self_test(len(window.chapters) == 3, "Missing reader sections")
                window.book_id = "0" * 64
                window.section = 1
                window.chapter_box.configure(values=[title for title, _ in window.chapters])
                window._show_chapter()
                window._highlight((0, 16))
                window.toggle_theme()
                require_self_test(window.reader.dark and window.reader.highlighted_text == 'Second sentence.', "Theme or highlighting failed")
                window.toggle_theme()
                require_self_test(not window.reader.dark, "Light theme failed")
                position = window.reading_position
                window.toggle_engine()
                require_self_test(window.engine == "kokoro" and window.voice.get() == kokoro_tts.DEFAULT_VOICE,
                                  "Local engine selection failed")
                require_self_test(window.reading_position == position, "Engine switch moved the reading position")
                require_self_test(kokoro_tts._resource("kokoro_worker.py").is_file()
                                  and kokoro_tts._resource("requirements-kokoro.lock").is_file(),
                                  "Optional Kokoro setup resources are missing")
                window.toggle_engine()
                require_self_test(window.engine == "edge", "Online engine selection failed")
                if args.self_test_kokoro:
                    require_self_test(kokoro_tts.is_installed(), "Set up Kokoro before the GPU self-test")
                    audio, duration = kokoro_tts.synthesize("At the café, Matthew C. Perry found 17 books.", speed=1.0)
                    require_self_test(audio.startswith(b"RIFF") and duration > 0, "Kokoro did not return WAV audio")
                    sample = Path(folder) / "kokoro-self-test.wav"
                    sample.write_bytes(audio)
                    window.player.play(sample, volume=0)
                    require_self_test(window.player.mode() == "playing", "Packaged Kokoro audio did not start")
                    require_self_test(int(window.player.command(f"status {window.player.alias} volume")) == 0,
                                      "Packaged Kokoro playback was not muted")
                    window.player.pause()
                    window.player.seek(100)
                    require_self_test(window.player.mode() == "playing", "Packaged Kokoro audio seek failed")
                root.update()
                window.close()
                require_self_test(store.get(window.book_id, window.chapters) == (1, 0, 16), "Reading position was not saved")
            if args.self_test_kokoro:
                args.self_test.write_text("OK: packaged Kokoro GPU synthesis, Unicode text, WAV playback, mute, seek and helper shutdown.\n", encoding="utf-8")
                return
            args.self_test.write_text("OK: app artwork, HTML renderer, three sections, light/dark themes, engine switching, Kokoro setup resources, highlighting, Windows audio and saved reading positions.\n", encoding="utf-8")
        else:
            run_follow(args.epub, args.voice, args.rate, args.chapter)
    except Exception as exc:
        if args.self_test:
            args.self_test.write_text(f"ERROR: {exc}\n", encoding="utf-8")
            raise SystemExit(1)
        root = tk.Tk()
        root.withdraw()
        apply_app_icon(root)
        messagebox.showerror("YapBook could not start", str(exc), parent=root)
        root.destroy()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
