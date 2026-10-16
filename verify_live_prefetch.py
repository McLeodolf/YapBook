"""Optional online prefetch check with invented text and muted Windows playback."""

import time
import tkinter as tk
from unittest.mock import patch

from epub_document import EpubDocument
from follow_reader import ReadingWindow, generate_audio


def wait_until(root, condition, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for speech generation or playback")


def main():
    root = tk.Tk()
    root.withdraw()
    window = ReadingWindow(root)
    chapters = [
        ("One", "This is a YapBook test with invented text. The next two parts are prepared while this part plays. We can pause and resume without losing the prepared audio. No text from a real book is used in this check."),
        ("Two", "The second section has already been prepared. Its sentence highlight should follow the audio."),
        ("Three", "The third section is ready as well. This is the final sentence of the test."),
    ]
    requests = []

    async def counted_audio(text, voice, rate, cancelled):
        requests.append(text)
        return await generate_audio(text, voice, rate, cancelled)

    try:
        window.chapters = chapters
        window.chapter_box.configure(values=[title for title, _ in chapters])
        window.reader.set_document(EpubDocument.from_plain(chapters))
        window._show_chapter()
        window.volume_slider.set(0)
        with patch("follow_reader.generate_audio", counted_audio):
            window.toggle_play()
            wait_until(root, lambda: window.state == "playing")
            window.toggle_play()
            wait_until(root, lambda: len(window.audio_cache) == 2)
            assert window.state == "paused"
            assert requests == [text for _, text in chapters]
            print("PASS: two upcoming sections prepared during paused playback", flush=True)
            window.toggle_play()

            for section in (1, 2):
                length = int(window.player.command(f"status {window.player.alias} length"))
                window.player.seek(max(0, length - 100))
                wait_until(root, lambda: window.section == section and window.state == "playing", timeout=5)
                assert len(requests) == 3, "A cached chunk was synthesized again"
                assert int(window.player.command(f"status {window.player.alias} volume")) == 0
                wait_until(root, lambda: window.highlighted is not None, timeout=5)
                assert window.reader.highlighted_text in chapters[section][1]
                print(f"PASS: cached section {section + 1} starts with volume and highlighting intact", flush=True)

            length = int(window.player.command(f"status {window.player.alias} length"))
            window.player.seek(max(0, length - 100))
            wait_until(root, lambda: window.state == "idle", timeout=5)
            assert window.audio_jobs is None and not window.audio_cache
            print("PASS: end of book releases playback and prefetch state", flush=True)
    finally:
        window.close()


if __name__ == "__main__":
    main()
