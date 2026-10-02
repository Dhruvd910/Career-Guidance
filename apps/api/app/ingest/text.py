"""Text from official documents, on the Pi (docs/design/15-phase6-plan.md, P6-5).

- **HTML** → text, keeping headings, list items and table rows ("Hostel rent | 21,000"), plus
  the page's links for the crawler.
- **PDF** → text per page with `pdftotext -layout`. A PDF whose pages carry almost no text is
  scanned: its pages are rendered as images for the reading model, and read by tesseract
  (English + Hindi) so every quote can be checked against text the Pi produced itself.
"""

from __future__ import annotations

import html
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin

BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table", "ul", "ol",
         "header", "footer", "address", "dd", "dt", "blockquote", "pre", "caption", "form"}
SKIP = {"script", "style", "noscript", "svg", "template", "iframe"}
SCANNED_CHARS_PER_PAGE = 80


@dataclass
class Extracted:
    kind: str  # html | pdf
    pages: list[str]
    scanned: bool = False
    title: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)  # (absolute url, link text)

    @property
    def text(self) -> str:
        return "\n\n".join(self.pages)


class _Parser(HTMLParser):
    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base, self.out, self.links, self.title = base, [], [], ""
        self._skip, self._in_title, self._href, self._anchor, self._cells = 0, False, None, [], None

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "a":
            self._href, self._anchor = dict(attrs).get("href"), []
        elif tag == "tr":
            self._cells = []
        elif tag in ("td", "th") and self._cells is not None:
            self._cells.append("")
        if tag in BLOCK and tag not in ("td", "th"):
            self.out.append("\n")
        if tag == "li":
            self.out.append("• ")

    def handle_endtag(self, tag):
        if tag in SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag == "a" and self._href is not None:
            url = urldefrag(urljoin(self.base, self._href.strip()))[0]
            if url.startswith(("http://", "https://")):
                self.links.append((url, " ".join("".join(self._anchor).split())))
            self._href = None
        elif tag == "tr" and self._cells is not None:
            cells = [" ".join(c.split()) for c in self._cells]
            if any(cells):
                self.out.append("\n" + " | ".join(cells) + "\n")
            self._cells = None
        if tag in BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
            return
        if self._href is not None:
            self._anchor.append(data)
        if self._cells is not None and self._cells:
            self._cells[-1] += data
        elif self._cells is None:
            self.out.append(data)


def tidy(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.replace("\xa0", " ").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def from_html(body: bytes, url: str) -> Extracted:
    parser = _Parser(url)
    parser.feed(body.decode("utf-8", errors="replace"))
    return Extracted("html", [tidy("".join(parser.out))], title=" ".join(html.unescape(parser.title).split()),
                     links=parser.links)


def _run(args: list[str], timeout: int = 120) -> str:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False).stdout


def from_pdf(path: str | Path, ocr_pages: int = 12) -> Extracted:
    pages = [tidy(p) for p in _run(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"]).split("\f")]
    while pages and not pages[-1]:
        pages.pop()
    info = _run(["pdfinfo", str(path)])
    title = next((line.split(":", 1)[1].strip() for line in info.splitlines() if line.startswith("Title:")), "")
    count = len(pages) or 1
    scanned = sum(len(p) for p in pages) / count < SCANNED_CHARS_PER_PAGE
    if scanned:
        pages = ocr(path, min(count, ocr_pages))
    return Extracted("pdf", pages, scanned=scanned, title=title)


def page_images(path: str | Path, first: int = 1, last: int = 6, dpi: int = 150) -> list[bytes]:
    """PNG renderings of PDF pages, for a model that reads images."""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftoppm", "-r", str(dpi), "-png", "-f", str(first), "-l", str(last), str(path), f"{tmp}/p"],
                       capture_output=True, timeout=300, check=False)
        return [p.read_bytes() for p in sorted(Path(tmp).glob("p*.png"))]


def ocr(path: str | Path, pages: int) -> list[str]:
    """The Pi's own reading of a scanned PDF (tesseract, English + Hindi), page by page."""
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftoppm", "-r", "200", "-png", "-f", "1", "-l", str(pages), str(path), f"{tmp}/p"],
                       capture_output=True, timeout=600, check=False)
        for image in sorted(Path(tmp).glob("p*.png")):
            out.append(tidy(_run(["tesseract", str(image), "-", "-l", "eng+hin", "--psm", "6"], timeout=300)))
    return out


def extract(body: bytes, url: str, mime: str | None, storage_path: str | None = None) -> Extracted:
    kind = (mime or "").split(";")[0].strip()
    if kind == "application/pdf" or body[:5] == b"%PDF-":
        if storage_path:
            return from_pdf(storage_path)
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(body)
            f.flush()
            return from_pdf(f.name)
    return from_html(body, url)


def normalise(text: str) -> str:
    """For finding a quote in a document: case, spacing, commas in numbers and ₹/Rs. don't matter."""
    text = text.lower().replace("₹", " ").replace("rs.", " ").replace("rs ", " ")
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    return " ".join(re.sub(r"[^\wऀ-ॿ]+", " ", text).split())


def contains(document: str, quote: str) -> bool:
    return bool(quote.strip()) and normalise(quote) in normalise(document)
