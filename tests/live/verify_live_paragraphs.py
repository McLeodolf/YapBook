"""Optional online check using invented headings and paragraph text."""

import asyncio
from pathlib import Path
import tempfile
import threading

import edge_tts

from yapbook.follow_reader import generate_audio
from yapbook.read_epub import prepare_speech
from yapbook.windows_audio import WindowsAudio


async def main():
    text = 'Chapter 2\nExploring the Quiet Garden\nA small bird landed on the wall.\nThe garden was peaceful.'
    audio, cues = await generate_audio(text, 'en-US-AriaNeural', 0, threading.Event())
    sentences = [text[cue.start_char:cue.end_char] for cue in cues]
    assert sentences == text.splitlines(), sentences
    assert all(first.start_ms < second.start_ms for first, second in zip(cues, cues[1:]))
    print('PASS: chapter label, heading and paragraphs have separate speech cues.', flush=True)
    print('Sentence timings (milliseconds):', [(round(cue.start_ms), round(cue.end_ms)) for cue in cues], flush=True)
    # Sentence event durations can overlap; word timings expose the actual breaks.
    words = []
    spoken, _ = prepare_speech(text)
    async for event in edge_tts.Communicate(spoken, 'en-US-AriaNeural', boundary='WordBoundary').stream():
        if event['type'] == 'WordBoundary':
            words.append(event)
    gaps = []
    for opening in ('Exploring', 'A', 'The'):
        index = next(index for index, word in enumerate(words) if word['text'] == opening)
        previous = words[index - 1]
        gaps.append((words[index]['offset'] - previous['offset'] - previous['duration']) / 10_000)
    print('Structural pause gaps (milliseconds):', gaps, flush=True)
    assert min(gaps) >= 150, gaps
    with tempfile.TemporaryDirectory(prefix='yapbook-paragraph-check-') as folder:
        path = Path(folder) / 'speech.mp3'
        path.write_bytes(audio)
        player = WindowsAudio()
        try:
            player.play(path, volume=0)
            length = int(player.command(f'status {player.alias} length'))
            assert length >= cues[-1].start_ms
            print('PASS: generated MP3 opens in the Windows player, muted.', flush=True)
        finally:
            player.close()


if __name__ == '__main__':
    asyncio.run(main())
