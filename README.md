# YapBook

A Windows EPUB reader that reads books aloud and highlights the current sentence as you follow along.

## Features

- Natural online voices through [edge-tts](https://github.com/rany2/edge-tts), with no API key required.
- A continuous reader that keeps EPUB formatting, images, and adjacent sections visible.
- Yellow sentence highlighting synchronized to the audio.
- Click any sentence to start reading from that point.
- Play, pause, resume, stop, and optional automatic scrolling.
- Voice selection, compact speed and volume sliders, text size, and section navigation.
- Background preparation of the next two audio chunks, including across section boundaries.
- A saved reading position for each EPUB, restored when you reopen it.
- An English desktop interface and a command-line reader.

YapBook requires Windows and an internet connection for speech. Text for the current and up to two upcoming audio chunks is sent to Microsoft's online speech service. EPUB images and styles are loaded locally. The speech client is unofficial, so service availability may change.

## Run from source

Developed and tested with Python 3.14 on Windows. In PowerShell:

```powershell
git clone https://github.com/McLeodolf/YapBook.git
cd YapBook
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe .\gui_entry.py
```

You can also double-click `YapBook.cmd` after setting up the Python environment, or drag an EPUB onto it.

Select **Open book**, choose a **Reading voice**, and select **Start reading**. **Refresh voice list** fetches the available voices; typing `en-` or `de-` filters the dropdown. Voice and speed can be changed while stopped.

The short **Speed** and **Volume** sliders sit next to each other. Speed is relative to normal: 0% is normal, negative values are slower, and positive values are faster.

**Volume** ranges from 0% (muted) to 100% and can be changed during playback. It stays at the selected level across pauses, sentence jumps, and section changes. A new app session starts at 100%.

Turn off **Auto-scroll while reading** to browse freely. Click a sentence to read from there. **Stop** resets playback to the beginning of the selected section; **Pause** keeps your position. Space pauses or resumes while the reader has keyboard focus.

YapBook remembers the last sentence read when you pause, stop, close the window, or open another book. Reopening that EPUB restores the sentence and its yellow highlight; select **Start reading** to continue. Audio does not start automatically. Stopping before closing still preserves the last sentence read. Each book has its own position, and renaming or moving the same EPUB keeps it. An explicit `--chapter` overrides the saved position.

Positions are saved locally in `%LOCALAPPDATA%\YapBook\positions`. These files contain book and text hashes plus sentence offsets, not book text, and survive replacing the EXE. This feature applies to the graphical reader; the plain CLI starts at section 1 unless you use `--chapter`.

## Build the Windows EXE

After setting up the Python environment:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

The build creates `dist\YapBook.exe`, which can run without a separate Python installation. Internet access is still needed for speech. Generated EXEs are not stored in the source repository.

## Command line

```powershell
# Read aloud
.\.venv\Scripts\python.exe .\read_epub.py "book.epub"

# Open the graphical reader
.\.venv\Scripts\python.exe .\read_epub.py "book.epub" --follow

# Choose a voice and read 15 percent faster
.\.venv\Scripts\python.exe .\read_epub.py "book.epub" --voice en-US-AriaNeural --rate 15

# List sections or available English voices
.\.venv\Scripts\python.exe .\read_epub.py "book.epub" --list-chapters
.\.venv\Scripts\python.exe .\read_epub.py --list-voices en
```

See [README.txt](README.txt) for the full usage guide, including text preview and starting from a particular section.

## Tests

Run the local tests on Windows:

```powershell
.\.venv\Scripts\python.exe -m unittest test_follow_reader test_html_reader test_reading_positions -v
```

These tests use generated sample text and do not call the online speech service. `verify_live_follow.py` and `verify_live_prefetch.py` are separate, optional online integration checks using invented text and muted playback.

## Limitations

- Requires a DRM-free EPUB containing text; there is no OCR or DRM removal.
- Complex browser layouts, embedded web fonts, and advanced SVG artwork may render differently.
- The next two audio chunks are prepared in the background to reduce loading pauses. Slow service responses or brief player transitions can still cause gaps.
- Voice, speed, volume, and display settings reset when the app closes.
