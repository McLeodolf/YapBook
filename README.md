# YapBook

<img src="assets/yapbook.png" alt="YapBook icon: an open book and a speaker" width="96" height="96">

An EPUB reader for Windows and the web that reads books aloud and highlights the current sentence as you follow along.

For the browser version and free Streamlit deployment, see [web/README.md](web/README.md). Both versions include saved light/dark mode.

## Features

- Natural online voices through [edge-tts](https://github.com/rany2/edge-tts), with no API key required.
- A continuous reader that keeps EPUB formatting, images, and adjacent sections visible.
- Yellow sentence highlighting synchronized to the audio.
- Natural speech pauses at headings, paragraphs, and explicit line breaks.
- Click any sentence to start reading from that point.
- Read internal book links aloud, then jump to their destination and continue reading.
- Play, pause, resume, stop, and optional automatic scrolling.
- Voice selection, compact speed and volume sliders, text size, and section navigation.
- Background preparation of the next two sentences, including across section boundaries.
- A saved reading position for each EPUB, restored when you reopen it.
- An English desktop interface and a command-line reader.
- Voice preview, language/name filters and favorite voices.
- Remembered voice, speed, volume, text size and auto-scroll settings.
- Recent books, named bookmarks, previous/next-sentence navigation and section progress.
- A sleep timer for 15/30 minutes or the end of the current section.
- Saved light/dark mode for the controls and book page; switch with the moon/sun icon.
- Audio loading time and received bytes, cancellable requests and a 90-second deadline.

YapBook requires Windows and an internet connection for speech. Text for the current sentence and up to two upcoming sentences is sent to Microsoft's online speech service. EPUB images and styles are loaded locally. The speech client is unofficial, so service availability may change.

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

The toolbar uses familiar icons with English tooltips, also shown on keyboard focus: folder to **Open book**, triangle to **Start reading**, pause bars, square to **Stop**, and a star for favorites. Book controls sit in the header, playback and sleep controls together, and section/bookmark/text-size controls above the page. Hover over an icon to see its action.

Choose **Language**, then **Reading voice**. Type directly into the voice field to filter its dropdown (for example `Brian`); open the arrow or press Down to select a matching voice. Escape restores the saved voice. **Favorites only** narrows the list to starred voices. The default is `en-US-BrianMultilingualNeural`. **Refresh voice list** fetches the online catalog. **Preview voice** plays a short sample at the selected speed and volume without moving your reading position. Voice and speed can be changed while stopped.

The short **Speed** and **Volume** sliders sit next to each other. The displayed speed starts at **0%**, a comfortable baseline that uses **−15%** at the speech service. Every displayed percentage point adds one point: +15% uses service rate 0%, and −10% uses service rate −25%. The CLI uses the same scale.

**Volume** ranges from 0% (muted) to 100% and can be changed during playback. Voice, speed, volume, text size and auto-scroll are remembered between sessions. An explicit `--voice` or `--rate` overrides the saved value for the GUI; the plain CLI uses its defaults when these options are omitted.

Turn off **Auto-scroll while reading** to browse freely. Click a sentence to read from there. **Stop** resets playback to the beginning of the selected section; **Pause** keeps your position. Space pauses or resumes while the reader has keyboard focus.

Click an internal book link to hear its label first. When that audio finishes, YapBook jumps to the target and continues reading there. Pause defers the jump; Stop or another navigation cancels it. Links keep the full book visible, including when auto-scroll is off.

**Previous sentence** and **Next sentence** start the adjacent sentence, including across section boundaries. **Section progress** shows text progress through the current section, not an estimated audio duration.

**Recent books** remembers the 20 most recently opened EPUBs. **Add bookmark** saves the current sentence under a name. **Bookmarks** lets you return to or delete multiple bookmarks for the current book. Jumping to a bookmark while reading resumes there; while stopped it only restores the position. Moving a book preserves its bookmarks; reopen it with **Open book** to update its recent file location.

**Sleep timer** pauses after 15 or 30 minutes of elapsed time, including loading and manual pauses. **End of section** finishes the selected section and waits before reading the next one. The timer is cleared when it finishes, when you press **Stop**, switch sections manually, or open another book. Timers are not restored after restart.

During audio loading, the status shows elapsed seconds and the amount of audio received. A request is cancelled after 90 seconds; **Stop** cancels it immediately. Failures keep the current sentence ready to retry with **Start reading**. Slow or unavailable voices can still fail because the speech service is external. The voice list is a catalog, not a guarantee that every voice responds immediately.

Each audio request contains one sentence. While it plays, the next two sentences are prepared, including across section boundaries. Exceptionally long sentences are split at around 700 characters. The status shows the actual request size. Clicking a sentence starts with that sentence, without adding several following paragraphs to the same request.

YapBook remembers the last sentence read when you pause, stop, close the window, or open another book. Reopening that EPUB restores the sentence and its yellow highlight; select **Start reading** to continue. Audio does not start automatically. Stopping before closing still preserves the last sentence read. Each book has its own position, and renaming or moving the same EPUB keeps it. An explicit `--chapter` overrides the saved position.

Positions are saved locally in `%LOCALAPPDATA%\YapBook\positions`. These files contain book and text hashes plus sentence offsets, not book text, and survive replacing the EXE. This feature applies to the graphical reader; the plain CLI starts at section 1 unless you use `--chapter`.

Preferences, favorite voices, recent file paths/titles and bookmark names/offsets are stored locally in `%LOCALAPPDATA%\YapBook\library.json`. No EPUB content or audio is saved in this library file. Bookmarks include a text hash to reject stale positions if the book changes.

## Build the Windows EXE

After setting up the Python environment:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

The build creates `dist\YapBook.exe`, which can run without a separate Python installation. Internet access is still needed for speech. Generated EXEs are not stored in the source repository.

The artwork in `assets/` is bundled into the EXE for its Explorer, taskbar, Alt-Tab, and window icons, and the small logo in the reader. Keep this folder beside the Python files when running from source.

## Command line

```powershell
# Read aloud
.\.venv\Scripts\python.exe .\read_epub.py "book.epub"

# Open the graphical reader
.\.venv\Scripts\python.exe .\read_epub.py "book.epub" --follow

# Choose a voice and add 15 points to the baseline (service rate 0%)
.\.venv\Scripts\python.exe .\read_epub.py "book.epub" --voice en-US-AriaNeural --rate 15

# List sections or available English voices
.\.venv\Scripts\python.exe .\read_epub.py "book.epub" --list-chapters
.\.venv\Scripts\python.exe .\read_epub.py --list-voices en
```

See [README.txt](README.txt) for the full usage guide, including text preview and starting from a particular section.

## Tests

Run the local tests on Windows:

```powershell
.\.venv\Scripts\python.exe -m unittest test_follow_reader test_html_reader test_reading_positions test_app_state -v
```

These tests use generated sample text and do not call the online speech service. `verify_live_follow.py`, `verify_live_prefetch.py`, and `verify_live_paragraphs.py` are separate, optional online integration checks using invented text and muted playback.

## Limitations

- Requires a DRM-free EPUB containing text; there is no OCR or DRM removal.
- Complex browser layouts, embedded web fonts, and advanced SVG artwork may render differently.
- The next two audio chunks are prepared in the background to reduce loading pauses. Slow service responses or brief player transitions can still cause gaps.
- The desktop interface and Windows audio player cannot run in a web browser; a hosted version needs a browser reader and audio player.
