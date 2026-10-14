"""Shared PDF building blocks for the AI Employee project documents (reportlab)."""
import re

from reportlab.graphics.shapes import Drawing, Line, Polygon, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Flowable, Frame, KeepTogether, NextPageTemplate,
                                PageBreak, PageTemplate, Paragraph, Preformatted, Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.lib.fonts import addMapping

FONTS = "C:/Windows/Fonts/"
for name, file in [("Body", "segoeui.ttf"), ("Body-Bold", "segoeuib.ttf"), ("Body-Italic", "segoeuii.ttf"),
                   ("Body-BoldItalic", "segoeuiz.ttf"), ("Body-Light", "segoeuisl.ttf"), ("Mono", "consola.ttf")]:
    pdfmetrics.registerFont(TTFont(name, FONTS + file))
addMapping("Body", 0, 0, "Body")
addMapping("Body", 1, 0, "Body-Bold")
addMapping("Body", 0, 1, "Body-Italic")
addMapping("Body", 1, 1, "Body-BoldItalic")

# ---------- palette ----------
NAVY = colors.HexColor("#0B1F3A")
BLUE = colors.HexColor("#1D4ED8")
TEAL = colors.HexColor("#0E9384")
INK = colors.HexColor("#1F2937")
MUTED = colors.HexColor("#6B7280")
LINE = colors.HexColor("#E2E8F0")
SOFT = colors.HexColor("#F3F6FB")
BLUE_BG = colors.HexColor("#EAF1FF")
TEAL_BG = colors.HexColor("#E6F6F4")
AMBER = colors.HexColor("#B45309")
AMBER_BG = colors.HexColor("#FEF3C7")
RED = colors.HexColor("#B91C1C")
RED_BG = colors.HexColor("#FDECEC")
PURPLE = colors.HexColor("#6D28D9")
PURPLE_BG = colors.HexColor("#F1EBFF")
GREEN = colors.HexColor("#047857")
GREEN_BG = colors.HexColor("#E7F7EF")
WHITE = colors.white

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

# ---------- styles ----------
def _s(name, **kw):
    base = dict(fontName="Body", fontSize=9.4, leading=13.6, textColor=INK, spaceAfter=5)
    base.update(kw)
    return ParagraphStyle(name, **base)

ST = {
    "body": _s("body"),
    "lead": _s("lead", fontSize=10.5, leading=15.5, textColor=INK, spaceAfter=8),
    "small": _s("small", fontSize=8.2, leading=11.2, textColor=MUTED),
    "H1": _s("H1", fontName="Body-Bold", fontSize=17, leading=22, textColor=NAVY, spaceBefore=4, spaceAfter=10),
    "H2": _s("H2", fontName="Body-Bold", fontSize=12.4, leading=16, textColor=BLUE, spaceBefore=10, spaceAfter=5),
    "H3": _s("H3", fontName="Body-Bold", fontSize=10.2, leading=14, textColor=INK, spaceBefore=6, spaceAfter=3),
    "bullet": _s("bullet", leftIndent=13, bulletIndent=3, spaceAfter=2.5),
    "bullet2": _s("bullet2", leftIndent=26, bulletIndent=16, spaceAfter=2, fontSize=9),
    "cell": _s("cell", fontSize=8.2, leading=11, spaceAfter=0),
    "cellb": _s("cellb", fontName="Body-Bold", fontSize=8.2, leading=11, spaceAfter=0),
    "cellh": _s("cellh", fontName="Body-Bold", fontSize=8.2, leading=11, spaceAfter=0, textColor=WHITE),
    "cellc": _s("cellc", fontSize=8.2, leading=11, spaceAfter=0, alignment=TA_CENTER),
    "caption": _s("caption", fontSize=8, leading=11, textColor=MUTED, alignment=TA_CENTER, spaceBefore=3, spaceAfter=10),
    "code": _s("code", fontName="Mono", fontSize=7.6, leading=10.2, textColor=INK, spaceAfter=0),
    "title": _s("title", fontName="Body-Bold", fontSize=17, leading=22, textColor=NAVY, spaceAfter=10),
    "toc0": _s("toc0", fontName="Body-Bold", fontSize=10, leading=15, textColor=NAVY),
    "toc1": _s("toc1", fontSize=8.8, leading=12.5, leftIndent=16, textColor=INK),
}

_AMP = re.compile(r"&(?!(amp|lt|gt|quot|apos|#\d+);)")


def fx(text):
    """Escape stray ampersands so authors can write plain '&' in content."""
    return _AMP.sub("&amp;", text)


def P(text, style="body"):
    return Paragraph(fx(text), ST[style] if isinstance(style, str) else style)


