"""Continuous HTML view with exact mappings to chapter-local speech offsets."""

from bisect import bisect_left, bisect_right
import re
import tkinter as tk
from urllib.parse import unquote, urlsplit
from tkinterweb import HtmlFrame


class HtmlBookView(HtmlFrame):
    def __init__(self, master, on_navigate=None):
        self.on_navigate = on_navigate
        self.model = None
        self.chapter_ranges = []
        self.offsets = []
        self.chapters = []
        self.highlighted_text = ""
        self.dark = False
        super().__init__(master, messages_enabled=False, threading_enabled=False,
                         javascript_enabled=False, forms_enabled=False, objects_enabled=False,
                         # The legacy compatibility filter strips emoji even on Tk 9.
                         crash_prevention_enabled=tk.TkVersion < 9,
                         request_func=self._resource, on_link_click=self._link)
        self.load_html('<html><body style="background:#fffdf8;color:#667085;font:20px Georgia;padding:36px">'
                       'Open an EPUB to read along with its original formatting.</body></html>')
        self._theme_styles()

    def _theme_styles(self):
        self.add_css('''html.reader-dark, html.reader-dark body {
            background: #161e24 !important; color: #d5ded9 !important;
        }
        html.reader-dark body * {
            color: #d5ded9 !important; background-color: transparent !important;
            border-color: #36463e !important;
        }
        html.reader-dark a { color: #9fc9b1 !important; }
        ''', priority="user")
        self.set_theme(self.dark)

    def set_theme(self, dark):
        self.dark = bool(dark)
        self.document.documentElement.setAttribute("class", "reader-dark" if self.dark else "")
        self.update_idletasks()

    def _resource(self, url, *args):
        if self.model is None:
            raise OSError("No EPUB loaded")
        return self.model.request_resource(url, *args)

    def _link(self, url):
        target = urlsplit(url)
        if target.netloc and target.netloc != "epub.local":
            return
        if not target.fragment:
            return
        try:
            element = self.document.getElementById(unquote(target.fragment))
            position = self._node_position(element.node)
            if self.on_navigate is not None and position is not None:
                self.on_navigate(*position)
            element.scrollIntoView()
        except tk.TclError:
            pass

    def _node_position(self, target):
        """Find the first readable text at or after an anchor in its section."""
        ancestor = target
        while ancestor:
            identifier = self.html.get_node_attribute(ancestor, "id", "")
            if identifier.startswith("reader-chapter-"):
                section = int(identifier.removeprefix("reader-chapter-"))
                break
            ancestor = self.html.get_node_parent(ancestor)
        else:
            return None
        offsets = self.offsets[section]
        pending, reached = [ancestor], False
        while pending:
            node = pending.pop()
            reached = reached or node == target
            if reached and not self.html.get_node_tag(node):
                text = self.html.get_node_text(node)
                if text.strip():
                    start = int(self.html.text("offset", node, 0))
                    char = bisect_left(offsets, start)
                    if char < len(offsets) and offsets[char] < start + len(text):
                        return section, char
            pending.extend(reversed(self.html.get_node_children(node)))
        return None

    def clicked_link(self, event):
        try:
            node, _ = self.html.node("-index", event.x, event.y)
            while node:
                if self.html.get_node_tag(node).lower() == "a":
                    return self.html.get_node_attribute(node, "href", "") or None
                node = self.html.get_node_parent(node)
        except (tk.TclError, TypeError, ValueError):
            pass
        return None

    def set_document(self, model):
        self.model = model
        self.load_html(model.markup, base_url="https://epub.local/")
        self._theme_styles()
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
            pieces, offsets = [], []
            previous_end = 0
            for match in re.finditer(r"\S+", page[start:end]):
                if pieces:
                    gap = page[start + previous_end:start + match.start()]
                    pieces.append("\n" if "\n" in gap else " ")
                    offsets.append(start + match.start() - 1)
                pieces.append(match.group())
                offsets.extend(range(start + match.start(), start + match.end()))
                previous_end = match.end()
            self.chapter_ranges.append((start, end))
            self.offsets.append(offsets)
            self.chapters.append((self.model.sections[index].title, "".join(pieces)))

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
