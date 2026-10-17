"""YapBook: read a DRM-free EPUB aloud on Windows using Microsoft's online voices."""

import argparse
import asyncio
from pathlib import Path
import re
import sys
import tempfile
import time

import edge_tts
from bs4 import BeautifulSoup
from ebooklib import ITEM_DOCUMENT, epub
from app_state import DEFAULT_VOICE, service_rate


def read_chapters(path):
    book = epub.read_epub(str(path), options={"ignore_ncx": True})
    chapters = []
    # The spine defines reading order; the archive's file order does not.
    for item_id, linear in book.spine:
        item = book.get_item_with_id(item_id)
        if linear == "no" or item is None or item.get_type() != ITEM_DOCUMENT:
            continue
        if isinstance(item, epub.EpubNav) or "nav" in getattr(item, "properties", []):
            continue
        soup = BeautifulSoup(item.get_body_content().decode("utf-8"), "html.parser")
        for tag in soup.select("script, style, nav, [hidden], [aria-hidden='true']"):
            tag.decompose()
        heading = soup.find(["h1", "h2", "h3"])
        title = heading.get_text(" ", strip=True) if heading else item.get_name()
        # HTML source line wrapping is whitespace; block elements and br are pauses.
        for block in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "h5", "h6",
                                    "li", "blockquote", "dt", "dd", "tr", "td", "th", "br"]):
            block.insert_before("\u2029")
            block.insert_after("\u2029")
        lines = [" ".join(line.split()) for line in soup.get_text().split("\u2029")]
        text = "\n".join(line for line in lines if line)
        if text:
            chapters.append((title, text))
    if not chapters:
        raise ValueError("No readable text found. The EPUB may be protected or image-only.")
    return chapters


def speech_chunks(text, limit=3500):
    """Bound startup time without losing paragraph breaks or source offsets."""
    if limit < 1:
        raise ValueError("Chunk size must be positive.")
    start = 0
    while start < len(text):
        if text[start].isspace():
            start += 1
            continue
        end = len(text)
        if end - start > limit:
            window = text[start:start + limit + 1]
            boundaries = list(re.finditer(r"(?<=[.!?])\s+|\n+", window))
            if not boundaries:
                boundaries = list(re.finditer(r"\s+", window))
            if boundaries:
                end = start + boundaries[-1].start()
            else:
                boundary = re.search(r"\s+", text[start + limit:])
                if boundary:
                    end = start + limit + boundary.start()
        yield text[start:end].rstrip()
        start = end


def prepare_speech(text):
    """Give unpunctuated headings sentence prosody, retaining source offsets."""
    spoken, offsets = [], []
    for match in re.finditer(r"[^\n]+|\n", text):
        part = match.group()
        if part != "\n":
            spoken.append(part)
            offsets.extend(range(match.start(), match.end()))
            line = part.rstrip()
            if line and match.end() < len(text) and not re.search(r'''[.!?…:;,]["'”’»)}\]]*$''', line):
                # Only the speech request receives punctuation; the book stays intact.
                spoken.append(".")
                offsets.append(match.start() + len(line) - 1)
        else:
            spoken.append(part)
            offsets.append(match.start())
    return "".join(spoken), offsets


def play_mp3(path, volume=1000):
    """Use Windows' MP3 player, polling so Ctrl+C can stop immediately."""
    from windows_audio import WindowsAudio
    player = WindowsAudio()
    try:
        player.play(path, volume)
        while player.mode() == "playing":
            time.sleep(0.1)
    finally:
        player.close()


async def list_voices(language):
    voices = await edge_tts.list_voices()
    for voice in sorted(voices, key=lambda v: v["ShortName"]):
        if voice["Locale"].lower().startswith(language.lower()):
            print(f'{voice["ShortName"]:35} {voice["Gender"]}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("epub", nargs="?", type=Path, help="path to your EPUB")
    parser.add_argument("--voice", help=f"online voice name (default: {DEFAULT_VOICE}; saved voice with --follow)")
    parser.add_argument("--rate", type=int, help="speed adjustment from the comfortable baseline; 0 means service rate -15%%")
    parser.add_argument("--chapter", type=int, help="start at this section (1-based); overrides saved position with --follow")
    parser.add_argument("--list-chapters", action="store_true", help="show section numbers and exit")
    parser.add_argument("--list-voices", nargs="?", const="", metavar="LANGUAGE",
                        help="list online voices, optionally filtered by en, de, etc.")
    parser.add_argument("--preview", action="store_true", help="print the selected section without speaking")
    parser.add_argument("--follow", action="store_true", help="open the reading window with sentence highlighting")
    args = parser.parse_args()

    if args.list_voices is not None:
        try:
            asyncio.run(list_voices(args.list_voices))
        except Exception as exc:
            raise RuntimeError("Could not fetch voices. Check your internet connection.") from exc
        return
    if args.rate is not None and not -50 <= args.rate <= 100:
        parser.error("--rate must be between -50 and 100")
    if args.follow:
        if sys.platform != "win32":
            parser.error("the reading window uses Windows audio playback")
        from follow_reader import run_follow
        run_follow(args.epub, args.voice, args.rate, args.chapter)
        return 0
    args.voice = args.voice or DEFAULT_VOICE
    args.rate = args.rate if args.rate is not None else 0
    if args.chapter is None:
        args.chapter = 1
    if args.epub is None:
        parser.error("provide an EPUB path, or use --list-voices")
    if not args.epub.is_file():
        parser.error(f"file not found: {args.epub}")
    try:
        chapters = read_chapters(args.epub)
    except Exception as exc:
        raise RuntimeError("Cannot read this EPUB. Use an unencrypted EPUB containing text.") from exc
    if args.list_chapters:
        for number, (title, _) in enumerate(chapters, 1):
            print(f"{number:3}. {title}")
        return
    if not 1 <= args.chapter <= len(chapters):
        parser.error(f"--chapter must be between 1 and {len(chapters)}")
    if args.preview:
        print(chapters[args.chapter - 1][1])
        return
    if sys.platform != "win32":
        parser.error("this script uses Windows audio playback")

    print(f"Voice: {args.voice} | Speed: {args.rate:+d}% | Ctrl+C to stop", flush=True)
    print("Book text is sent to Microsoft's online speech service.", flush=True)
    current_chapter = args.chapter
    try:
        with tempfile.TemporaryDirectory(prefix="epub-reader-audio-") as folder:
            audio = Path(folder) / "speech.mp3"
            for number in range(args.chapter, len(chapters) + 1):
                current_chapter = number
                title, text = chapters[number - 1]
                chunks = list(speech_chunks(text))
                print(f"\n[{number}/{len(chapters)}] {title}", flush=True)
                for part, chunk in enumerate(chunks, 1):
                    print(f"  Preparing audio {part}/{len(chunks)}...", flush=True)
                    try:
                        spoken, _ = prepare_speech(chunk)
                        speech = edge_tts.Communicate(spoken, args.voice, rate=f"{service_rate(args.rate):+d}%")
                        async def save_audio():
                            await asyncio.wait_for(speech.save(str(audio)), timeout=90)
                        asyncio.run(save_audio())
                    except Exception as exc:
                        raise RuntimeError(
                            "Speech generation failed. Check your connection and voice name; "
                            f"retry with --chapter {number}."
                        ) from exc
                    play_mp3(audio)
        print("Finished.")
    except KeyboardInterrupt:
        print(f"\nStopped. Restart this section with --chapter {current_chapter}.")
        return 130
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
        raise SystemExit(130)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
