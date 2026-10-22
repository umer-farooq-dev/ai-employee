"""A tiny PDF writer for invoices (SUB-06): text in the PDF base fonts, lines and filled boxes on A4 pages.
No extra dependency; the base fonts cover Latin-1, so "₹" is printed as "Rs.".

ponytail: base-14 fonts only (no Unicode/Indic scripts in the PDF); embed a TTF if invoices ever need them.
"""

import zlib

A4 = (595.28, 841.89)
FONTS = {"regular": "Helvetica", "bold": "Helvetica-Bold"}
# Helvetica advance widths (1/1000 em) for the printable ASCII range, used to right-align and wrap text
_W = (
    "278,278,355,556,556,889,667,191,333,333,389,584,278,333,278,278,556,556,556,556,556,556,556,556,556,556,278,278,"
    "584,584,584,556,1015,667,667,722,722,667,611,778,722,278,500,667,556,833,722,778,667,778,722,667,611,722,667,"
    "944,667,667,611,278,278,278,469,556,333,556,556,500,556,556,278,556,556,222,222,500,222,833,556,556,556,556,333,"
    "500,278,556,500,722,500,500,500,334,260,334,584"
)
WIDTHS = [int(x) for x in _W.split(",")]
_WB = (
    "278,333,474,556,556,889,722,238,333,333,389,584,278,333,278,278,556,556,556,556,556,556,556,556,556,556,333,333,"
    "584,584,584,611,975,722,722,722,722,667,611,778,722,278,556,722,611,833,722,778,667,778,722,667,611,722,667,"
    "944,667,667,611,333,278,333,584,556,333,556,611,556,611,556,333,611,611,278,278,556,278,889,611,611,611,611,389,"
    "556,333,611,556,778,556,556,500,389,280,389,584"
)
WIDTHS_BOLD = [int(x) for x in _WB.split(",")]


def clean(text):
    text = str(text).replace("₹", "Rs.").replace("–", "-").replace("—", "-").replace("’", "'").replace("…", "...")
    return text.encode("latin-1", "replace").decode("latin-1")


def width(text, size, bold=False):
    table = WIDTHS_BOLD if bold else WIDTHS
    return sum(table[ord(c) - 32] if 32 <= ord(c) < 127 else 556 for c in clean(text)) * size / 1000


def wrap(text, size, max_width, bold=False):
    lines = []
    for para in clean(text).splitlines() or [""]:
        line = ""
        for word in para.split(" "):
            test = f"{line} {word}".strip()
            if width(test, size, bold) <= max_width or not line:
                line = test
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def _esc(text):
    return clean(text).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _rgb(hex_colour):
    h = (hex_colour or "#000000").lstrip("#")
    return " ".join(f"{int(h[i:i + 2], 16) / 255:.3f}" for i in (0, 2, 4))


class Document:
    """Coordinates are from the top-left corner in points (1/72 inch)."""

    def __init__(self):
        self.pages = []
        self.new_page()

    def new_page(self):
        self.ops = []
        self.pages.append(self.ops)

    def text(self, x, y, text, size=10, bold=False, colour="#1f2937", align="left"):
        if align == "right":
            x -= width(text, size, bold)
        elif align == "center":
            x -= width(text, size, bold) / 2
        font = "F2" if bold else "F1"
        self.ops.append(
            f"BT {_rgb(colour)} rg /{font} {size} Tf {x:.2f} {A4[1] - y - size:.2f} Td ({_esc(text)}) Tj ET"
        )

    def line(self, x1, y1, x2, y2, colour="#e5e7eb", w=0.8):
        self.ops.append(f"{_rgb(colour)} RG {w} w {x1:.2f} {A4[1] - y1:.2f} m {x2:.2f} {A4[1] - y2:.2f} l S")

    def box(self, x, y, w, h, fill="#f3f4f6"):
        self.ops.append(f"{_rgb(fill)} rg {x:.2f} {A4[1] - y - h:.2f} {w:.2f} {h:.2f} re f")

    def render(self):
        objs = [
            "<< /Type /Catalog /Pages 2 0 R >>",
            None,  # pages, filled below
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        ]
        kids = []
        for ops in self.pages:
            stream = zlib.compress("\n".join(ops).encode("latin-1"))
            objs.append(f"<< /Length {len(stream)} /Filter /FlateDecode >>stream\n".encode("latin-1") + stream)
            content = len(objs)
            objs.append(
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {A4[0]} {A4[1]}] "
                f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content} 0 R >>"
            )
            kids.append(f"{len(objs)} 0 R")
        objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
        out, offsets = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"), []
        for i, obj in enumerate(objs, 1):
            offsets.append(len(out))
            body = obj if isinstance(obj, bytes) else obj.encode("latin-1")
            end = b"\nendstream" if isinstance(obj, bytes) else b""
            out += f"{i} 0 obj\n".encode() + body + end + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
        out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
        out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        return bytes(out)
