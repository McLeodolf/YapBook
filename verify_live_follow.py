"""Integration check with invented text; all playback stays muted."""

import asyncio
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk

from follow_reader import ReadingWindow, generate_audio
from windows_audio import WindowsAudio


text = 'Hallo Welt. Dr. Weber liest heute ein Buch. Dies ist der letzte Satz.'
audio, cues = asyncio.run(generate_audio(text, 'de-DE-KatjaNeural', 0, threading.Event()))
assert len(audio) > 1000 and len(cues) >= 3
assert text[cues[0].start_char:cues[0].end_char] == 'Hallo Welt.'
print(f'PASS: live audio and {len(cues)} aligned sentence timestamps', flush=True)

with tempfile.TemporaryDirectory(prefix='epub-timing-check-') as folder:
    path = Path(folder) / 'speech.mp3'
    path.write_bytes(audio)
    player = WindowsAudio()
    try:
        player.play(path, volume=0)
        time.sleep(0.3)
        player.pause()
        paused_at = player.position_ms()
        time.sleep(0.25)
        assert abs(player.position_ms() - paused_at) < 25
        player.resume()
        time.sleep(0.2)
        assert player.position_ms() > paused_at
        player.seek(cues[1].start_ms)
        assert abs(player.position_ms() - cues[1].start_ms) < 150
        assert player.mode() == 'playing'
    finally:
        player.close()
    path.unlink()
print('PASS: Windows playback clock, pause/resume, sentence seek and file release', flush=True)

root = tk.Tk()
root.withdraw()
window = ReadingWindow(root)
try:
    window.chapters = [('Testkapitel', text)]
    window.chapter_box.configure(values=['Testkapitel'])
    window._show_chapter()
    window.volume_slider.set(0)
    window._set_state('loading')
    window.waiting_for = (0, 0)
    window.audio_requested.add((0, 0))
    window.results.put((window.generation, (0, 0), (audio, cues), None))
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and window.highlighted is None:
        root.update()
        time.sleep(0.02)
    assert window.highlighted == (cues[0].start_char, cues[0].end_char), window.highlighted
    window.seek_to_character(cues[-1].start_char + 2)
    assert window.highlighted == (cues[-1].start_char, cues[-1].end_char)
    assert abs(window.player.position_ms() - cues[-1].start_ms) < 150
    window.toggle_play()
    assert window.state == 'paused'
    marked = window.highlighted
    root.update()
    assert window.highlighted == marked
    window.toggle_play()
    assert window.state == 'playing'
    window.stop()
    assert window.audio_temp is None and window.highlighted is None
finally:
    window.close()
print('PASS: reading window follows live audio, seeks on selection, pauses and stops', flush=True)
