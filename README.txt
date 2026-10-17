YapBook for Windows

A small desktop app and Python CLI that read DRM-free EPUBs aloud using Microsoft's online
voices through edge-tts. No paid account or API key is needed. An internet
connection is required, and the text being spoken is sent to Microsoft.
This uses an unofficial client; service availability can change.

SETUP (PowerShell, in this folder)

    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt

READ A BOOK

    .\.venv\Scripts\python.exe .\read_epub.py "C:\path\to\book.epub"

YAPBOOK / FOLLOW-ALONG WINDOW

    Double-click YapBook.exe, then choose "Open book …" and "Start reading".
    The EXE needs no Python installation. YapBook.cmd starts the Python version.
    You can also drag an EPUB file onto the EXE or YapBook.cmd.

    .\.venv\Scripts\python.exe .\read_epub.py "book.epub" --follow

The window displays all EPUB HTML sections as one continuous document.
Paragraphs, headings, bold/italic text, lists, tables, embedded raster images
and supported EPUB CSS are kept. Previous and next sections stay visible
while scrolling. Chapter selection scrolls to that section without replacing
the rest of the book. The spoken sentence is highlighted in yellow, using
the speech service's sentence timestamps and
the audio player's actual position. "Pause" and "Resume" pause/resume
both audio and highlighting. Headings, paragraphs, and explicit line breaks
keep their speech boundaries. Unpunctuated headings receive sentence-ending
punctuation only in the speech request, giving the voice a natural pause;
the displayed book stays unchanged. Automatic line wrapping adds no pauses.
"Auto-scroll while reading" controls auto-scrolling;
"Text size: Smaller / Larger" changes the font size. Choose another section using
the "Section" dropdown. The compact "Speed" slider starts at 0%, using a comfortable
-15% speech-service rate. Displayed +15% means service 0%; displayed -10% means
service -25%. The CLI uses the same scale. The default voice is en-US-BrianMultilingualNeural.
"Stop" resets playback to the beginning of the selected section.
The compact "Volume" slider beside "Speed" adjusts playback from 0% (muted) to 100%. It works while
playing or paused and stays at the chosen level when the next audio part or
section starts. It does not change the Windows system volume. Voice, speed, volume,
text size and auto-scroll are remembered after closing YapBook.
Space pauses/resumes when the reading text has keyboard focus.
The book continues into subsequent sections automatically. Voice and speed
can be changed while stopped. The EXE includes the HTML renderer. When using
the Python version, install the updated requirements.txt first.

The graphical reader saves each EPUB's last read sentence on pause, stop,
close, or switching books. Reopening the EPUB restores that sentence and its
highlight; select "Start reading" to continue. Playback does not start by itself.
Stopping before closing preserves the last read sentence. An explicit --chapter
overrides the saved position. Moving or renaming the same EPUB keeps its position.
Positions are stored in %LOCALAPPDATA%\YapBook\positions, separately from the EXE,
as book/text hashes and offsets. They contain no book text.

Disable "Auto-scroll while reading" to scroll freely while playback continues.
Clicking a sentence in any displayed section switches playback to that section.
Internal book links read their label first, then jump to their target and continue
reading. Pause defers the jump; Stop or another navigation cancels it. The full book remains visible.
The renderer supports HTML and CSS suitable for typical reflowable EPUBs;
advanced browser layout, embedded web fonts and complex SVG artwork may differ
from a full browser. EPUB resource loading stays local; book JavaScript is not run.

Click a sentence to continue reading from there. In the currently loaded
audio, this seeks directly using the service's exact sentence timestamps.
Elsewhere, it prepares new audio from the selected sentence. Before audio
is available, sentence starts are estimated from punctuation and common
German/English abbreviations. Dragging to select text does not seek.

"Refresh voice list" fetches the full list of available online voices;
it does not download offline voices. Choose the reading voice in "Reading voice".
Choose Language first. Type directly into Reading voice (for example Brian) to
filter the dropdown, then open its arrow or press Down and select a matching voice.
Escape restores the saved voice. Favorite / Unfavorite saves
preferred voices; Favorites only narrows the list to them. Preview voice plays a short
sample using the current speed and volume, without changing the book's reading position.
The section dropdown replaces the
CLI's chapter listing/selection; the visible text provides the text preview.

