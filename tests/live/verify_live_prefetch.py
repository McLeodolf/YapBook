"""Optional live prefetch check with invented text and muted Windows playback."""

import argparse
import time
from yapbook import kokoro_tts
from pathlib import Path
import tempfile
import tkinter as tk
from unittest.mock import patch

from yapbook.epub_document import EpubDocument
from yapbook.follow_reader import ReadingWindow, generate_audio
from yapbook.app_state import AppState


def wait_until(root, condition, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for speech generation or playback")


def main(engine="edge"):
    if engine == "kokoro" and not kokoro_tts.is_installed():
        raise RuntimeError("Set up Kokoro once in YapBook before running the live GPU check.")
    preferences = tempfile.TemporaryDirectory(prefix="yapbook-prefetch-check-")
    root = tk.Tk()
    root.withdraw()
    settings = AppState(Path(preferences.name) / "library.json")
    settings.settings["engine"] = engine
    window = ReadingWindow(root, app_state=settings)
    chapters = [
        ("One", "This invented sentence checks a moving audio buffer while the current chapter is being read."),
        ("Two", "The second sentence is prepared before we arrive at this section."),
        ("Three", "A quiet library has a small garden beside its entrance."),
        ("Four", "A reader finds a comfortable chair by the sunny window."),
        ("Five", "The next chapter tells a story about a journey through the mountains."),
        ("Six", "There is enough time to prepare another sentence before this one finishes."),
        ("Seven", "Going back should reuse the audio that has already been downloaded."),
        ("Eight", "This final invented sentence completes the playback check."),
    ]
    requests = []
    local_synthesize = kokoro_tts.synthesize

    async def counted_audio(text, voice, rate, cancelled, progress=None):
        assert engine == "edge", "Local playback called the online voice service"
        requests.append(text)
        return await generate_audio(text, voice, rate, cancelled, progress)

    def counted_local(text, voice, speed, progress=None, cancelled=None):
        assert engine == "kokoro", "Online playback called the local engine"
        requests.append(text)
        return local_synthesize(text, voice, speed, progress, cancelled)

    try:
        window.chapters = chapters
        window.chapter_box.configure(values=[title for title, _ in chapters])
        window.reader.set_document(EpubDocument.from_plain(chapters))
        window._show_chapter()
        window.volume_slider.set(0)
        with patch("yapbook.follow_reader.generate_audio", counted_audio), patch("yapbook.kokoro_tts.synthesize", counted_local):
            window.toggle_play()
            wait_until(root, lambda: window.state == "playing", timeout=120 if engine == "kokoro" else 45)
            window.toggle_play()
            wait_until(root, lambda: len(window.audio_cache) == 5)
            assert window.state == "paused"
            assert sorted(requests) == sorted(text for _, text in chapters[:6])
            print("PASS: exactly five upcoming sentences prepared during paused playback", flush=True)
            window.toggle_play()

            for section in range(1, 7):
                length = int(window.player.command(f"status {window.player.alias} length"))
                window.player.seek(max(0, length - 100))
                wait_until(root, lambda: window.section == section and window.state == "playing", timeout=5)
                wait_until(root, lambda: len(window.audio_cache) == min(5, len(chapters) - section - 1))
                assert len(requests) == min(section + 6, len(chapters)), "Unexpected duplicate or out-of-window request"
                assert int(window.player.command(f"status {window.player.alias} volume")) == 0
                wait_until(root, lambda: window.highlighted is not None, timeout=5)
                assert window.reader.highlighted_text in chapters[section][1]
                print(f"PASS: cached section {section + 1} starts with volume and highlighting intact", flush=True)

            generation = window.generation
            for section in range(5, 0, -1):
                window.previous_sentence()
                assert window.section == section and window.state == "playing"
                assert window.generation == generation, "Buffered navigation restarted the worker queue"
                assert len(window.audio_buffer) <= 11
            print("PASS: previous five sentences replay immediately from RAM", flush=True)
            for section in range(2, len(chapters)):
                window.next_sentence()
                wait_until(root, lambda: window.section == section and window.state == "playing", timeout=5)
                wait_until(root, lambda: len(window.audio_cache) == min(5, len(chapters) - section - 1))
            assert len(requests) == len(chapters), "Replay caused a duplicate voice request"
            print("PASS: rolling refill and backward/forward replay use eight unique requests", flush=True)

            length = int(window.player.command(f"status {window.player.alias} length"))
            window.player.seek(max(0, length - 100))
            wait_until(root, lambda: window.state == "idle", timeout=5)
            assert window.audio_jobs is None and not window.audio_cache
            print("PASS: end of book releases playback and prefetch state", flush=True)
    finally:
        window.close()
        preferences.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("edge", "kokoro"), default="edge")
    main(parser.parse_args().engine)
