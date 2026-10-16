"""A reading window synchronized to the speech service's sentence timestamps."""

import asyncio
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
import queue
import re
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import unicodedata

import edge_tts

from read_epub import speech_chunks
from epub_document import EpubDocument, read_document
from html_reader import HtmlBookView
from reading_positions import PositionStore, book_fingerprint
from windows_audio import WindowsAudio


@dataclass(frozen=True)
class SentenceCue:
    start_ms: float
    end_ms: float
    start_char: int
    end_char: int


def normalized_text(text):
    """Retain source offsets when the service normalizes spacing or typography."""
    letters, offsets = [], []
    punctuation = str.maketrans({"\u201c": '"', "\u201d": '"', "\u201e": '"',
                                 "\u2018": "'", "\u2019": "'", "\u00ad": ""})
    for index, char in enumerate(text):
        for letter in unicodedata.normalize("NFKC", char).translate(punctuation).casefold():
            if not letter.isspace() and unicodedata.category(letter) not in ("Cc", "Cf"):
                letters.append(letter)
                offsets.append(index)
    return "".join(letters), offsets


def align_sentences(text, events):
    normalized, offsets = normalized_text(text)
    cursor = 0
    cues = []
    for event in events:
        sentence, _ = normalized_text(event["text"])
        if not sentence:
            continue
        start = normalized.find(sentence, cursor)
        if start < 0:
            raise ValueError("Sentence timestamps do not match the text. Please try again.")
        end = start + len(sentence)
        cues.append(SentenceCue(event["offset"] / 10_000,
                                (event["offset"] + event["duration"]) / 10_000,
                                offsets[start], offsets[end - 1] + 1))
        cursor = end
    if not cues:
        raise ValueError("The speech service did not return sentence timestamps.")
    return cues


def cue_at(cues, position_ms):
    # Adjacent service timestamps can overlap slightly; prefer the new sentence.
    for cue in reversed(cues):
        if cue.start_ms <= position_ms < cue.end_ms:
            return cue
    return None


def sentence_spans(text):
    """Find a starting sentence before its audio timestamps have been loaded."""
    abbreviations = {"dr.", "prof.", "mr.", "mrs.", "ms.", "st.", "bzw.",
                     "z.b.", "u.a.", "d.h.", "e.g.", "i.e.", "usw.", "etc.",
                     "z.", "b.", "u.", "a.", "d.", "h.", "ca.", "vgl.", "nr."}
    start = 0
    for boundary in re.finditer(r'[.!?]+[\"\u201d\u201c\u2019\u00bb)\]]*(?=\s+|$)', text):
        preceding = text[start:boundary.end()].rstrip()
        last_word = preceding.split()[-1].casefold()
        if last_word in abbreviations or re.fullmatch(r"[A-ZÄÖÜ]\.", preceding.split()[-1]):
            continue
        if start < boundary.end():
            yield start, boundary.end()
        start = boundary.end()
        while start < len(text) and text[start].isspace():
            start += 1
    if start < len(text):
        yield start, len(text)


async def generate_audio(text, voice, rate, cancelled):
    audio = bytearray()
    events = []
    speech = edge_tts.Communicate(text, voice, rate=f"{rate:+d}%", boundary="SentenceBoundary")
    async for event in speech.stream():
        if cancelled.is_set():
            return None
        if event["type"] == "audio":
            audio.extend(event["data"])
        elif event["type"] == "SentenceBoundary":
            events.append(event)
    if cancelled.is_set():
        return None
    if not audio:
        raise ValueError("The speech service did not return any audio.")
    return bytes(audio), align_sentences(text, events)


def text_parts(text, start_char=0):
    cursor = start_char
    for chunk in speech_chunks(text[start_char:]):
        start = text.find(chunk, cursor)
        if start < 0:
            raise ValueError("The reading section could not be located in the book text.")
        yield start, chunk
        cursor = start + len(chunk)


