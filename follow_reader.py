"""A reading window synchronized to the speech service's sentence timestamps."""

import asyncio
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
import queue
import re
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import unicodedata

import edge_tts

from app_branding import apply_app_icon, load_app_logo
from app_state import AppState, DEFAULT_VOICE, service_rate, valid_voice
from read_epub import prepare_speech, speech_chunks
from epub_document import EpubDocument, read_document
from html_reader import HtmlBookView
from reading_positions import PositionStore, book_fingerprint
from windows_audio import WindowsAudio
from ui_icons import IconButton
from ui_theme import apply_theme


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
    for boundary in re.finditer(r'[.!?]+[\"\u201d\u201c\u2019\u00bb)\]]*(?=\s+|$)|\n+', text):
        preceding = text[start:boundary.end()].rstrip()
        if not preceding:
            start = boundary.end()
            continue
        last_word = preceding.split()[-1].casefold()
        if not boundary.group().startswith("\n") and (last_word in abbreviations or re.fullmatch(r"[A-ZÄÖÜ]\.", preceding.split()[-1])):
            continue
        end = start + len(text[start:boundary.end()].rstrip())
        if start < end:
            yield start, end
        start = boundary.end()
        while start < len(text) and text[start].isspace():
            start += 1
    if start < len(text):
        yield start, len(text)


async def generate_audio(text, voice, rate, cancelled, progress=None):
    audio = bytearray()
    events = []
    spoken, source_offsets = prepare_speech(text)
    speech = edge_tts.Communicate(spoken, voice, rate=f"{rate:+d}%", boundary="SentenceBoundary")
    async for event in speech.stream():
        if cancelled.is_set():
            return None
        if event["type"] == "audio":
            audio.extend(event["data"])
            if progress is not None:
                progress(len(audio))
        elif event["type"] == "SentenceBoundary":
            events.append(event)
    if cancelled.is_set():
        return None
    if not audio:
        raise ValueError("The speech service did not return any audio.")
    cues = [SentenceCue(cue.start_ms, cue.end_ms,
                        source_offsets[cue.start_char], source_offsets[cue.end_char - 1] + 1)
            for cue in align_sentences(spoken, events)]
    return bytes(audio), cues


async def request_audio(text, voice, rate, cancelled, progress=None, timeout=90):
    """Bound the whole request and cancel even when the network stops responding."""
    received = 0
    def report(count):
        nonlocal received
        received = count
        if progress is not None:
            progress(count)
    task = asyncio.create_task(generate_audio(text, voice, rate, cancelled, report))
    deadline = time.monotonic() + timeout
    try:
        while not cancelled.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"The voice service took longer than {timeout:g} seconds ({len(text)} characters, {received / 1024:.1f} KB received). Please retry or choose another voice.")
            done, _ = await asyncio.wait({task}, timeout=min(0.1, remaining))
            if done:
                return task.result()
        return None
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def audio_error(exc):
    if isinstance(exc, TimeoutError):
        return str(exc) or "The voice service timed out. Please retry or choose another voice."
    if isinstance(exc, edge_tts.exceptions.NoAudioReceived):
        return "This voice returned no audio. Try Preview voice, retry, or choose another voice."
    if isinstance(exc, ValueError):
        return str(exc)
    return f"Could not load audio ({type(exc).__name__}). Check your internet connection, then retry or preview another voice."


def text_parts(text, start_char=0):
    # Prepare only the current sentence and the next two. Exceptionally long
    # sentences still need bounded requests for slower multilingual voices.
    for first, last in sentence_spans(text[start_char:]):
        cursor = start_char + first
        for chunk in speech_chunks(text[cursor:start_char + last], limit=700):
            start = text.find(chunk, cursor)
            if start < 0:
                raise ValueError("The reading section could not be located in the book text.")
            yield start, chunk
            cursor = start + len(chunk)


