import io
import tkinter as tk
import unittest
import tempfile
from pathlib import Path
from zipfile import ZipFile
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image
from bs4 import BeautifulSoup

from epub_document import BookSection, EpubDocument, fragment_id, read_document
from html_reader import HtmlBookView


def sample_book():
    buffer = io.BytesIO()
    Image.new('RGB', (30, 20), '#4477aa').save(buffer, format='PNG')
    sections = [
        BookSection('Eins', 'Text/one.xhtml', '''<html><head><link rel="stylesheet" href="../Styles/main.css"/></head>
          <body class="book"><h1>Erster Abschnitt</h1><p id="same" class="lead">Ein <em>kursiver</em> Satz. Noch ein Satz.</p>
          <p>Zweiter Absatz mit <strong>fettem Text</strong>.</p><ul><li>Listenpunkt</li></ul>
          <img src="../Images/picture.png"/><p style="display:none">VERSTECKT</p></body></html>'''),
        BookSection('Zwei', 'Text/two.xhtml', '''<html><head><style>body {color: blue} .lead {text-align:right}</style></head>
          <body><h2>Zweiter Abschnitt</h2><p id="same" class="lead">Hallo Grüße 👋. Ein weiterer Satz.</p>
          <a href="one.xhtml#same">Zurück</a></body></html>'''),
        BookSection('Drei', 'Text/three.xhtml', '<html><body><h2>Dritter Abschnitt</h2><p>Der nächste Text.</p></body></html>')]
    assets = {'Styles/main.css': (b'@import "extra.css"; body {color: #202020} .lead {text-align:center} em {font-style:italic}', 'text/css'),
              'Styles/extra.css': (b'strong {font-weight:bold}', 'text/css'),
              'Images/picture.png': (buffer.getvalue(), 'image/png')}
    document = EpubDocument(sections, assets)
    document.build_page()
    return document


class HtmlReaderTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.view = HtmlBookView(self.root)
        self.view.pack()
        self.book = sample_book()
        self.chapters = self.view.set_document(self.book)

    def tearDown(self):
        self.root.destroy()

    def test_all_sections_and_original_structure_are_present(self):
        page = self.view.get_page_text()
        self.assertIn('Erster Abschnitt', page)
        self.assertIn('Zweiter Abschnitt', page)
        self.assertIn('Dritter Abschnitt', page)
        self.assertNotIn('VERSTECKT', page)
        self.assertIn('Grüße 👋.', page)
        dom = BeautifulSoup(self.book.markup, 'html.parser')
        self.assertEqual(len(dom.select('.reader-body')), 3)
        for tag in ('h1', 'h2', 'em', 'strong', 'ul', 'li', 'img'):
            self.assertIsNotNone(dom.find(tag))

    def test_speech_preserves_structural_breaks_but_not_source_or_visual_wrapping(self):
        document = EpubDocument([BookSection('One', 'one.xhtml',
            '<h1>Chapter 2</h1><h2>Exploring the Quiet Garden</h2>'
            '<p>A small\n bird <em>landed</em> on the wall.</p>'
            '<p>Next paragraph.<br>Another line.</p>')], {})
        document.build_page()
        chapters = self.view.set_document(document)
        expected = 'Chapter 2\nExploring the Quiet Garden\nA small bird landed on the wall.\nNext paragraph.\nAnother line.'
        self.assertEqual(chapters[0][1], expected)
        start = expected.index('A small')
        end = expected.index('\nNext')
        self.view.highlight(0, (start, end))
        self.assertEqual(self.view.highlighted_text, 'A small bird landed on the wall.')
        self.root.geometry('320x300')
        self.view.set_font_scale(1.8)
        self.assertEqual(self.view.chapters, chapters)

    def test_css_is_applied_without_leaking_between_sections(self):
        first = self.view.document.getElementById(fragment_id(0, 'same')).node
        second = self.view.document.getElementById(fragment_id(1, 'same')).node
        self.assertEqual(self.view.html.get_node_property(first, 'text-align'), 'center')
        self.assertEqual(self.view.html.get_node_property(second, 'text-align'), 'right')
        emph = self.view.html.search('#reader-chapter-0 em')[0]
        self.assertEqual(self.view.html.get_node_property(emph, 'font-style'), 'italic')
        strong = self.view.html.search('#reader-chapter-0 strong')[0]
        self.assertIn(self.view.html.get_node_property(strong, 'font-weight'), ('bold', '700'))

    def test_local_images_and_internal_links_are_rebased(self):
        dom = BeautifulSoup(self.book.markup, 'html.parser')
        url = dom.img['src']
        result = self.book.request_resource(url)
        self.assertEqual(result[2], 'image/png')
        self.assertTrue(result[1].startswith(b'\x89PNG'))
        self.assertEqual(dom.a['href'], '#' + fragment_id(0, 'same'))
        with self.assertRaises(OSError):
            self.book.request_resource('https://example.org/picture.png')

    def test_sentence_highlight_crosses_inline_formatting_and_survives_zoom(self):
        text = self.chapters[0][1]
        start = text.index('Ein kursiver Satz.')
        end = start + len('Ein kursiver Satz.')
        self.view.highlight(0, (start, end), scroll=True)
        self.assertEqual(self.view.highlighted_text, 'Ein kursiver Satz.')
        offsets = self.view.offsets[0]
        raw = self.view.get_page_text()[offsets[start]:offsets[end - 1] + 1]
        self.assertEqual(' '.join(raw.split()), 'Ein kursiver Satz.')
        self.view.set_font_scale(1.4)
        self.assertEqual(self.view.chapters, self.chapters)
        self.view.highlight(0, (start, end), scroll=True)
        self.assertEqual(self.view.highlighted_text, 'Ein kursiver Satz.')

    def test_links_resolve_sections_body_ids_and_empty_named_anchors(self):
        document = EpubDocument([
            BookSection('One', 'one.xhtml', '<html><body id="opening"><h1>First heading</h1>'
                '<p id="same">First target.</p></body></html>'),
            BookSection('Two', 'two.xhtml', '<html><body><h1>Second heading</h1>'
                '<p id="same">Second target.</p><a name="old note"></a>'
                '<p>Legacy target.</p><a id="end"></a></body></html>'),
        ])
        document.build_page()
        chapters = self.view.set_document(document)
        self.view.on_navigate = Mock()
        cases = [
            ('reader-chapter-1', 1, 'Second heading'),
            (fragment_id(0, 'opening'), 0, 'First heading'),
            (fragment_id(0, 'same'), 0, 'First target.'),
            (fragment_id(1, 'same'), 1, 'Second target.'),
            (fragment_id(1, 'old note'), 1, 'Legacy target.'),
        ]
        for target, section, text in cases:
            with self.subTest(target=target):
                self.view.on_navigate.reset_mock()
                self.view._link('https://epub.local/#' + target)
                self.view.on_navigate.assert_called_once_with(section, chapters[section][1].index(text), None)
        for url in ('https://example.org/#reader-chapter-0', '#missing', '#' + fragment_id(1, 'end')):
            with self.subTest(url=url):
                self.view.on_navigate.reset_mock()
                self.view._link(url)
                self.view.on_navigate.assert_not_called()
                self.assertEqual(self.view.chapters, chapters)

    def test_epub_import_keeps_body_anchors_and_original_styles(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'body-anchor.epub'
            with ZipFile(path, 'w') as archive:
                archive.writestr('mimetype', 'application/epub+zip')
                archive.writestr('META-INF/container.xml', '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
                archive.writestr('book.opf', '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">test</dc:identifier><dc:title>Sample</dc:title><dc:language>en</dc:language></metadata><manifest><item id="one" href="one.xhtml" media-type="application/xhtml+xml"/><item id="two" href="two.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="one"/><itemref idref="two"/></spine></package>')
                archive.writestr('one.xhtml', '<html><body><p><a href="two.xhtml#original-body">Open the chapter</a></p></body></html>')
                archive.writestr('two.xhtml', '<html><head><style>body.special p {color:#246824}</style></head><body id="original-body" class="special"><p>Destination sentence.</p></body></html>')
            document = read_document(path)
        chapters = self.view.set_document(document)
        self.view.on_navigate = Mock()
        self.view._link('#' + fragment_id(1, 'original-body'))
        self.view.on_navigate.assert_called_once_with(1, 0, None)
        self.assertEqual(chapters[1][1], 'Destination sentence.')
        paragraph = self.view.html.search('#reader-chapter-1 p')[0]
        self.assertEqual(self.view.html.get_node_property(paragraph, 'color'), '#246824')

    def test_theme_changes_colors_without_changing_offsets_or_highlight(self):
        text = self.chapters[0][1]
        start = text.index('Ein kursiver Satz.')
        self.view.highlight(0, (start, start + len('Ein kursiver Satz.')))
        offsets = [list(values) for values in self.view.offsets]
        node = self.view.document.getElementById(fragment_id(0, 'same')).node
        original = self.view.html.get_node_property(node, 'color')
        for _ in range(2):
            self.view.set_theme(True)
            self.assertEqual(self.view.html.get_node_property(node, 'color'), '#d5ded9')
            self.assertEqual(self.view.highlighted_text, 'Ein kursiver Satz.')
            self.assertEqual(self.view.offsets, offsets)
            self.view.set_theme(False)
            self.assertEqual(self.view.html.get_node_property(node, 'color'), original)
        self.view.set_theme(True)
        self.view.set_document(self.book)
        self.assertEqual(self.view.html.get_node_property(self.view.document.getElementById(fragment_id(0, 'same')).node, 'color'), '#d5ded9')

    def test_actual_click_coordinates_resolve_to_the_next_section(self):
        self.root.geometry('900x600+10000+10000')
        self.root.deiconify()
        self.view.pack(fill='both', expand=True)
        self.root.update()
        char = self.chapters[1][1].index('Hallo') + 2
        self.view.scroll_to(1, char)
        self.root.update()
        offset = self.view.offsets[1][char]
        bounds = self.view.html.text('bbox', *self.view.html.text('index', offset, offset + 1))
        page = self.view.html.bbox()
        top = self.view.html.yview()[0] * page[3]
        event = SimpleNamespace(x=int((bounds[0] + bounds[2]) / 2), y=int((bounds[1] + bounds[3]) / 2 - top))
        section, selected = self.view.clicked_position(event)
        self.assertEqual(section, 1)
        self.assertLessEqual(abs(selected - char), 1)


if __name__ == '__main__':
    unittest.main()
