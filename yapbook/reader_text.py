"""Local book search and conservative citation recognition with source offsets."""

import re


_NAME = r"[A-ZÀ-ÖØ-Þ][\w'’\-]+"
_AUTHORS = rf"{_NAME}(?:\s+(?:et\s+al\.|(?:and|und|&)\s+{_NAME}))?"
_YEAR = r"(?:18|19|20)\d{2}[a-z]?"
_CITATIONS = [
    re.compile(r"\[\s*\d+(?:\s*[,;–—-]\s*\d+)*\s*\]"),
    re.compile(rf"\((?:{_AUTHORS}\s*,?\s*{_YEAR}(?:\s*[,;]\s*(?:{_AUTHORS}\s*,?\s*)?{_YEAR})*(?:\s*,\s*(?:p{1,2}\.|S\.)\s*\d+(?:[–-]\d+)?)?)\)"),
    re.compile(rf"\b{_AUTHORS}\s*\(\s*{_YEAR}(?:\s*[,;]\s*{_YEAR})*\s*\)"),
    re.compile(rf"\b{_NAME}\s+et\s+al\.\s*,?\s*{_YEAR}\b"),
]


def citation_spans(text, marked=()):
    ranges = list(marked)
    for pattern in _CITATIONS:
        ranges.extend(match.span() for match in pattern.finditer(text))
    merged = []
    for start, end in sorted(ranges):
        start, end = max(0, start), min(len(text), end)
        if start >= end:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def speech_projection(text, read_citations=True, marked=()):
    """Return speech text and one original character offset per speech character."""
    removed = set()
    if not read_citations:
        for start, end in citation_spans(text, marked):
            removed.update(range(start, end))
    letters, offsets = [], []
    for index, char in enumerate(text):
        if index in removed:
            continue
        if char.isspace() and (not letters or letters[-1].isspace()):
            continue
        if char in ',.;:!?' and letters and letters[-1].isspace():
            letters.pop()
            offsets.pop()
        letters.append(char)
        offsets.append(index)
    while letters and letters[-1].isspace():
        letters.pop()
        offsets.pop()
    spoken = ''.join(letters)
    if not any(char.isalnum() for char in spoken):
        return '', []
    return spoken, offsets


def search_book(chapters, query):
    words = query.strip().split()
    if not words:
        return []
    pattern = re.compile(r"\s+".join(re.escape(word) for word in words), re.I)
    return [(section, match.start(), match.end())
            for section, (_, text) in enumerate(chapters)
            for match in pattern.finditer(text)]


def mark_citations(body):
    """Only explicit references or linked superscripts, never mathematical powers."""
    for node in body.find_all(True):
        kinds = str(node.get('epub:type', '')).split() + str(node.get('role', '')).split()
        reference = any(kind in ('noteref', 'biblioref', 'doc-noteref', 'doc-biblioref') for kind in kinds)
        superscript_link = node.name == 'sup' and node.find('a', href=True) is not None
        numbered_link = (node.name == 'a' and re.fullmatch(r"[\[\]()\d⁰¹²³⁴⁵⁶⁷⁸⁹\s]+", node.get_text())
                         and re.search(r"(?:#|[/_\-])(?:fn|ftn|footnote|endnote|note|ref)[_\-]?\d", node.get('href', ''), re.I))
        if reference or superscript_link or numbered_link:
            node['data-reader-citation'] = 'true'