class ReadingWindow:
    def __init__(self, root, voice=None, rate=None, position_store=None, app_state=None):
        self.root = root
        self.position_store = position_store if position_store is not None else PositionStore()
        self.app_state = app_state if app_state is not None else AppState()
        settings = self.app_state.settings
        voice = voice if voice is not None else settings["voice"]
        rate = rate if rate is not None else settings["rate"]
        self.settings_timer = None
        self.settings_warning_shown = False
        self.preview_active = False
        self.progress_events = queue.Queue()
        self.request_progress = {}
        self.loading_since = 0
        self.sleep_deadline = None
        self.sleep_section = None
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
        self.all_voices = sorted(set([DEFAULT_VOICE, voice, "en-US-AriaNeural", "en-US-GuyNeural", "de-DE-KatjaNeural", "de-DE-ConradNeural", *self.app_state.favorites]))
        self.closed = False
        self.font_size = settings["font_size"]
        self.theme = settings["theme"]
        self.voice = tk.StringVar(root, voice)
        self.rate = tk.DoubleVar(root, rate)
        self.rate_label = tk.StringVar(root, f"{rate:+d}%")
        self.volume = tk.DoubleVar(root, settings["volume"])
        self.volume_label = tk.StringVar(root, f'{settings["volume"]}%')
        self.follow = tk.BooleanVar(root, settings["follow"])
        self.language = tk.StringVar(root, "All languages")
        self.voice_query = ""
        self.favorites_only = tk.BooleanVar(root, False)
        self.sleep_choice = tk.StringVar(root, "Off")
        self.sleep_label = tk.StringVar(root, "")
        self.progress_label = tk.StringVar(root, "Section progress: 0%")
        self.status = tk.StringVar(root, "Open a book, choose a voice, then select Start reading.")
        self.book_title = tk.StringVar(root, "YapBook")
        self._build_window()
        self._apply_theme()
        self.reader.set_font_scale(self.font_size / 20)
        self._refresh_voice_choices()
        for variable in (self.voice, self.rate, self.volume, self.follow):
            variable.trace_add("write", self._schedule_settings)
        self.timer = root.after(50, self._poll)
        root.protocol("WM_DELETE_WINDOW", self.close)

    def _build_window(self):
        apply_app_icon(self.root)
        self.root.title("YapBook")
        self.root.geometry("1080x850")
        self.root.minsize(920, 680)
        self.root.configure(bg="#111827")
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background="#111827")
        style.configure("TLabel", background="#111827", foreground="#cbd5e1", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 6))
        style.configure("Icon.TButton", padding=8, background="#1f2937", borderwidth=0)
        style.map("Icon.TButton", background=[("active", "#334155"), ("disabled", "#111827")])
        style.configure("TCheckbutton", background="#111827", foreground="#cbd5e1", font=("Segoe UI", 10))
        style.map("TCheckbutton", background=[("active", "#1f2937")])
        layout = ttk.Frame(self.root, padding=20)
        layout.pack(fill="both", expand=True)
        header = ttk.Frame(layout)
        header.pack(fill="x", pady=(0, 12))
        self.app_logo = load_app_logo(self.root)
        tk.Label(header, image=self.app_logo, bg="#111827", borderwidth=0).pack(side="left", padx=(0, 12))
        title = tk.Label(header, textvariable=self.book_title, anchor="w", bg="#111827",
                         fg="#f9fafb", font=("Segoe UI", 18, "bold"))
        IconButton(header, "recent", "Recent books", self.show_recent_books).pack(side="right", padx=(8, 0))
        self.theme_button = IconButton(header, "moon", "Switch to dark mode", self.toggle_theme)
        self.theme_button.pack(side="right", padx=(8, 0))
        IconButton(header, "folder", "Open book …", self.choose_book).pack(side="right")
        title.pack(side="left", fill="x", expand=True)

        settings = ttk.Frame(layout)
        settings.pack(fill="x", pady=(0, 12))
        settings.columnconfigure(1, weight=1)
        ttk.Label(settings, text="Language").grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Label(settings, text="Reading voice · type to search").grid(row=0, column=1, sticky="w", pady=(0, 4))
        self.language_box = ttk.Combobox(settings, textvariable=self.language, state="readonly", width=16)
        self.language_box.grid(row=1, column=0, sticky="ew", padx=(0, 12))
        self.language_box.bind("<<ComboboxSelected>>", self._language_changed)
        self.voice_box = ttk.Combobox(settings, textvariable=self.voice, width=26, values=self.all_voices)
        self.voice_box.grid(row=1, column=1, sticky="ew")
        self.voice_box.bind("<<ComboboxSelected>>", self._voice_selected)
        self.voice_box.bind("<KeyRelease>", self._voice_edited)
        self.voice_box.bind("<Escape>", self._restore_voice)
        self.preview_button = IconButton(settings, "preview", "Preview voice", self.preview_voice)
        self.preview_button.grid(row=1, column=2, padx=(8, 0))
        self.favorite_button = IconButton(settings, "star", "Favorite", self.toggle_favorite)
        self.favorite_button.grid(row=1, column=3, padx=(8, 0))
        ttk.Checkbutton(settings, text="Favorites only", variable=self.favorites_only,
                        command=self._filter_voices).grid(row=2, column=1, sticky="w", pady=(6, 0))
        self.voices_button = IconButton(settings, "refresh", "Refresh voice list", self.load_voices)
        self.voices_button.grid(row=2, column=2, columnspan=2, sticky="e", pady=(6, 0))

        ttk.Separator(layout).pack(fill="x", pady=(0, 12))
        controls = ttk.Frame(layout)
        controls.pack(fill="x", pady=(0, 10))
        IconButton(controls, "previous", "Previous sentence", self.previous_sentence).pack(side="left", padx=(0, 8))
        self.play_button = IconButton(controls, "play", "Start reading", self.toggle_play)
        self.play_button.pack(side="left", padx=(0, 8))
        IconButton(controls, "stop", "Stop", self.stop).pack(side="left")
        timer_controls = ttk.Frame(controls)
        timer_controls.pack(side="right")
        ttk.Label(timer_controls, text="Sleep timer:").pack(side="left", padx=(0, 6))
        self.sleep_box = ttk.Combobox(timer_controls, textvariable=self.sleep_choice, width=16, state="readonly",
                                     values=["Off", "15 minutes", "30 minutes", "End of section"])
        self.sleep_box.pack(side="left")
        self.sleep_box.bind("<<ComboboxSelected>>", self.set_sleep_timer)
        ttk.Label(timer_controls, textvariable=self.sleep_label, width=16).pack(side="left", padx=(8, 0))

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
        chapters.pack(fill="x", pady=(0, 10))
        chapters.columnconfigure(1, weight=1)
        ttk.Label(chapters, text="Section:").grid(row=0, column=0, padx=(0, 6))
        self.chapter_box = ttk.Combobox(chapters, state="readonly", width=12)
        self.chapter_box.grid(row=0, column=1, sticky="ew")
        self.chapter_box.bind("<<ComboboxSelected>>", self.select_chapter)
        IconButton(chapters, "bookmark_add", "Add bookmark", self.add_bookmark).grid(row=0, column=2, padx=(12, 6))
        IconButton(chapters, "bookmark", "Bookmarks", self.show_bookmarks).grid(row=0, column=3)
        ttk.Label(chapters, text="Text size:").grid(row=0, column=4, padx=(16, 6))
        IconButton(chapters, "smaller", "Smaller", lambda: self.resize_font(-2)).grid(row=0, column=5, padx=(0, 6))
        IconButton(chapters, "larger", "Larger", lambda: self.resize_font(2)).grid(row=0, column=6)
        extras = ttk.Frame(layout)
        page = ttk.Frame(layout)
        page.pack(fill="both", expand=True)
        self.reader = HtmlBookView(page)
        self.reader.pack(fill="both", expand=True)
        self.reader.html.bind("<space>", self._space, add="+")
        self.reader.html.bind("<ButtonRelease-1>", self.click_sentence, add="+")
        extras.pack(fill="x", pady=(8, 0))
        self.section_progress = ttk.Progressbar(extras, length=120, maximum=100)
        self.section_progress.pack(side="left", padx=(0, 8))
        ttk.Label(extras, textvariable=self.progress_label).pack(side="left")
        ttk.Label(layout, textvariable=self.status, wraplength=900).pack(fill="x", pady=(12, 4))
        ttk.Label(layout, text="Online voice: current and upcoming text is sent to Microsoft.").pack(fill="x")

    def _apply_theme(self):
        apply_theme(self.root, self.theme == "dark")
        self.reader.set_theme(self.theme == "dark")
        self.theme_button.configure(text="Switch to light mode" if self.theme == "dark" else "Switch to dark mode")

    def toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        self._apply_theme()
        self._save_settings()

    def _filter_voices(self, _event=None):
        query = self.voice_query.casefold()
        language = self.language.get()
        self.voice_box.configure(values=[voice for voice in self.all_voices
            if query in voice.casefold() and (language == "All languages" or voice.rsplit("-", 1)[0] == language)
            and (not self.favorites_only.get() or voice in self.app_state.favorites)])

    def _voice_edited(self, event):
        if event.keysym not in ("Up", "Down", "Return", "Escape", "Tab", "Left", "Right"):
            self.voice_query = self.voice.get()
            self._filter_voices()

    def _restore_voice(self, _event=None):
        self.voice.set(self.app_state.settings["voice"])
        self._voice_selected()

    def _language_changed(self, _event=None):
        self.voice_query = ""
        self._filter_voices()
        choices = self.voice_box["values"]
        if choices and self.voice.get() not in choices:
            self.voice.set(choices[0])
        self._voice_selected()

    def _refresh_voice_choices(self):
        self.language_box.configure(values=["All languages", *sorted({voice.rsplit("-", 1)[0] for voice in self.all_voices})])
        self._filter_voices()
        self._voice_selected()

    def _voice_selected(self, _event=None):
        self.voice_query = ""
        self._filter_voices()
        self.favorite_button.configure(text="Unfavorite" if self.voice.get() in self.app_state.favorites else "Favorite")

    def toggle_favorite(self):
        voice = self.voice.get().strip()
        if not valid_voice(voice):
            self.status.set("Choose a complete voice name before adding a favorite.")
            return
        if voice in self.app_state.favorites:
            self.app_state.favorites.remove(voice)
        else:
            self.app_state.favorites.append(voice)
            self.all_voices = sorted(set([*self.all_voices, voice]))
        self._refresh_voice_choices()
        self._save_settings()

    def _schedule_settings(self, *_args):
        if not self.closed:
            if self.settings_timer is not None:
                self.root.after_cancel(self.settings_timer)
            self.settings_timer = self.root.after(400, self._save_settings)

    def _save_settings(self):
        if self.settings_timer is not None:
            self.root.after_cancel(self.settings_timer)
            self.settings_timer = None
        settings = self.app_state.settings
        if valid_voice(self.voice.get().strip()):
            settings["voice"] = self.voice.get().strip()
        settings.update(rate=round(self.rate.get()), volume=round(self.volume.get()),
                        font_size=self.font_size, follow=self.follow.get(), theme=self.theme)
        try:
            self.app_state.save()
        except OSError:
            if not self.settings_warning_shown:
                self.settings_warning_shown = True
                messagebox.showwarning("YapBook · Settings", "Could not save preferences and library on this computer.", parent=self.root)

    def preview_voice(self):
        if self.preview_active:
            self._finish_preview()
            return
        if self.state != "idle":
            return
        if not valid_voice(self.voice.get().strip()):
            self.status.set("Choose a complete voice name, then try Preview voice.")
            return
        self.preview_active = True
        self._start_audio_worker()
        self.waiting_for = (-1, 0)
        self.audio_requested.add(self.waiting_for)
        self.loading_since = time.monotonic()
        self._set_state("loading")
        sample = ("Willkommen bei YapBook. So klingt diese Stimme beim Vorlesen." if self.voice.get().startswith("de-")
                  else "Welcome to YapBook. This is how this voice sounds when reading a book.")
        self.audio_jobs.put((self.waiting_for, sample))
        self._loading_status()

    def _finish_preview(self):
        self._cancel_pending_audio()
        self._release_audio()
        self.preview_active = False
        self._set_state("idle")
        self.status.set("Voice preview finished · Select Start reading to continue your book.")

    def _library_dialog(self, title, columns):
        dialog = tk.Toplevel(self.root)
        apply_app_icon(dialog)
        dialog.title(f"YapBook · {title}")
        dialog.geometry("760x360")
        dialog.transient(self.root)
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=[key for key, _ in columns], show="headings", selectmode="browse")
        for key, label in columns:
            tree.heading(key, text=label)
            tree.column(key, width=230)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        buttons = ttk.Frame(dialog, padding=12)
        buttons.pack(fill="x")
        apply_theme(dialog, self.theme == "dark")
        return dialog, tree, buttons

    def show_recent_books(self):
        dialog, tree, buttons = self._library_dialog("Recent books", [("title", "Book"), ("path", "File location")])
        entries = list(self.app_state.recent)
        for index, item in enumerate(entries):
            tree.insert("", "end", iid=str(index), values=(item["title"], item["path"]))

        def open_selected(_event=None):
            if not tree.selection():
                return
            item = entries[int(tree.selection()[0])]
            if not Path(item["path"]).is_file():
                messagebox.showinfo("Recent books", "This file has moved or is no longer available. Use Open book to select its new location.", parent=dialog)
                return
            self.load_book(item["path"])
            dialog.destroy()

        def remove_selected():
            if tree.selection():
                key = tree.selection()[0]
                item = entries[int(key)]
                self.app_state.recent = [entry for entry in self.app_state.recent if entry["id"] != item["id"]]
                tree.delete(key)
                self._save_settings()

        tree.bind("<Double-1>", open_selected)
        ttk.Button(buttons, text="Open selected", command=open_selected).pack(side="left")
        ttk.Button(buttons, text="Remove from list", command=remove_selected).pack(side="left", padx=8)
        if not entries:
            ttk.Label(buttons, text="Books you open will appear here.").pack(side="left", padx=8)

    def add_bookmark(self):
        if not self.book_id or not self.reading_position:
            self.status.set("Open a book before adding a bookmark.")
            return
        if not self.preview_active:
            self._save_position()
        position = self.reading_position
        if position[1] == position[2]:
            return
        label = simpledialog.askstring("YapBook · Add bookmark", "Bookmark name:",
                    initialvalue=f"Section {position[0] + 1} · Bookmark {len(self.app_state.marks_for(self.book_id, self.chapters)) + 1}", parent=self.root)
        if label and label.strip():
            self.app_state.add_mark(self.book_id, position, label, self.chapters)
            self._save_settings()
            self.status.set("Bookmark saved.")

    def show_bookmarks(self):
        if not self.book_id:
            self.status.set("Open a book to view its bookmarks.")
            return
        book_id = self.book_id
        dialog, tree, buttons = self._library_dialog("Bookmarks", [("label", "Bookmark"), ("section", "Section")])
        entries = {mark["id"]: mark for mark in self.app_state.marks_for(book_id, self.chapters)}
        for key, item in entries.items():
            tree.insert("", "end", iid=key, values=(item["label"], item["section"] + 1))

        def jump(_event=None):
            if tree.selection() and self.book_id == book_id:
                self.go_to_bookmark(entries[tree.selection()[0]])
                dialog.destroy()

        def remove():
            if tree.selection() and self.book_id == book_id:
                key = tree.selection()[0]
                self.app_state.remove_mark(book_id, key, self.chapters)
                tree.delete(key)
                self._save_settings()

        tree.bind("<Double-1>", jump)
        ttk.Button(buttons, text="Go to bookmark", command=jump).pack(side="left")
        ttk.Button(buttons, text="Delete bookmark", command=remove).pack(side="left", padx=8)
        if not entries:
            ttk.Label(buttons, text="Use Add bookmark to save a sentence.").pack(side="left", padx=8)

    def go_to_bookmark(self, mark):
        resume = self.state in ("playing", "loading") and not self.preview_active
        self.stop()
        self.section = mark["section"]
        self._show_chapter()
        self._prepare_parts(mark["start"])
        self._highlight((mark["start"], mark["end"]))
        self.reader.scroll_to(self.section, mark["start"])
        self._save_position()
        if resume:
            self.toggle_play()
        else:
            self.status.set("Bookmark restored · Select Start reading to continue.")

    def previous_sentence(self):
        if not self.chapters:
            return
        if self.preview_active:
            self._finish_preview()
        self._save_position()
        current = self.reading_position[1] if self.reading_position else 0
        previous = [span for span in sentence_spans(self.chapters[self.section][1]) if span[0] < current]
        if previous:
            self.seek_to_character(previous[-1][0])
            return
        for section in range(self.section - 1, -1, -1):
            spans = list(sentence_spans(self.chapters[section][1]))
            if spans:
                self.seek_to_character(spans[-1][0], section)
                return
        self.seek_to_character(0)

    def set_sleep_timer(self, _event=None):
        choice = self.sleep_choice.get()
        self.sleep_deadline = None
        self.sleep_section = None
        if choice == "End of section":
            if not self.chapters:
                self.sleep_choice.set("Off")
                self.status.set("Open a book before choosing End of section.")
            else:
                self.sleep_section = self.section
        elif choice != "Off":
            self.sleep_deadline = time.monotonic() + int(choice.split()[0]) * 60
        self._update_sleep_label()

    def _update_sleep_label(self):
        if self.sleep_deadline is not None:
            seconds = max(0, int(self.sleep_deadline - time.monotonic()))
            self.sleep_label.set(f"{seconds // 60:02d}:{seconds % 60:02d} remaining")
        elif self.sleep_section is not None:
            self.sleep_label.set(f"After section {self.sleep_section + 1}")
        else:
            self.sleep_label.set("")

    def _clear_sleep_timer(self):
        self.sleep_deadline = self.sleep_section = None
        self.sleep_choice.set("Off")
        self._update_sleep_label()

    def _sleep_now(self):
        if self.preview_active:
            self._finish_preview()
        elif self.state == "playing":
            self.toggle_play()
        elif self.state == "loading":
            position = self.reading_position
            self.stop(reset_timer=False)
            if position:
                self._prepare_parts(position[1])
                self._highlight(position[1:])
        self._clear_sleep_timer()
        self.status.set("Sleep timer finished · Playback paused. Select Resume or Start reading to continue.")

    def _update_progress(self, complete=False):
        text = self.chapters[self.section][1] if self.chapters else ""
        char = self.reading_position[1] if self.reading_position else 0
        percent = 100 if complete else min(100, round(100 * char / max(1, len(text))))
        self.section_progress["value"] = percent
        self.progress_label.set(f"Section progress: {percent}%")

    def _loading_status(self):
        elapsed = int(time.monotonic() - self.loading_since)
        received = self.request_progress.get(self.waiting_for, 0)
        detail = f"{received / 1024:.1f} KB received" if received else "Waiting for voice service"
        target = "voice preview" if self.preview_active else f"section {self.section + 1}, part {self.part + 1}/{len(self.parts)}"
        if not self.preview_active:
            target += f" · {len(self.parts[self.part][1])} characters"
        self.status.set(f"Preparing {target} · {elapsed}s · {detail} · Stop to cancel")

    def load_voices(self):
        self.voices_button.configure(state="disabled", text="Loading voice list …")
        voice_results = self.voice_results

        def worker():
            try:
                async def fetch():
                    return await asyncio.wait_for(edge_tts.list_voices(), timeout=20)
                voices = asyncio.run(fetch())
                voice_results.put(sorted(voice["ShortName"] for voice in voices))
            except Exception:
                voice_results.put(None)

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
        if self.preview_active:
            self._finish_preview()
        if section is not None and section != self.section:
            self.stop(reset_timer=False)
            if self.sleep_section is not None:
                self.sleep_section = section
                self._update_sleep_label()
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
        self.stop(reset_timer=False)
        self._prepare_parts(chosen[0])
        self._highlight(chosen)
        self.toggle_play()

    def resize_font(self, change):
        self.font_size = max(14, min(36, self.font_size + change))
        self.reader.set_font_scale(self.font_size / 20)
        if self.chapters:
            self.reader.highlight(self.section, self.highlighted)
        self._follow_changed()
        self._schedule_settings()

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
        self.app_state.remember_book(book_id, path)
        self._save_settings()
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
        self._update_progress()
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
                                   state="disabled" if state == "loading" or self.preview_active else "normal")
        for widget in (self.voice_box, self.speed_slider):
            widget.configure(state="normal" if state == "idle" else "disabled")
        self.preview_button.configure(text="Stop preview" if self.preview_active else "Preview voice",
                                      state="normal" if self.preview_active or state == "idle" else "disabled")

    def toggle_play(self):
        if self.preview_active:
            self._finish_preview()
            return
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
                if not -50 <= rate <= 100 or not valid_voice(self.voice.get().strip()):
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
        self.loading_since = time.monotonic()
        self._set_state("loading")
        self._loading_status()
        self._queue_upcoming_audio()
        self._play_ready_audio()

    def _start_audio_worker(self):
        self.generation += 1
        token = self.generation
        self.cancelled = threading.Event()
        cancelled = self.cancelled
        self.audio_jobs = jobs = queue.Queue()
        voice, rate = self.voice.get().strip(), service_rate(self.rate.get())
        results, progress_events = self.results, self.progress_events

        # One worker synthesizes in reading order. A session token rejects late
        # results after Stop or a jump, including failures from prefetched chunks.
        def worker():
            while not cancelled.is_set():
                job = jobs.get()
                if job is None or cancelled.is_set():
                    return
                key, text = job
                try:
                    progress_events.put((token, key, 0))
                    result = asyncio.run(request_audio(text, voice, rate, cancelled,
                        progress=lambda count: progress_events.put((token, key, count))))
                    if result is not None and not cancelled.is_set():
                        results.put((token, key, result, None))
                except Exception as exc:
                    if not cancelled.is_set():
                        results.put((token, key, None, audio_error(exc)))

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
        self.request_progress = {key: count for key, count in self.request_progress.items() if key in wanted}
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
        if self.preview_active:
            self.status.set("Playing voice preview · Stop preview to finish.")
        else:
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
        self.request_progress.clear()

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
                    self._refresh_voice_choices()
                    if self.state == "idle":
                        self.status.set(f"{len(voices)} voices available. Filter by language or name, then try Preview voice.")
                elif self.state == "idle":
                    self.status.set("Could not load the voice list. Please check your internet connection.")
            while True:
                try:
                    token, key, count = self.progress_events.get_nowait()
                except queue.Empty:
                    break
                if token == self.generation and key in self.audio_requested:
                    self.request_progress[key] = count
            while True:
                try:
                    token, key, result, error = self.results.get_nowait()
                except queue.Empty:
                    break
                if token != self.generation or key not in self.audio_requested:
                    continue
                self.audio_cache[key] = (result, error)
            self._play_ready_audio()
            self._update_sleep_label()
            if self.sleep_deadline is not None and time.monotonic() >= self.sleep_deadline:
                self._sleep_now()
            if self.state == "loading":
                self._loading_status()
            if self.preview_active and self.state == "playing":
                if self.player.mode() == "stopped":
                    self._finish_preview()
            elif self.state == "playing":
                cue = cue_at(self.cues, self.player.position_ms())
                base = self.parts[self.part][0]
                self._highlight((base + cue.start_char, base + cue.end_char) if cue else None)
                if self.player.mode() == "stopped":
                    self._release_audio()
                    self._highlight(None)
                    self.part += 1
                    if self.part == len(self.parts):
                        self._update_progress(complete=True)
                        if self.sleep_section == self.section:
                            self._cancel_pending_audio()
                            if not self._advance_section():
                                self._prepare_parts()
                            self._set_state("idle")
                            self._clear_sleep_timer()
                            self._save_position()
                            self.status.set("Sleep timer finished · End of section reached. Select Start reading to continue.")
                        elif not self._advance_section():
                            self._cancel_pending_audio()
                            self.part = 0
                            self._set_state("idle")
                            self._clear_sleep_timer()
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
            self._update_progress()
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
        if self.preview_active:
            return
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

    def stop(self, reset_timer=True):
        if self.preview_active:
            self._finish_preview()
            if reset_timer:
                self._clear_sleep_timer()
            return
        self._save_position()
        self._cancel_pending_audio()
        self._release_audio()
        self._highlight(None)
        self.part = 0
        if self.chapters:
            self._prepare_parts()
        self._set_state("idle")
        if reset_timer:
            self._clear_sleep_timer()
        self.status.set("Stopped · Start reading begins the selected section again.")

    def _error(self, message):
        position = self.reading_position
        preview = self.preview_active
        self.stop()
        if position and not preview:
            self._prepare_parts(position[1])
            self._highlight(position[1:])
        self.status.set("Playback interrupted · Start reading retries from this sentence, or try another voice.")
        messagebox.showerror("YapBook · Playback", message, parent=self.root)

    def close(self):
        self.closed = True
        self.stop()
        self._save_position()
        self._save_settings()
        self.root.after_cancel(self.timer)
        self.root.destroy()


def run_follow(path=None, voice=None, rate=None, chapter=None):
    root = tk.Tk()
    window = ReadingWindow(root, voice, rate)
    if path is not None:
        window.load_book(path, chapter)
    root.mainloop()
