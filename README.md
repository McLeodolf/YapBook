# YapBook

<img src="assets/yapbook.png" alt="YapBook icon: an open book and a speaker" width="96" height="96">

An EPUB reader for Windows and the web that reads books aloud and highlights the current sentence as you follow along.

For the browser version and free Streamlit deployment, see [web/README.md](web/README.md). Both versions include saved light/dark mode.

## Features

- Natural online voices through [edge-tts](https://github.com/rany2/edge-tts), with no API key required.
- An AI icon beside the theme toggle switches to local Kokoro English voices: WebGPU in the browser, NVIDIA CUDA in the Windows app.
- A continuous reader that keeps EPUB formatting, images, and adjacent sections visible.
- Yellow sentence highlighting synchronized to the audio.
- Context-aware sentence boundaries for common abbreviations, name initials and German ordinals such as `17. Jahrhundert` or `105. Geburtstag`, in both readers.
- Natural speech pauses at headings, paragraphs, and explicit line breaks.
- Click any sentence to start reading from that point.
- Read internal book links aloud, then jump to their destination and continue reading.
- Play, pause, resume, stop, and optional automatic scrolling.
- Voice selection, compact speed and volume sliders, text size, and section navigation.
- A moving RAM buffer keeps the previous five and next five sentences ready, including across section boundaries.
- Search the entire open EPUB with the magnifying glass or Ctrl+F, then select a result to jump there.
- A saved **Read citations** checkbox: turn it off to omit recognized author–year references, numbered citations and marked footnote references from speech. Original book text remains visible; quotations and mathematical superscripts are retained. Citation recognition is conservative and unusual formats may still be read.
- Sentence boundaries keep references such as `Smith et al. (2021)` together.
- In online mode, six bounded speech jobs prepare the current sentence and the next five concurrently. The buffer refills as playback advances, and recent sentences play directly from RAM when you go back. Successful audio is cached locally by spoken text, voice and effective speed; identical in-flight requests share one result.
- A saved reading position for each EPUB, restored when you reopen it.
- An English desktop interface and a command-line reader.
- Voice preview, language/name filters and favorite voices.
- Remembered voice, speed, volume, text size and auto-scroll settings.
- Recent books, named bookmarks, previous/next-sentence navigation and section progress.
- A sleep timer for 5, 10, 15, 20, 30, 45, 60, 90, or 120 minutes, or the end of the current section.
- Saved light/dark mode for the controls and book page; switch with the moon/sun icon.
- Audio loading time and received bytes, cancellable requests and a 90-second deadline.

The desktop app requires Windows. In the default online mode, speech needs an internet connection, and text for the current sentence and up to five upcoming sentences is sent to Microsoft's online speech service. EPUB images and styles are loaded locally. The speech client is unofficial, so service availability may change.

The desktop audio cache is `%LOCALAPPDATA%\YapBook\speech.sqlite3`; the web cache is in this browser's IndexedDB. Stop, pause, seeking and reopening a book reuse completed audio. A started request may finish into the cache after Stop; queued playback is detached. Failed requests require an explicit retry. Changing engine, voice, speed or spoken text requires different audio. Clearing app/browser data, unavailable storage or closing during an unfinished request can require another request; caches do not synchronize between devices. The cache grows as new text is read and is not automatically deleted.

## Local Kokoro voices

Use the sparkle **AI** icon beside the moon/sun icon to switch between online voices and **Kokoro GPU**. Switching stops playback at the current sentence and remembers a separate voice choice for each engine. Select Play to continue, or Preview voice to try it. Online mode remains the default.

- **Windows:** Kokoro requires a compatible NVIDIA GPU and current driver. On the first Play or Preview, the app asks before downloading a separate runtime and model (several GB). The normal EXE and its Python environment remain separate from that runtime. Setup and model progress appear in the status line. Intel/AMD GPUs are not supported by this native CUDA backend.
- **Web:** Kokoro runs in a browser worker on the user's GPU through WebGPU, with a one-time model download. Browser/GPU support is checked, and unsupported devices show an error. No book text is sent through Streamlit or Microsoft's speech service in this mode.
- **Voices:** This integration exposes Kokoro's American and British English voices. It does not provide German speech; use the existing online voices for German and other languages. The default local voice is `af_heart`.
- **Buffering:** The same current/previous-five/next-five window and speech cache are used, with separate cache keys for each engine. Local GPU jobs run one at a time to avoid competing for GPU memory. Kokoro speed 0% uses its unchanged native speed of 1.0×. The slider ranges from −50% (0.5×) to +100% (2.0×). Only online voices use the −15% baseline. Long sentences may require several local model calls but retain their sentence highlight.

There is no API key or per-request fee. After the runtime, model and selected voice have been downloaded, synthesis is local. Initial downloads still need internet. Failure never silently switches to cloud speech or CPU synthesis; use the AI icon to choose online mode yourself. Local speed depends on the GPU, and the first sentence can take longer while the model initializes. Closing the app releases the native GPU worker. Its runtime, downloads and model files are stored separately in `%LOCALAPPDATA%\YapBook\kokoro-v1`, so replacing or moving the EXE does not download them again.

Kokoro is provided by [hexgrad](https://github.com/hexgrad/kokoro), with browser support through [Kokoro.js](https://github.com/hexgrad/kokoro/tree/main/kokoro.js). Model weights are Apache-2.0 licensed; the optional runtimes and phonemizer retain their respective licenses.

## Repository layout

```text
YapBook/
├── yapbook/             Python desktop app, CLI, reader and speech engines
├── assets/              Desktop artwork and icons
├── requirements/        Desktop, EXE-build and optional Kokoro dependency files
├── scripts/             Windows build script and packaging launcher
├── tests/
│   ├── desktop/         Offline desktop regression tests
│   └── live/            Optional speech-service and GPU playback checks
├── web/
│   ├── streamlit_app.py Streamlit deployment entry point
│   ├── requirements.txt Web server dependencies
│   ├── tests/           Web backend tests
│   └── frontend/        Browser source, tests and built deployment assets
├── .github/             Actions workflows and Dependabot configuration
├── YapBook.cmd          Windows source launcher
└── README.md
```

Run the desktop commands below from the repository root. The application is a Python package: use `python -m yapbook` for the window and `python -m yapbook.read_epub` for the command-line reader. The build creates `dist/YapBook.exe`; generated executables and local environments are not committed. The web entry point and its dependency file stay together under `web/` for Streamlit deployment.

## Run from source

Developed and tested with Python 3.14 on Windows. In PowerShell:

```powershell
git clone https://github.com/McLeodolf/YapBook.git
cd YapBook
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r .\requirements\requirements.txt
.\.venv\Scripts\python.exe -m yapbook
```

You can also double-click `YapBook.cmd` after setting up the Python environment, or drag an EPUB onto it.

The toolbar uses familiar icons with English tooltips, also shown on keyboard focus: folder to **Open book**, triangle to **Start reading**, pause bars, square to **Stop**, and a star for favorites. Book controls sit in the header, playback and sleep controls together, and section/bookmark/text-size controls above the page. Hover over an icon to see its action.

Choose **Language**, then **Reading voice**. Type directly into the voice field to filter its dropdown (for example `Brian`); open the arrow or press Down to select a matching voice. Escape restores the saved voice. Choose **Favorites** at the top of the **Language** dropdown to see starred voices from every language. **Favorites only** narrows a selected language to starred voices. The default is `en-US-BrianMultilingualNeural`. **Refresh voice list** fetches the online catalog. **Preview voice** plays a short sample at the selected speed and volume without moving your reading position. Voice and speed can be changed while stopped.

The short **Speed** and **Volume** sliders sit next to each other. The displayed speed starts at **0%**. For online voices this uses **−15%** at the speech service; for Kokoro it uses the model's unchanged **1.0×** default speed. Every displayed percentage point adds one point: +15% uses service rate 0%, and −10% uses service rate −25%. These online rate examples also apply to the CLI.

**Volume** ranges from 0% (muted) to 100% and can be changed during playback. Voice, speed, volume, text size and auto-scroll are remembered between sessions. An explicit `--voice` or `--rate` overrides the saved value for the GUI; the plain CLI uses its defaults when these options are omitted.

Turn off **Auto-scroll while reading** to browse freely. Click a sentence to read from there. **Stop** resets playback to the beginning of the selected section; **Pause** keeps your position. Space pauses or resumes while the reader has keyboard focus.

Click an internal book link to hear its label first. When that audio finishes, YapBook jumps to the target and continues reading there. Pause defers the jump; Stop or another navigation cancels it. Links keep the full book visible, including when auto-scroll is off.

**Previous sentence** and **Next sentence** start the adjacent sentence, including across section boundaries. **Section progress** shows text progress through the current section, not an estimated audio duration.

**Recent books** remembers the 20 most recently opened EPUBs. **Add bookmark** saves the current sentence under a name. **Bookmarks** lets you return to or delete multiple bookmarks for the current book. Jumping to a bookmark while reading resumes there; while stopped it only restores the position. Moving a book preserves its bookmarks; reopen it with **Open book** to update its recent file location.

**Sleep timer** pauses after 5, 10, 15, 20, 30, 45, 60, 90, or 120 minutes of elapsed time, including loading and manual pauses. The small magnifying glass beside the timer opens book search; Ctrl+F also works. **End of section** finishes the selected section and waits before reading the next one. The timer is cleared when it finishes, when you press **Stop**, switch sections manually, or open another book. Timers are not restored after restart.

During online audio loading, the status shows elapsed seconds and the amount of audio received. A request is cancelled after 90 seconds; **Stop** cancels it immediately. Failures keep the current sentence ready to retry with **Start reading**. Slow or unavailable voices can still fail because the speech service is external. The voice list is a catalog, not a guarantee that every voice responds immediately.

Each audio request contains one sentence. While it plays, the next five sentences are prepared, including across section boundaries. The previous five remain in RAM, giving a window of up to eleven sentences including the current one. Downloaded audio can play immediately while its persistent cache copy is saved in the background. Exceptionally long sentences are split at around 700 characters. The status shows the actual request size. Clicking a sentence starts with that sentence, without adding several following paragraphs to the same request.

Internal periods in names such as `Matthew C. Perry` and common ordinal expressions stay inside the same request and yellow highlight. Explicit paragraph and heading breaks still separate the text. If a voice returns several timing fragments for one sentence, YapBook combines their highlights; the voice service still controls pronunciation and pauses within the audio.

YapBook remembers the last sentence read when you pause, stop, close the window, or open another book. Reopening that EPUB restores the sentence and its yellow highlight; select **Start reading** to continue. Audio does not start automatically. Stopping before closing still preserves the last sentence read. Each book has its own position, and renaming or moving the same EPUB keeps it. An explicit `--chapter` overrides the saved position.

Positions are saved locally in `%LOCALAPPDATA%\YapBook\positions`. These files contain book and text hashes plus sentence offsets, not book text, and survive replacing the EXE. This feature applies to the graphical reader; the plain CLI starts at section 1 unless you use `--chapter`.

Preferences, favorite voices, recent file paths/titles and bookmark names/offsets are stored locally in `%LOCALAPPDATA%\YapBook\library.json`. No EPUB content or audio is saved in this library file. Bookmarks include a text hash to reject stale positions if the book changes.

## Build the Windows EXE

After setting up the Python environment:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
```

The build creates `dist\YapBook.exe`, which can run without a separate Python installation. Internet access is needed for online voices and the optional first-time Kokoro setup. Generated EXEs are not stored in the source repository.

The artwork in `assets/` is bundled into the EXE for its Explorer, taskbar, Alt-Tab, and window icons, and the small logo in the reader. Keep `assets/` at the repository root beside `yapbook/` when running from source.

## Command line

```powershell
# Read aloud
.\.venv\Scripts\python.exe -m yapbook.read_epub "book.epub"

# Open the graphical reader
.\.venv\Scripts\python.exe -m yapbook.read_epub "book.epub" --follow

# Choose a voice and add 15 points to the baseline (service rate 0%)
.\.venv\Scripts\python.exe -m yapbook.read_epub "book.epub" --voice en-US-AriaNeural --rate 15

# List sections or available English voices
.\.venv\Scripts\python.exe -m yapbook.read_epub "book.epub" --list-chapters
.\.venv\Scripts\python.exe -m yapbook.read_epub --list-voices en
```

```powershell
# Start at section 3
.\.venv\Scripts\python.exe -m yapbook.read_epub "book.epub" --chapter 3

# Preview extracted text without sending it to the speech service
.\.venv\Scripts\python.exe -m yapbook.read_epub "book.epub" --chapter 3 --preview

# Read a German book with a German voice
.\.venv\Scripts\python.exe -m yapbook.read_epub "book.epub" --voice de-DE-KatjaNeural
```

Section numbers follow the EPUB's internal reading order and may differ from printed chapter numbers. Press Ctrl+C to stop the plain CLI.

## Tests

Run the local tests on Windows:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests/desktop -t . -p 'test_*.py' -v
```

These tests use generated sample text and do not call the online speech service. `tests/live/verify_live_follow.py`, `tests/live/verify_live_prefetch.py`, and `tests/live/verify_live_paragraphs.py` are separate, optional live checks using invented text and muted playback. After setting up Kokoro once in the app, `python -m tests.live.verify_live_prefetch --engine kokoro` checks real local GPU playback, five-ahead refill and five-back replay with no duplicate synthesis or online speech calls. Without this flag, the script checks the online engine. Run these probes as modules from the repository root so they can import the application package.

The native Windows audio-device check runs separately with `python -m unittest tests.live.test_windows_audio -v`. It exercises real muted WAV playback, volume, pause/resume and seeking, so it needs a Windows desktop with an available audio device; hosted CI runners do not provide one.

The web backend tests run from `web/` with `python -m unittest discover -s tests -v`.
Frontend checks run from `web/frontend/` with `npm ci --ignore-scripts`,
`npm run lint`, `npm test`, and `npm run test:browser`. Install Chromium first
with `npx playwright install chromium` when using the CI browser configuration.

GitHub Actions runs the app tests and frontend build for pull requests. The
manual **Build Windows EXE** workflow creates a downloadable EXE artifact.
Routine dependency updates are grouped weekly, with at most one open frontend
update PR and one GitHub Actions update PR. Security updates remain separate.

## Limitations

- Requires a DRM-free EPUB containing text; there is no OCR or DRM removal.
- Complex browser layouts, embedded web fonts, and advanced SVG artwork may render differently.
- The next five audio chunks are prepared in the background to reduce loading pauses; the previous five remain ready for backward navigation. Slow service responses or brief player transitions can still cause gaps.
- The desktop interface and Windows audio player cannot run in a web browser; a hosted version needs a browser reader and audio player.
