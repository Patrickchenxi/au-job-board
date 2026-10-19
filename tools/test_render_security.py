"""Synthetic JD rendering contracts; no browser or external sources."""
from html.parser import HTMLParser
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from jobs.render import render_jd_html


class ParsedHTML(HTMLParser):
    def __init__(self, value):
        super().__init__()
        self.tags = []
        self.text = []
        self.feed(value)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, value):
        self.text.append(value)


class RenderSecurityTests(unittest.TestCase):
    def test_quoted_bare_urls_stay_plain_text(self):
        for quote in ('"', "'"):
            with self.subTest(quote=quote):
                text = f'Apply at {quote}https://example.invalid/apply{quote} today.'
                parsed = ParsedHTML(render_jd_html(text))
                self.assertEqual([attrs for tag, attrs in parsed.tags if tag == "a"], [])
                self.assertEqual("".join(parsed.text), text)

    def test_bare_url_stops_before_escaped_closing_quote(self):
        for quote in ('"', "'"):
            with self.subTest(quote=quote):
                url = "https://example.invalid/apply?a=1&b=2"
                text = f'Apply at {url}{quote} today.'
                parsed = ParsedHTML(render_jd_html(text))
                self.assertEqual([attrs["href"] for tag, attrs in parsed.tags if tag == "a"],
                                 [url])
                self.assertEqual("".join(parsed.text), text)

    def test_markdown_url_quotes_cannot_create_attributes(self):
        for event in ("onmouseover", "onpointerenter"):
            with self.subTest(event=event):
                url = f'https://example.invalid/"{event}="window.synthetic=1'
                parsed = ParsedHTML(render_jd_html(f"[Apply]({url})"))
                anchors = [attrs for tag, attrs in parsed.tags if tag == "a"]
                self.assertEqual(len(anchors), 1)
                self.assertEqual(anchors[0], {
                    "href": url, "target": "_blank", "rel": "noopener"})

    def test_normal_markdown_links_and_text_are_preserved(self):
        parsed = ParsedHTML(render_jd_html(
            '# Synthetic role\n\n**Bold** and *italic* and `code`.\n\n'
            '- [Apply](https://example.invalid/job?a=1&b=2)\n'
            '- https://example.invalid/help\n\n'
            'Say "hello" & don\'t render <script>synthetic</script>.'))
        anchors = [attrs["href"] for tag, attrs in parsed.tags if tag == "a"]
        self.assertEqual(anchors, ["https://example.invalid/job?a=1&b=2",
                                   "https://example.invalid/help"])
        tags = [tag for tag, attrs in parsed.tags]
        self.assertTrue({"h4", "strong", "em", "code", "ul", "li"}.issubset(tags))
        self.assertNotIn("script", tags)
        self.assertIn('Say "hello" & don\'t render <script>synthetic</script>.',
                      "".join(parsed.text))


if __name__ == "__main__":
    unittest.main()