class ReadingWindow:
    def __init__(self, root, voice="en-US-AriaNeural", rate=0, position_store=None):
        self.root = root
        self.position_store = position_store if position_store is not None else PositionStore()
        self.book_id = None
        self.reading_position = None
        self.saved_position = None
        self.position_warning_shown = False
        self.player = WindowsAudio()
        self.chapters = []
        self.section = 0
        self.parts = []
        self.part = 0
        self.cues = []
        self.highlighted = None
        self.audio_temp = None
        self.state = "idle"
        self.generation = 0
        self.cancelled = threading.Event()
        self.results = queue.Queue()
        self.audio_jobs = None
        self.audio_cache = {}
        self.audio_requested = set()
        self.waiting_for = None
        self.voice_results = queue.Queue()
        self.all_voices = ["en-US-AriaNeural", "en-US-GuyNeural", "de-DE-KatjaNeural", "de-DE-ConradNeural"]
        self.closed = False
        self.font_size = 20
        self.voice = tk.StringVar(root, voice)
        self.rate = tk.DoubleVar(root, rate)
        self.rate_label = tk.StringVar(root, f"{rate:+d}%")
        self.volume = tk.DoubleVar(root, 100)
        self.volume_label = tk.StringVar(root, "100%")
        self.follow = tk.BooleanVar(root, True)
        self.status = tk.StringVar(root, "Open a book, choose a voice, then select Start reading.")
        self.book_title = tk.StringVar(root, "YapBook")
        self._build_window()
        self.timer = root.after(50, self._poll)
        root.protocol("WM_DELETE_WINDOW", self.close)

    def _build_window(self):
        self.root.title("YapBook")
        self.root.geometry("1000x760")
        self.root.minsize(760, 520)
        self.root.configure(bg="#111827")
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background="#111827")
        style.configure("TLabel", background="#111827", foreground="#cbd5e1", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 6))
        style.configure("TCheckbutton", background="#111827", foreground="#cbd5e1", font=("Segoe UI", 10))
        style.map("TCheckbutton", background=[("active", "#1f2937")])
        layout = ttk.Frame(self.root, padding=20)
        layout.pack(fill="both", expand=True)
        title = tk.Label(layout, textvariable=self.book_title, anchor="w", bg="#111827",
                         fg="#f9fafb", font=("Segoe UI", 18, "bold"))
        title.pack(fill="x", pady=(0, 12))

        controls = ttk.Frame(layout)
        controls.pack(fill="x", pady=(0, 10))
        ttk.Button(controls, text="Open book …", command=self.choose_book).pack(side="left", padx=(0, 8))
        self.play_button = ttk.Button(controls, text="Start reading", command=self.toggle_play)
        self.play_button.pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Stop", command=self.stop).pack(side="left")
        ttk.Button(controls, text="Larger", command=lambda: self.resize_font(2)).pack(side="right")
        ttk.Button(controls, text="Smaller", command=lambda: self.resize_font(-2)).pack(side="right", padx=6)
        ttk.Label(controls, text="Text size:").pack(side="right", padx=(0, 6))

        settings = ttk.Frame(layout)
        settings.pack(fill="x", pady=(0, 4))
        ttk.Label(settings, text="Reading voice:").pack(side="left", padx=(0, 6))
        self.voice_box = ttk.Combobox(settings, textvariable=self.voice, width=26, values=self.all_voices)
        self.voice_box.pack(side="left", fill="x", expand=True)
        self.voice_box.bind("<KeyRelease>", self._filter_voices)
        self.voices_button = ttk.Button(settings, text="Refresh voice list", command=self.load_voices)
        self.voices_button.pack(side="left", padx=(8, 0))
        ttk.Label(layout, text="Choose a voice from the list. Type en- for English or de- for German to filter.",
                  wraplength=680).pack(fill="x", pady=(0, 10))

        options = ttk.Frame(layout)
        options.pack(fill="x", pady=(0, 10))
        ttk.Label(options, text="Speed:").pack(side="left", padx=(0, 6))
        self.speed_slider = ttk.Scale(options, from_=-50, to=100, length=110,
                                      variable=self.rate, command=self._rate_changed)
        self.speed_slider.pack(side="left")
        ttk.Label(options, textvariable=self.rate_label, width=5, anchor="e").pack(side="left", padx=(4, 20))
        ttk.Label(options, text="Volume:").pack(side="left", padx=(0, 6))
        self.volume_slider = ttk.Scale(options, from_=0, to=100, length=110,
                                       variable=self.volume, command=self._volume_changed)
        self.volume_slider.pack(side="left")
        ttk.Label(options, textvariable=self.volume_label, width=5, anchor="e").pack(side="left", padx=(4, 8))
        ttk.Checkbutton(options, text="Auto-scroll while reading", variable=self.follow,
                        command=self._follow_changed).pack(side="right")

        chapters = ttk.Frame(layout)
        chapters.pack(fill="x", pady=(0, 12))
        ttk.Label(chapters, text="Section:").pack(side="left", padx=(0, 6))
        self.chapter_box = ttk.Combobox(chapters, state="readonly")
        self.chapter_box.pack(side="left", fill="x", expand=True)
        self.chapter_box.bind("<<ComboboxSelected>>", self.select_chapter)

        page = ttk.Frame(layout)
        page.pack(fill="both", expand=True)
        self.reader = HtmlBookView(page)
        self.reader.pack(fill="both", expand=True)
        self.reader.html.bind("<space>", self._space, add="+")
        self.reader.html.bind("<ButtonRelease-1>", self.click_sentence, add="+")
        ttk.Label(layout, textvariable=self.status, wraplength=900).pack(fill="x", pady=(12, 4))
        ttk.Label(layout, text="Online voice: current and upcoming text is sent to Microsoft.").pack(fill="x")

    def _filter_voices(self, _event=None):
        query = self.voice.get().casefold()
        self.voice_box.configure(values=[voice for voice in self.all_voices if query in voice.casefold()])

    def load_voices(self):
        self.voices_button.configure(state="disabled", text="Loading voice list …")

        def worker():
            try:
                voices = asyncio.run(edge_tts.list_voices())
                self.voice_results.put(sorted(voice["ShortName"] for voice in voices))
            except Exception:
                self.voice_results.put(None)

        threading.Thread(target=worker, daemon=True).start()

    def click_sentence(self, event):
        if not self.chapters:
            return
        position = self.reader.clicked_position(event)
        if position is not None:
            section, char = position
            self.seek_to_character(char, section)

    def seek_to_character(self, char, section=None):
        if not self.chapters:
            return
        if section is not None and section != self.section:
            self.stop()
            self.section = section
            self._show_chapter(scroll=False)
        text = self.chapters[self.section][1]
        if not text:
            return
        char = max(0, min(char, len(text) - 1))
        # Use exact service boundaries and seek in the existing MP3 when possible.
        if self.state in ("playing", "paused"):
            base = self.parts[self.part][0]
            for cue in self.cues:
                if base + cue.start_char <= char < base + cue.end_char:
                    try:
                        self.player.seek(cue.start_ms)
                        self._set_state("playing")
                        self._highlight((base + cue.start_char, base + cue.end_char))
                        self._playing_status()
                    except Exception as exc:
                        self._error(str(exc))
                    return
        spans = list(sentence_spans(text))
        chosen = next((span for span in spans if char < span[1]), spans[-1])
        self.stop()
        self._prepare_parts(chosen[0])
        self._highlight(chosen)
        self.toggle_play()

    def resize_font(self, change):
        self.font_size = max(14, min(36, self.font_size + change))
        self.reader.set_font_scale(self.font_size / 20)
        if self.chapters:
            self.reader.highlight(self.section, self.highlighted)
        self._follow_changed()

    def _rate_changed(self, _value=None):
        self.rate_label.set(f"{round(self.rate.get()):+d}%")

    def _volume_changed(self, _value=None):
        percent = round(self.volume.get())
        self.volume_label.set(f"{percent}%")
        try:
            self.player.set_volume(percent * 10)
        except Exception as exc:
            self._error(str(exc))

    def _space(self, _event):
        self.toggle_play()
        return "break"

    def _follow_changed(self):
        if self.follow.get() and self.highlighted:
            self._scroll_to(self.highlighted[0])

    def _scroll_to(self, char):
        self.reader.scroll_to(self.section, char)

    def choose_book(self):
        path = filedialog.askopenfilename(parent=self.root, title="YapBook · Open book",
                                          filetypes=[("EPUB books", "*.epub")])
        if path:
            self.load_book(path)

    def load_book(self, path, chapter=None):
        self.stop()
        try:
            book_id = book_fingerprint(path)
            document = read_document(Path(path))
            if chapter is not None and not 1 <= chapter <= len(document.sections):
                raise ValueError("This section number does not exist in this book.")
            chapters = self.reader.set_document(document)
        except Exception:
            messagebox.showerror("Open book", "The EPUB could not be read, or the section number is invalid.", parent=self.root)
            return
        self.chapters = chapters
        self.book_id = book_id
        self.saved_position = None
        self.position_warning_shown = False
        self.book_title.set(Path(path).stem)
        self.root.title(f"{Path(path).stem} · YapBook")
        self.chapter_box.configure(values=[f"{i}. {title}" for i, (title, _) in enumerate(chapters, 1)])
        position = self.position_store.get(book_id, chapters) if chapter is None else None
        self.section = position[0] if position is not None else (chapter or 1) - 1
        self._show_chapter()
        if position is not None:
            _, start, end = position
            self._prepare_parts(start)
            if end > start:
                self._highlight((start, end))
            self.reader.scroll_to(self.section, start)
            self.saved_position = position
            self.status.set(f"Saved position restored · Section {self.section + 1}/{len(chapters)} · Select Start reading to continue.")

    def _show_chapter(self, scroll=True):
        if self.reader.model is None:
            self.chapters = self.reader.set_document(EpubDocument.from_plain(self.chapters))
        self.chapter_box.current(self.section)
        title, _ = self.chapters[self.section]
        self.reader.clear_highlight()
        if scroll:
            self.reader.scroll_to(self.section)
        self._prepare_parts()
        first = next(sentence_spans(self.chapters[self.section][1]), (0, 0))
        self.reading_position = (self.section, *first)
        self.highlighted = None
        self.status.set(f"Section {self.section + 1}/{len(self.chapters)} · {title} · Click a sentence to read from there.")

    def _prepare_parts(self, start_char=0):
        self.parts = list(text_parts(self.chapters[self.section][1], start_char))
        self.part = 0

    def select_chapter(self, _event=None):
        selected = self.chapter_box.current()
        if selected >= 0:
            self.stop()
            self.section = selected
            self._show_chapter()

    def _set_state(self, state):
        self.state = state
        self.play_button.configure(text={"idle": "Start reading", "loading": "Preparing audio …",
                                         "playing": "Pause", "paused": "Resume"}[state],
                                   state="disabled" if state == "loading" else "normal")
        for widget in (self.voice_box, self.speed_slider):
            widget.configure(state="normal" if state == "idle" else "disabled")

    def toggle_play(self):
        try:
            if self.state == "playing":
                self.player.pause()
                self._set_state("paused")
                self._save_position()
                self.status.set("Paused · Select Resume to continue from here.")
            elif self.state == "paused":
                self.player.resume()
                self._set_state("playing")
                self._playing_status()
            elif self.state == "idle":
                if not self.chapters:
                    self.choose_book()
                    return
                try:
                    rate = round(self.rate.get())
                except ValueError:
                    rate = 999
                if not -50 <= rate <= 100 or not self.voice.get().strip():
                    messagebox.showerror("Voice and speed", "Please choose a voice and a speed between -50 and 100.", parent=self.root)
                    return
                if not self.parts and not self._advance_section():
                    self.status.set("There is no readable text in this or any later section.")
                    return
                self._request_part()
        except Exception as exc:
            self._error(str(exc))

    def _request_part(self):
        start, text = self.parts[self.part]
        first = next(sentence_spans(text), (0, 0))
        self.reading_position = (self.section, start + first[0], start + first[1])
        if self.audio_jobs is None:
            self._start_audio_worker()
        self.waiting_for = (self.section, self.parts[self.part][0])
        self._set_state("loading")
        self.status.set(f"Preparing audio · Section {self.section + 1} · Part {self.part + 1}/{len(self.parts)}")
        self._queue_upcoming_audio()
        self._play_ready_audio()

    def _start_audio_worker(self):
        self.generation += 1
        token = self.generation
        self.cancelled = threading.Event()
        cancelled = self.cancelled
        self.audio_jobs = jobs = queue.Queue()
        voice, rate = self.voice.get().strip(), round(self.rate.get())

        # One worker synthesizes in reading order. A session token rejects late
        # results after Stop or a jump, including failures from prefetched chunks.
        def worker():
            while not cancelled.is_set():
                job = jobs.get()
                if job is None or cancelled.is_set():
                    return
                key, text = job
                try:
                    result = asyncio.run(generate_audio(text, voice, rate, cancelled))
                    if result is not None and not cancelled.is_set():
                        self.results.put((token, key, result, None))
                except Exception:
                    if not cancelled.is_set():
                        self.results.put((token, key, None, "Audio or sentence timestamps could not be loaded. Please check your internet connection and voice selection, then try again."))

        threading.Thread(target=worker, daemon=True).start()

    def _upcoming_parts(self):
        for start, text in self.parts[self.part:]:
            yield (self.section, start), text
        for section in range(self.section + 1, len(self.chapters)):
            for start, text in text_parts(self.chapters[section][1]):
                yield (section, start), text

    def _queue_upcoming_audio(self):
        upcoming = list(islice(self._upcoming_parts(), 3))
        wanted = {key for key, _ in upcoming}
        self.audio_requested.intersection_update(wanted)
        self.audio_cache = {key: result for key, result in self.audio_cache.items() if key in wanted}
        for key, text in upcoming:
            if key not in self.audio_requested:
                self.audio_requested.add(key)
                self.audio_jobs.put((key, text))

    def _play_ready_audio(self):
        if self.state != "loading" or self.waiting_for not in self.audio_cache:
            return
        result, error = self.audio_cache.pop(self.waiting_for)
        self.waiting_for = None
        if error:
            raise RuntimeError(error)
        audio, cues = result
        self._release_audio()
        self.cues = cues
        self.audio_temp = tempfile.TemporaryDirectory(prefix="yapbook-audio-")
        path = Path(self.audio_temp.name) / "speech.mp3"
        path.write_bytes(audio)
        self.player.play(path, volume=round(self.volume.get()) * 10)
        self._set_state("playing")
        self._playing_status()

    def _cancel_pending_audio(self):
        self.generation += 1
        self.cancelled.set()
        if self.audio_jobs is not None:
            self.audio_jobs.put(None)
        self.audio_jobs = None
        self.waiting_for = None
        self.audio_cache.clear()
        self.audio_requested.clear()

    def _playing_status(self):
        self.status.set(f"Reading · Section {self.section + 1}/{len(self.chapters)} · Part {self.part + 1}/{len(self.parts)}")

    def _advance_section(self):
        for index in range(self.section + 1, len(self.chapters)):
            if self.chapters[index][1]:
                self.section = index
                self._show_chapter(scroll=self.follow.get())
                return True
        return False

    def _poll(self):
        if self.closed:
            return
        try:
            while True:
                try:
                    voices = self.voice_results.get_nowait()
                except queue.Empty:
                    break
                self.voices_button.configure(state="normal", text="Refresh voice list")
                if voices:
                    self.all_voices = voices
                    self.voice_box.configure(values=voices)
                    if self.state == "idle":
                        self.status.set(f"{len(voices)} voices available. Choose a reading voice; type en- for English or de- for German to filter.")
                elif self.state == "idle":
                    self.status.set("Could not load the voice list. Please check your internet connection.")
            while True:
                try:
                    token, key, result, error = self.results.get_nowait()
                except queue.Empty:
                    break
                if token != self.generation or key not in self.audio_requested:
                    continue
                self.audio_cache[key] = (result, error)
            self._play_ready_audio()
            if self.state == "playing":
                cue = cue_at(self.cues, self.player.position_ms())
                base = self.parts[self.part][0]
                self._highlight((base + cue.start_char, base + cue.end_char) if cue else None)
                if self.player.mode() == "stopped":
                    self._release_audio()
                    self._highlight(None)
                    self.part += 1
                    if self.part == len(self.parts):
                        if not self._advance_section():
                            self._cancel_pending_audio()
                            self.part = 0
                            self._set_state("idle")
                            self.status.set("Finished reading the book.")
                        else:
                            self._request_part()
                    else:
                        self._request_part()
        except Exception as exc:
            self._error(str(exc))
        if not self.closed:
            self.timer = self.root.after(50, self._poll)

    def _highlight(self, span):
        if span is not None:
            self.reading_position = (self.section, *span)
        if span == self.highlighted:
            return
        self.highlighted = span
        self.reader.highlight(self.section, span, scroll=self.follow.get())

    def _release_audio(self):
        self.player.close()
        if self.audio_temp is not None:
            self.audio_temp.cleanup()
            self.audio_temp = None
        self.cues = []

    def _save_position(self):
        if self.book_id is None or self.reading_position is None:
            return
        # Read the audio clock once more before closing, even between UI ticks
        # or between sentences when the yellow highlight is temporarily hidden.
        if self.state in ("playing", "paused") and self.cues:
            try:
                position_ms = self.player.position_ms()
                cue = next((cue for cue in reversed(self.cues) if cue.start_ms <= position_ms), None)
                if cue is not None:
                    base = self.parts[self.part][0]
                    self.reading_position = (self.section, base + cue.start_char, base + cue.end_char)
            except Exception:
                pass
        if self.reading_position == self.saved_position:
            return
        try:
            self.position_store.save(self.book_id, self.reading_position, self.chapters)
            self.saved_position = self.reading_position
        except OSError:
            if not self.position_warning_shown:
                self.position_warning_shown = True
                messagebox.showwarning("YapBook · Reading position", "Could not save the reading position on this computer.", parent=self.root)

    def stop(self):
        self._save_position()
        self._cancel_pending_audio()
        self._release_audio()
        self._highlight(None)
        self.part = 0
        if self.chapters:
            self._prepare_parts()
        self._set_state("idle")
        self.status.set("Stopped · Start reading begins the selected section again.")

    def _error(self, message):
        self.stop()
        self.status.set("Playback interrupted. Try again or choose another section.")
        messagebox.showerror("YapBook · Playback", message, parent=self.root)

    def close(self):
        self.closed = True
        self.stop()
        self.root.after_cancel(self.timer)
        self.root.destroy()


def run_follow(path=None, voice="en-US-AriaNeural", rate=0, chapter=None):
    root = tk.Tk()
    window = ReadingWindow(root, voice, rate)
    if path is not None:
        window.load_book(path, chapter)
    root.mainloop()
