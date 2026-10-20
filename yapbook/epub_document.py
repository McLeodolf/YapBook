"""Render EPUB spine documents together, keeping their local CSS and resources."""

from dataclasses import dataclass, field
import hashlib
import html
import json
from pathlib import Path
import re
from urllib.parse import quote, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup
from ebooklib import ITEM_DOCUMENT, epub
import tinycss2


BOOK_ORIGIN = "https://epub.local/"


def fragment_id(section, original):
    # Stable DOM identifiers, not authentication or integrity checks.
    digest = hashlib.sha1(original.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    return f"reader-s{section}-{digest}"


def resource_url(name):
    return BOOK_ORIGIN + quote(name.lstrip("/"))


def rewrite_urls(tokens, base):
    for token in tokens:
        if token.type == "url":
            token.value = urljoin(base, token.value)
            token.representation = f"url({json.dumps(token.value)})"
        elif token.type == "function" and token.lower_name == "url":
            value = tinycss2.serialize(token.arguments).strip().strip("\"'")
            token.arguments = tinycss2.parse_component_value_list(json.dumps(urljoin(base, value)))
        elif hasattr(token, "arguments"):
            rewrite_urls(token.arguments, base)
        elif hasattr(token, "content") and token.content is not None:
            rewrite_urls(token.content, base)
    return tokens


def selector_text(tokens):
    # Duplicate IDs in separate XHTML files must not collide in the combined page.
    result = []
    for token in tokens:
        if token.type == "hash" and token.is_identifier:
            result.append(f"[data-epub-id={json.dumps(token.value)}]")
        elif token.type == "function":
            result.append(f"{token.name}({selector_text(token.arguments)})")
        else:
            result.append(tinycss2.serialize([token]))
    return "".join(result)


def scope_selectors(tokens, scope):
    groups, current = [], []
    for token in tokens:
        if token.type == "literal" and token.value == ",":
            groups.append(current)
            current = []
        else:
            current.append(token)
    groups.append(current)
    selectors = []
    for group in groups:
        selector = selector_text(group).strip()
        if not selector:
            continue
        # Each old html/body root is now one div carrying the original classes.
        selector = re.sub(r"^html\s+(?=body\b)", "", selector, flags=re.I)
        if re.match(r"^(html|body)\b|^:root\b", selector, flags=re.I):
            selectors.append(re.sub(r"^(html|body)\b|^:root\b", scope, selector, count=1, flags=re.I))
        else:
            selectors.append(f"{scope} {selector}")
            if selector.startswith((".", "[", ":")):
                selectors.append(scope + selector)
    return ", ".join(selectors)


@dataclass
class BookSection:
    title: str
    name: str
    markup: str


@dataclass
class EpubDocument:
    sections: list[BookSection]
    assets: dict = field(default_factory=dict)
    markup: str = ""

    def request_resource(self, url, *_args):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "epub.local":
            raise OSError("Only resources contained in this EPUB are loaded.")
        name = unquote(parsed.path).lstrip("/")
        data, mime = self.assets[name]
        if mime == "text/css":
            data = data.decode("utf-8-sig", errors="replace")
        return url, data, mime, 200

    def _css(self, source, scope, base, seen=None):
        seen = set() if seen is None else seen
        output = []
        for rule in tinycss2.parse_stylesheet(source, skip_comments=True, skip_whitespace=True):
            if rule.type == "qualified-rule":
                selector = scope_selectors(rule.prelude, scope)
                if selector:
                    output.append(selector + "{" + tinycss2.serialize(rewrite_urls(rule.content, base)) + "}")
            elif rule.type == "at-rule":
                if rule.lower_at_keyword == "import":
                    values = [t for t in rule.prelude if t.type not in ("whitespace", "comment")]
                    if not values:
                        continue
                    first = values[0]
                    if first.type in ("string", "url"):
                        target = first.value
                    elif first.type == "function" and first.lower_name == "url":
                        target = tinycss2.serialize(first.arguments).strip().strip("\"'")
                    else:
                        continue
                    target = urljoin(base, target)
                    if target not in seen:
                        seen.add(target)
                        try:
                            imported = self.request_resource(target)[1]
                            scoped = self._css(imported, scope, target, seen)
                            media = tinycss2.serialize(values[1:]).strip()
                            output.append(f"@media {media}{{{scoped}}}" if media else scoped)
                        except (KeyError, OSError):
                            pass
                elif rule.content is not None and rule.lower_at_keyword in ("media", "supports", "layer"):
                    nested = self._css(tinycss2.serialize(rule.content), scope, base, seen)
                    output.append(f"@{rule.at_keyword} {tinycss2.serialize(rule.prelude)}{{{nested}}}")
                elif rule.lower_at_keyword == "font-face":
                    output.append("@font-face{" + tinycss2.serialize(rewrite_urls(rule.content, base)) + "}")
        return "\n".join(output)

    def build_page(self):
        from .reader_text import mark_citations
        styles, pages = {}, []
        lookup = {section.name: i for i, section in enumerate(self.sections)}
        for index, section in enumerate(self.sections):
            soup = BeautifulSoup(section.markup, "html.parser")
            body = soup.body
            if body is None:
                body = soup.new_tag("div")
                for child in list(soup.contents):
                    body.append(child.extract())
                soup.append(body)
            base = resource_url(section.name)
            mark_citations(body)
            css_classes = []
            for style in soup.find_all(["style", "link"]):
                if style.name == "link":
                    if "stylesheet" not in style.get("rel", []):
                        continue
                    css_base = urljoin(base, style.get("href", ""))
                    try:
                        source = self.request_resource(css_base)[1]
                    except (KeyError, OSError):
                        continue
                else:
                    css_base, source = base, style.get_text()
                key = "reader-css-" + hashlib.sha1((css_base + str(source)).encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
                if key not in styles:
                    styles[key] = self._css(source, "." + key, css_base)
                css_classes.append(key)
            for tag in soup.select("script, style, link, nav, base, iframe, object, [hidden], [aria-hidden='true']"):
                tag.decompose()
            for tag in [body, *body.find_all(True)]:
                if tag.name is None:
                    continue
                for attribute in list(tag.attrs):
                    if attribute.lower().startswith("on"):
                        del tag.attrs[attribute]
                if tag.get("id"):
                    original = tag["id"]
                    tag["data-epub-id"] = original
                    tag["id"] = fragment_id(index, original)
                elif tag.name == "a" and tag.get("name"):
                    tag["id"] = fragment_id(index, tag["name"])
                if tag.get("style"):
                    values = tinycss2.parse_component_value_list(tag["style"])
                    tag["style"] = tinycss2.serialize(rewrite_urls(values, base))
                for attribute in ("src", "poster", "xlink:href"):
                    if tag.get(attribute):
                        tag[attribute] = urljoin(base, tag[attribute])
                if tag.get("href"):
                    target = urlsplit(urljoin(base, tag["href"]))
                    target_name = unquote(target.path).lstrip("/")
                    if target.netloc == "epub.local" and target_name in lookup:
                        target_index = lookup[target_name]
                        target_id = fragment_id(target_index, unquote(target.fragment)) if target.fragment else f"reader-chapter-{target_index}"
                        tag["href"] = "#" + target_id
                    else:
                        tag["href"] = urljoin(base, tag["href"])
            # EPUB covers often use SVG only as a wrapper around a raster image.
            for svg in list(body.find_all("svg")):
                image = svg.find("image")
                if image and len(svg.find_all(["image", "path", "text", "rect", "circle"])) == 1:
                    replacement = soup.new_tag("img", src=image.get("xlink:href", image.get("href", "")))
                    replacement["alt"] = svg.get_text(" ", strip=True)
                    svg.replace_with(replacement)
            body.name = "div"
            if body.get("id"):
                anchor = soup.new_tag("a", id=body["id"])
                body.insert(0, anchor)
            body["id"] = f"reader-chapter-{index}"
            body["class"] = [*body.get("class", []), "reader-body", *css_classes]
            pages.append(f'<div class="reader-divider" id="reader-marker-{index}">Section {index + 1}</div>{body}')
        defaults = """
            body { margin: 0; padding: 24px 36px 64px; background: #fffdf8; color: #20242b;
                   font-family: Georgia, serif; font-size: 20px; line-height: 1.5; }
            .reader-divider { margin-top: 36px; margin-bottom: 24px; padding-top: 16px;
                border-top: 1px solid #b8bdc7; color: #667085; font: 13px Arial, sans-serif; }
            .reader-body img { max-width: 100%; height: auto; }
        """
        self.markup = '<!DOCTYPE html><html><head><meta charset="utf-8"><style>' + defaults + "\n" + "\n".join(styles.values()) + '</style></head><body>' + "\n".join(pages) + '</body></html>'
        return self.markup

    @classmethod
    def from_plain(cls, chapters):
        sections = [BookSection(title, f"section-{index}.html", '<html><body><p>' + html.escape(text) + '</p></body></html>')
                    for index, (title, text) in enumerate(chapters)]
        document = cls(sections)
        document.build_page()
        return document


def read_document(path):
    book = epub.read_epub(str(Path(path)), options={"ignore_ncx": True})
    # get_content() rebuilds XHTML and drops original body IDs, styles and classes.
    assets = {item.get_name(): (item.content, item.media_type) for item in book.get_items()}
    sections = []
    for item_id, linear in book.spine:
        item = book.get_item_with_id(item_id)
        if linear == "no" or item is None or item.get_type() != ITEM_DOCUMENT:
            continue
        if isinstance(item, epub.EpubNav) or "nav" in getattr(item, "properties", []):
            continue
        markup = item.content.decode("utf-8-sig")
        soup = BeautifulSoup(markup, "html.parser")
        heading = soup.find(["h1", "h2", "h3"])
        title = heading.get_text(" ", strip=True) if heading else item.get_name()
        sections.append(BookSection(title, item.get_name(), markup))
    if not sections:
        raise ValueError("No HTML sections were found in this EPUB.")
    document = EpubDocument(sections, assets)
    document.build_page()
    return document