Toolbar actions use familiar icons with English tooltips: folder for Open book,
triangle for Start reading, pause bars, square for Stop, star for favorites, and
bookmark icons for adding/viewing bookmarks. Hover or use keyboard focus to see
the action name. Language/voice, speed/volume and section selectors retain labels.

Recent books lists the last 20 EPUBs opened. Reopen a moved EPUB using Open book to
update its path. Add bookmark saves a named sentence; Bookmarks lists and deletes
marks for the current book. Jumping while reading resumes at the bookmark; jumping
while stopped only restores the position. Multiple bookmarks are supported per book.
Previous sentence starts the preceding sentence, including in the previous section.
Next sentence starts the following sentence, including in the next section.
Section progress measures the text position, not remaining audio time.

Sleep timer offers 15 minutes, 30 minutes or End of section. Minute timers count wall
time, including pauses/loading, and pause playback when they expire. End of section
stops before the next section. Stop, manual section changes and opening another book
clear the timer. Timers are not restored after restart.

Audio loading shows elapsed time and received KB. Stop cancels a pending request;
a 90-second deadline prevents endless preparation. On failure the current sentence
is retained for Start reading to retry. A listed voice may still respond slowly or fail.

Preferences, favorites, recent paths/titles and named bookmark offsets are stored in
%LOCALAPPDATA%\YapBook\library.json, independently of the EXE. EPUB content and audio
are not saved there. An explicit --voice or --rate overrides the saved GUI setting;
the plain CLI uses its defaults if those options are omitted.

REBUILD THE EXE (optional)

    powershell -ExecutionPolicy Bypass -File .\build_exe.ps1

The build script installs PyInstaller into this folder's .venv and writes
dist\YapBook.exe. The artwork in assets is embedded in the EXE for the Windows
icons and the small logo in the reader. Keep assets beside the Python files
when running from source. Test the source with:

    .\.venv\Scripts\python.exe -m unittest test_follow_reader test_html_reader test_reading_positions test_app_state -v

In the plain CLI, press Ctrl+C to stop and use --chapter to restart a section
later; automatic reading positions apply to the graphical reader. During GUI playback, the next two sentences are
prepared in the background, including across section boundaries. This reduces
loading pauses; slow service responses and player transitions can still cause
brief gaps. Current and upcoming text is sent to Microsoft for speech generation.
Stopping or jumping outside the current audio clears the old preparation. Temporary audio is
removed on normal exit or Ctrl+C. Playback uses your default Windows output.

OPTIONS

    # Show the book's sections in reading order
    .\.venv\Scripts\python.exe .\read_epub.py "book.epub" --list-chapters

    # Start at section 3 and add 15 points to the baseline (service rate 0%)
    .\.venv\Scripts\python.exe .\read_epub.py "book.epub" --chapter 3 --rate 15

    # German voice (use a voice matching the book's language)
    .\.venv\Scripts\python.exe .\read_epub.py "book.epub" --voice de-DE-KatjaNeural

    # List English voices; replace en with de for German, or omit it for all
    .\.venv\Scripts\python.exe .\read_epub.py --list-voices en

    # Check the extracted text without sending it online
    .\.venv\Scripts\python.exe .\read_epub.py "book.epub" --chapter 3 --preview

Section numbers follow the EPUB's internal spine. They can include a preface
or cover and may differ from the printed chapter numbers. Navigation pages
and non-linear extras are skipped. Image-only books and encrypted EPUBs are
not supported. There is no OCR or DRM removal.

Dependencies and documentation:
https://github.com/rany2/edge-tts
https://docs.sourcefabric.org/projects/ebooklib/en/latest/tutorial.html
https://www.crummy.com/software/BeautifulSoup/bs4/doc/

Light / dark mode
-----------------
Use the moon/sun icon at the top of the window. The mode is remembered and applies to the controls and book page without interrupting playback.

Web version
-----------
See web/README.md for the browser reader and free Streamlit Community Cloud deployment.