def bullets(items, style="bullet"):
    out = []
    for it in items:
        if isinstance(it, (list, tuple)):
            out += bullets(it, "bullet2")
        else:
            out.append(Paragraph(fx(it), ST[style], bulletText="•" if style == "bullet" else "–"))
    return out


def _cell(v, style="cell"):
    if isinstance(v, str):
        return Paragraph(fx(v), ST[style])
    return v


def table(header, rows, widths, zebra=True, bold_first=False, head_bg=NAVY, extra=None, font=None):
    """Generic table. widths are fractions of CONTENT_W or absolute points."""
    w = [x * CONTENT_W if x <= 1 else x for x in widths]
    data = []
    if header:
        data.append([_cell(h, "cellh") for h in header])
    for r in rows:
        data.append([_cell(c, "cellb" if (bold_first and i == 0) else "cell") for i, c in enumerate(r)])
    t = Table(data, colWidths=w, repeatRows=1 if header else 0)
    cmds = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
    ]
    if header:
        cmds += [("BACKGROUND", (0, 0), (-1, 0), head_bg), ("LINEBELOW", (0, 0), (-1, 0), 0, head_bg)]
    if zebra:
        start = 1 if header else 0
        for i in range(start, len(data)):
            if (i - start) % 2 == 1:
                cmds.append(("BACKGROUND", (0, i), (-1, i), SOFT))
    if extra:
        cmds += extra
    t.setStyle(TableStyle(cmds))
    return t


