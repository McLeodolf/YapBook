"""Optional live Windows check with invented text and muted, uninterrupted playback."""
from pathlib import Path
import time
import tkinter as tk
from unittest.mock import patch

from app_state import AppState
from epub_document import EpubDocument
from follow_reader import ReadingWindow, generate_audio


def main():
    root = tk.Tk()
    root.withdraw()
    state = AppState(Path('test-output/continuous/library.json'))
    window = ReadingWindow(root, app_state=state)
    chapters = [('Test', 'This invented passage checks the small desktop reader (Smith et al., 2021). '
                         'The next sentence [12] should already be ready before it is needed. '
                         'A third sentence follows without pressing any button in the application. '
                         'The fourth sentence completes this quiet playback test.')]
    window.chapters = window.reader.set_document(EpubDocument.from_plain(chapters))
    window.chapter_box.configure(values=['Test'])
    window._show_chapter()
    window.volume.set(0)
    window.read_citations.set(False)
    window._citations_changed()
    requests, played, errors = [], [], []
    async def counted(text, voice, rate, cancelled, progress=None):
        requests.append(text)
        return await generate_audio(text, voice, rate, cancelled, progress)
    try:
        with patch('follow_reader.generate_audio', counted), patch('follow_reader.messagebox.showerror', lambda *args, **kwargs: errors.append(args)):
            window.toggle_play()
            deadline = time.monotonic()+150
            while time.monotonic()<deadline:
                root.update()
                if errors:
                    raise AssertionError(errors)
                if window.state=='playing' and (not played or played[-1]!=window.part):
                    played.append(window.part)
                    assert int(window.player.command(f'status {window.player.alias} volume'))==0
                if window.state=='idle' and 'Finished' in window.status.get():
                    break
                time.sleep(0.01)
            else:
                raise AssertionError('Continuous playback did not finish within 150 seconds')
            assert played==[0,1,2,3], played
            assert len(requests)==len(set(requests))<=4, requests
            assert all('2021' not in text and '[12]' not in text for text in requests)
            assert window.chapters[0][1]==chapters[0][1]
            # Restart the completed book; current plus two must come from cache.
            count=len(requests)
            window.toggle_play()
            deadline=time.monotonic()+5
            while time.monotonic()<deadline and window.state!='playing':
                root.update();time.sleep(0.01)
            assert window.state=='playing'
            assert len(requests)==count
            window.stop()
            print(f'PASS: four automatic sentence transitions, preserved citation display, muted Windows MP3 playback, {count} unique requests, cached restart.')
    finally:
        window.close()


if __name__=='__main__':
    main()
