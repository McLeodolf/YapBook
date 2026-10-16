"""Continuous HTML view with exact mappings to chapter-local speech offsets."""

from bisect import bisect_right
import re
import tkinter as tk
from tkinterweb import HtmlFrame


class HtmlBookView(HtmlFrame):
    def __init__(self, master):
        self.model = None
        self.chapter_ranges = []
        self.offsets = []
        self.chapters = []
        self.highlighted_text = ""
        super().__init__(master, messages_enabled=False, threading_enabled=False,
                         javascript_enabled=False, forms_enabled=False, objects_enabled=False,
                         # The legacy compatibility filter strips emoji even on Tk 9.
                         crash_prevention_enabled=tk.TkVersion < 9,
                         request_func=self._resource, on_link_click=self._link)
        self.load_html('<html><body style="background:#fffdf8;color:#667085;font:20px Georgia;padding:36px">'
                       'Open an EPUB to read along with its original formatting.</body></html>')

    def _resource(self, url, *args):
        if self.model is None:
            raise OSError("No EPUB loaded")
        return self.model.request_resource(url, *args)

    def _link(self, url):
        fragment = url.split("#", 1)[1] if "#" in url else ""
        if fragment:
            try:
                self.document.getElementById(fragment).scrollIntoView()
            except tk.TclError:
                pass

    def set_document(self, model):
        self.model = model
        self.load_html(model.markup, base_url="https://epub.local/")
        self.update_idletasks()
        self._map_text()
        self.clear_highlight()
        return self.chapters

    def _map_text(self):
        page = self.get_page_text()
        markers = []
        for index in range(len(self.model.sections)):
            node = self.document.getElementById(f"reader-marker-{index}").node
            text_node = self.html.get_node_children(node)[0]
            start = int(self.html.text("offset", text_node, 0))
            markers.append((start, start + len(f"Section {index + 1}")))
        self.offsets, self.chapter_ranges, self.chapters = [], [], []
        for index, (_, start) in enumerate(markers):
            end = markers[index + 1][0] if index + 1 < len(markers) else len(page)
            words, offsets = [], []
            for match in re.finditer(r"\S+", page[start:end]):
                if words:
                    offsets.append(start + match.start() - 1)
                words.append(match.group())
                offsets.extend(range(start + match.start(), start + match.end()))
            self.chapter_ranges.append((start, end))
            self.offsets.append(offsets)
            self.chapters.append((self.model.sections[index].title, " ".join(words)))

    def clear_highlight(self):
        self.html.tag("delete", "reader-spoken")
        self.highlighted_text = ""

    def highlight(self, section, span, scroll=False):
        self.clear_highlight()
        if span is None:
            return
        start, end = span
        offsets = self.offsets[section]
        if not 0 <= start < end <= len(offsets):
            return
        first, last = offsets[start], offsets[end - 1] + 1
        self.html.tag("configure", "reader-spoken", "-background", "#fbbf24", "-foreground", "#111827")
        self.html.tag("add", "reader-spoken", *self.html.text("index", first, last))
        self.highlighted_text = self.chapters[section][1][start:end]
        if scroll:
            self.scroll_to(section, start)

    def scroll_to(self, section, char=0):
        if not self.offsets[section]:
            self.document.getElementById(f"reader-chapter-{section}").scrollIntoView()
            return
        offset = self.offsets[section][min(char, len(self.offsets[section]) - 1)]
        indices = self.html.text("index", offset, offset + 1)
        bounds = self.html.text("bbox", *indices)
        whole = self.html.bbox()
        if bounds and whole:
            self.yview_moveto(max(0, (int(bounds[1]) - 70) / max(int(whole[3]), 1)))

    def clicked_position(self, event):
        if self.get_selection():
            return None
        try:
            node, offset = self.html.node("-index", event.x, event.y)
            if not node:
                return None
            position = int(self.html.text("offset", node, offset))
        except (tk.TclError, TypeError, ValueError):
            return None
        for index, (start, end) in enumerate(self.chapter_ranges):
            if start <= position < end and self.offsets[index]:
                char = max(0, bisect_right(self.offsets[index], position) - 1)
                return index, char
        return None

    def set_font_scale(self, scale):
        self.configure(fontscale=scale)
        self.update_idletasks()
        if self.model is not None:
            self._map_text()