def callout(title, body, kind="info"):
    fg, bg = {"info": (BLUE, BLUE_BG), "rule": (TEAL, TEAL_BG), "warn": (AMBER, AMBER_BG),
              "pending": (PURPLE, PURPLE_BG), "ok": (GREEN, GREEN_BG), "risk": (RED, RED_BG)}[kind]
    parts = [Paragraph(f'<font color="#{fg.hexval()[2:]}"><b>{fx(title)}</b></font>', ST["body"])]
    if isinstance(body, str):
        parts.append(P(body))
    else:
        parts += bullets(body)
    t = Table([[parts]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg), ("LINEBEFORE", (0, 0), (0, -1), 3, fg),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return KeepTogether([t, Spacer(1, 8)])


def code(text):
    pre = Preformatted(text.strip("\n"), ST["code"])
    t = Table([[pre]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SOFT), ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return KeepTogether([t, Spacer(1, 8)])


def kv(pairs, key_w=0.27):
    return table(None, pairs, [key_w, 1 - key_w], zebra=True, bold_first=True)


def sp(h=6):
    return Spacer(1, h)


# ---------- numbering ----------
class Numbering:
    def __init__(self):
        self.h1 = 0
        self.h2 = 0
        self.fig = 0

    def H1(self, text, new_page=True):
        self.h1 += 1
        self.h2 = 0
        out = [PageBreak()] if new_page else [CondPageBreak(60 * mm)]
        return out + [Paragraph(f"{self.h1}. {fx(text)}", ST["H1"])]

    def H2(self, text):
        self.h2 += 1
        return [CondPageBreak(30 * mm), Paragraph(f"{self.h1}.{self.h2} {fx(text)}", ST["H2"])]

    def figure(self, drawing, caption):
        self.fig += 1
        return [KeepTogether([drawing, Paragraph(f"Figure {self.fig}: {fx(caption)}", ST["caption"])])]


def H3(text):
    return Paragraph(fx(text), ST["H3"])


def toc():
    t = TableOfContents()
    t.levelStyles = [ST["toc0"], ST["toc1"]]
    t.dotsMinLevel = 0
    return t


# ---------- diagrams ----------
class Dia:
    """Tiny helper over reportlab Drawing for boxes-and-arrows diagrams."""

    def __init__(self, w, h):
        self.d = Drawing(w, h)
        self.w, self.h = w, h

    def box(self, x, y, w, h, text, fill=BLUE_BG, stroke=BLUE, color=INK, fs=7.6, r=4, sub_fs=None, bold=True):
        self.d.add(Rect(x, y, w, h, rx=r, ry=r, fillColor=fill, strokeColor=stroke, strokeWidth=0.8))
        lines = text.split("\n")
        sub_fs = sub_fs or fs - 0.8
        sizes = [fs] + [sub_fs] * (len(lines) - 1)
        lh = [s * 1.28 for s in sizes]
        total = sum(lh)
        yy = y + h / 2 + total / 2
        for i, ln in enumerate(lines):
            yy -= lh[i]
            font = "Body-Bold" if (i == 0 and bold) else "Body"
            size = sizes[i]
            width = pdfmetrics.stringWidth(ln, font, size)
            if width > w - 6:  # shrink a line that would overflow its box
                size *= (w - 6) / width
            self.d.add(String(x + w / 2, yy + lh[i] * 0.25, ln, fontName=font, fontSize=size,
                              fillColor=color, textAnchor="middle"))

    def group(self, x, y, w, h, title, stroke=MUTED, fill=None, color=MUTED):
        self.d.add(Rect(x, y, w, h, rx=6, ry=6, fillColor=fill, strokeColor=stroke, strokeWidth=0.7,
                        strokeDashArray=[3, 2]))
        self.d.add(String(x + 6, y + h - 10, title, fontName="Body-Bold", fontSize=7.2, fillColor=color))

    def text(self, x, y, s, fs=7, color=MUTED, anchor="middle", bold=False):
        self.d.add(String(x, y, s, fontName="Body-Bold" if bold else "Body", fontSize=fs, fillColor=color,
                          textAnchor=anchor))

    def tag(self, x, y, s, fs=6.4, color=INK, anchor="middle"):
        """Text on a white background so lines behind it stay readable."""
        w = pdfmetrics.stringWidth(s, "Body", fs)
        x0 = {"middle": x - w / 2, "start": x, "end": x - w}[anchor]
        self.d.add(Rect(x0 - 1.5, y - fs * 0.28, w + 3, fs * 1.18, fillColor=WHITE, strokeColor=None))
        self.text(x, y, s, fs=fs, color=color, anchor=anchor)

    def arrow(self, pts, color=MUTED, label=None, dashed=False, head=True, both=False, lx=None, ly=None, width=0.9):
        flat = [c for p in pts for c in p]
        kw = dict(strokeColor=color, strokeWidth=width)
        if dashed:
            kw["strokeDashArray"] = [3, 2]
        self.d.add(PolyLine(flat, **kw))
        if head:
            self._head(pts[-2], pts[-1], color)
        if both:
            self._head(pts[1], pts[0], color)
        if label:
            (x1, y1), (x2, y2) = pts[0], pts[1]
            self.text(lx if lx is not None else (x1 + x2) / 2 + 3, ly if ly is not None else (y1 + y2) / 2 + 3,
                      label, fs=6.6, anchor="start" if lx is None else "middle")

    def _head(self, a, b, color, size=4.5):
        import math
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        p1 = (b[0] - size * math.cos(ang - 0.42), b[1] - size * math.sin(ang - 0.42))
        p2 = (b[0] - size * math.cos(ang + 0.42), b[1] - size * math.sin(ang + 0.42))
        self.d.add(Polygon([b[0], b[1], p1[0], p1[1], p2[0], p2[1]], fillColor=color, strokeColor=color,
                           strokeWidth=0.5))

    @staticmethod
    def wrap(words, width, font="Body", fs=6.6, sep=", "):
        """Greedy-wrap a list of words into lines that fit `width`."""
        lines, cur = [], ""
        for w in words:
            cand = cur + sep + w if cur else w
            if cur and pdfmetrics.stringWidth(cand, font, fs) > width:
                lines.append(cur + sep.rstrip())
                cur = w
            else:
                cur = cand
        return lines + [cur] if cur else lines

    def line(self, x1, y1, x2, y2, color=LINE, width=0.8, dashed=False):
        kw = dict(strokeColor=color, strokeWidth=width)
        if dashed:
            kw["strokeDashArray"] = [2, 2]
        self.d.add(Line(x1, y1, x2, y2, **kw))


class TocMark(Flowable):
    """Invisible flowable that adds a TOC / bookmark entry for content without an H1/H2 paragraph."""

    def __init__(self, text, level=1):
        super().__init__()
        self.text, self.level = text, level

    def wrap(self, *_):
        return 0, 0

    def draw(self):
        pass


# ---------- document ----------
class ProjectDoc(BaseDocTemplate):
    def __init__(self, path, meta, total_pages=None):
        super().__init__(path, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=22 * mm,
                         bottomMargin=18 * mm, title=meta["title"], author=meta["author"],
                         subject=meta["subtitle"], creator="AI Employee Platform documentation")
        self.meta = meta
        self.total_pages = total_pages
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="body",
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate("cover", [frame], onPage=self._cover),
                               PageTemplate("body", [frame], onPage=self._chrome)])

    def afterFlowable(self, f):
        if isinstance(f, TocMark):
            level, text = f.level, f.text
        elif isinstance(f, Paragraph) and f.style.name in ("H1", "H2"):
            level = 0 if f.style.name == "H1" else 1
            text = f.getPlainText()
        else:
            level = None
        if level is not None:
            key = f"s{id(f)}"
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=level, closed=level > 0)
            self.notify("TOCEntry", (level, text, self.page, key))

    def _chrome(self, c, doc):
        m = self.meta
        c.saveState()
        c.setStrokeColor(LINE)
        c.setLineWidth(0.6)
        c.line(MARGIN, PAGE_H - 14 * mm, PAGE_W - MARGIN, PAGE_H - 14 * mm)
        c.setFont("Body-Bold", 7.5)
        c.setFillColor(NAVY)
        c.drawString(MARGIN, PAGE_H - 12 * mm, "AI EMPLOYEE PLATFORM")
        c.setFont("Body", 7.5)
        c.setFillColor(MUTED)
        c.drawRightString(PAGE_W - MARGIN, PAGE_H - 12 * mm, m["short"])
        c.line(MARGIN, 12 * mm, PAGE_W - MARGIN, 12 * mm)
        c.drawString(MARGIN, 8 * mm, m["footer"])
        total = f" of {self.total_pages}" if self.total_pages else ""
        c.drawRightString(PAGE_W - MARGIN, 8 * mm, f"Page {doc.page}{total}")
        c.restoreState()

    def _cover(self, c, doc):
        m = self.meta
        c.saveState()
        c.setFillColor(NAVY)
        c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        # decorative rings
        for r, col, a in [(150, BLUE, 0.35), (105, TEAL, 0.30), (62, colors.HexColor("#60A5FA"), 0.25)]:
            c.setStrokeColor(col)
            c.setStrokeAlpha(a)
            c.setLineWidth(14)
            c.circle(PAGE_W - 40 * mm, PAGE_H - 45 * mm, r, stroke=1, fill=0)
        c.setStrokeAlpha(1)
        c.setFillColor(TEAL)
        c.rect(MARGIN, PAGE_H - 92 * mm, 18 * mm, 1.6 * mm, fill=1, stroke=0)
        c.setFont("Body-Bold", 9)
        c.setFillColor(colors.HexColor("#5EEAD4"))
        c.drawString(MARGIN, PAGE_H - 84 * mm, m["kicker"])
        title = Paragraph(m["title"], ParagraphStyle("ct", fontName="Body-Bold", fontSize=28, leading=34,
                                                     textColor=WHITE))
        _, th = title.wrap(CONTENT_W - 20 * mm, 200 * mm)
        title.drawOn(c, MARGIN, PAGE_H - 100 * mm - th)
        sub = Paragraph(m["subtitle"], ParagraphStyle("cs", fontName="Body-Light", fontSize=13, leading=19,
                                                      textColor=colors.HexColor("#CBD5E1")))
        _, sh = sub.wrap(CONTENT_W - 30 * mm, 100 * mm)
        sub.drawOn(c, MARGIN, PAGE_H - 108 * mm - th - sh)
        tag = Paragraph(m["tagline"], ParagraphStyle("tg", fontName="Body-Italic", fontSize=10.5, leading=15,
                                                     textColor=colors.HexColor("#93C5FD")))
        _, tgh = tag.wrap(CONTENT_W, 50 * mm)
        tag.drawOn(c, MARGIN, PAGE_H - 118 * mm - th - sh - tgh)
        # meta grid
        y0 = 62 * mm
        c.setStrokeColor(colors.HexColor("#334155"))
        c.setLineWidth(0.6)
        c.line(MARGIN, y0 + 14 * mm, PAGE_W - MARGIN, y0 + 14 * mm)
        colw = CONTENT_W / 2
        for i, (k, v) in enumerate(m["cover_meta"]):
            x = MARGIN + (i % 2) * colw
            y = y0 - (i // 2) * 13 * mm
            c.setFont("Body", 7.5)
            c.setFillColor(colors.HexColor("#94A3B8"))
            c.drawString(x, y + 4.5 * mm, k.upper())
            c.setFont("Body-Bold", 10)
            c.setFillColor(WHITE)
            c.drawString(x, y, v)
        c.setFont("Body", 7.5)
        c.setFillColor(colors.HexColor("#94A3B8"))
        c.drawString(MARGIN, 14 * mm, m["cover_footer"])
        c.restoreState()


def build(path, meta, make_story):
    """Two passes: first to learn total page count, second to print 'Page X of Y'."""
    doc = ProjectDoc(path, meta)
    doc.multiBuild(make_story())
    total = doc.page
    doc = ProjectDoc(path, meta, total_pages=total)
    doc.multiBuild(make_story())
    return doc.page


def cover_story():
    return [NextPageTemplate("body"), Spacer(1, 1), PageBreak()]
