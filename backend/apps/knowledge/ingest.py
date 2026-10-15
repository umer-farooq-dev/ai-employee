"""Turn knowledge sources into plain-text documents (KB-01 … KB-05). Standard library + pypdf only.

Each extractor returns [{"title", "url", "text", "metadata"}]. Chunking and embedding happen in services.process().
"""

import io
import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import zipfile
from html import unescape
from html.parser import HTMLParser

from django.conf import settings
from django.core.exceptions import ValidationError

SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "iframe", "head"}
BLOCK_TAGS = {"p", "div", "section", "article", "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul"}
MAX_PAGE_BYTES = 3 * 1024 * 1024


# ------------------------------------------------------------------ HTML → text
class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.links, self.title, self._skip, self._in_title = [], [], "", 0, False

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)

    def text(self):
        lines = (" ".join(line.split()) for line in "".join(self.parts).splitlines())
        return "\n".join(line for line in lines if line)


def html_to_text(html):
    parser = _HTMLText()
    parser.feed(html or "")
    return parser.text(), parser.title.strip(), parser.links


# ------------------------------------------------------------------ website (KB-01)
def _check_host(url):
    """Block internal addresses on production servers (SSRF); local / staging may crawl a local test site."""
    host = urllib.parse.urlparse(url).hostname
    if not host:
        raise ValidationError("Enter a full website address, e.g. https://example.com")
    if settings.ENVIRONMENT != "production":
        return
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except OSError:
        raise ValidationError(f"Could not find {host}.") from None
    for addr in addresses:
        ip = ipaddress.ip_address(addr)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValidationError("This address points to a private network and cannot be crawled.")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith(("http://", "https://")):
            return None
        _check_host(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SafeRedirect)


def fetch(url, user_agent, timeout=20):
    """→ (final url, html) or None for non-HTML pages."""
    _check_host(url)
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "text/html"})
    with _opener.open(req, timeout=timeout) as resp:  # nosec B310
        if "html" not in resp.headers.get("Content-Type", ""):
            return None
        raw = resp.read(MAX_PAGE_BYTES)
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.geturl(), raw.decode(charset, errors="replace")


def _normal(url):
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or "/", parts.query, ""))


def crawl(start, max_pages, max_depth, include=(), exclude=(), user_agent="", fetcher=None):
    """Breadth-first crawl of one site: same host, robots.txt respected, include / exclude path patterns."""
    start = _normal(start)
    host = urllib.parse.urlsplit(start).netloc
    robots = urllib.robotparser.RobotFileParser()
    robots.set_url(urllib.parse.urljoin(start, "/robots.txt"))
    try:
        robots.read()
    except (OSError, urllib.error.URLError, ValueError):
        robots = None
    fetcher = fetcher or fetch
    seen, queue, pages, errors = {start}, [(start, 0)], [], []

    def allowed(url):
        path = urllib.parse.urlsplit(url).path
        if include and not any(re.search(p, path) for p in include):
            return url == start
        return not any(re.search(p, path) for p in exclude)

    while queue and len(pages) < max_pages:
        url, depth = queue.pop(0)
        if robots and not robots.can_fetch(user_agent or "*", url):
            continue
        try:
            got = fetcher(url, user_agent)
        except (OSError, urllib.error.URLError, ValidationError, ValueError) as exc:
            errors.append(f"{url}: {getattr(exc, 'reason', exc)}")
            continue
        if not got:
            continue
        final, html = got
        text, title, links = html_to_text(html)
        if allowed(final) and text:
            pages.append({"title": title or final, "url": final, "text": text, "metadata": {"depth": depth}})
        if depth >= max_depth:
            continue
        for href in links:
            link = _normal(urllib.parse.urljoin(final, href.split("#")[0]))
            if link.startswith(("http://", "https://")) and urllib.parse.urlsplit(link).netloc == host:
                if link not in seen and not re.search(r"\.(pdf|jpe?g|png|gif|zip|docx?|xlsx?|mp4|mp3)$", link, re.I):
                    seen.add(link)
                    queue.append((link, depth + 1))
    if not pages and errors:
        raise ValidationError(f"Could not read the website: {errors[0]}")
    return pages


# ------------------------------------------------------------------ files (KB-02, KB-05)
def pdf_text(data):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValidationError("The PDF is password protected.")
        pages = [page.extract_text() or "" for page in reader.pages]
    except PdfReadError as exc:
        raise ValidationError(f"Could not read the PDF: {exc}") from None
    return [
        {"title": f"Page {i}", "text": t.strip(), "metadata": {"page": i}} for i, t in enumerate(pages, 1) if t.strip()
    ]


def docx_text(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError):
        raise ValidationError("Could not read the Word file (.docx).") from None
    paragraphs = []
    for para in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        text = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", para, re.S))
        if text.strip():
            paragraphs.append(unescape(text))
    return [{"title": "", "text": "\n".join(paragraphs), "metadata": {}}] if paragraphs else []


def sheet_rows(name, data):
    """KB-05: every row kept as an exact record ("Column: value" lines) — never summarised."""
    from apps.core.tabular import read_table

    rows = read_table(name, data)
    if len(rows) < 2:
        raise ValidationError("The sheet needs a header row and at least one data row.")
    header = [h.strip() or f"Column {i}" for i, h in enumerate(rows[0], 1)]
    docs = []
    for n, row in enumerate(rows[1:], start=2):
        pairs = [(h, str(v).strip()) for h, v in zip(header, row, strict=False) if str(v).strip()]
        if pairs:
            docs.append(
                {
                    "title": f"Row {n}",
                    "text": "\n".join(f"{h}: {v}" for h, v in pairs),
                    "metadata": {"row": n, "record": dict(pairs)},
                }
            )
    return docs


# ------------------------------------------------------------------ chunking
def chunk(text, size, overlap):
    """Split on paragraphs, then sentences, into pieces of about `size` characters with `overlap`."""
    pieces = []
    for para in re.split(r"\n\s*\n|\n", text):
        para = para.strip()
        while len(para) > size:
            cut = max(para.rfind(". ", 0, size), para.rfind("। ", 0, size), para.rfind(" ", 0, size))
            cut = cut + 1 if cut > size // 2 else size
            pieces.append(para[:cut].strip())
            para = para[cut:].strip()
        if para:
            pieces.append(para)
    chunks, current = [], ""
    for piece in pieces:
        if current and len(current) + len(piece) + 1 > size:
            chunks.append(current)
            current = current[-overlap:].lstrip() + " " + piece if overlap else piece
        else:
            current = f"{current}\n{piece}" if current else piece
    if current:
        chunks.append(current)
    return chunks
