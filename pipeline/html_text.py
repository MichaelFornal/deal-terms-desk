import re
from html.parser import HTMLParser

from pipeline.normalise import canonical

BLOCK = {"p", "div", "br", "tr", "li", "table", "h1", "h2", "h3", "h4", "h5", "h6", "center", "hr", "dd", "dt", "ul", "ol", "blockquote", "pre"}
SKIP = {"script", "style", "title"}
PAGE_LINE = re.compile(r"(?m)^[ \t]*(?:-\s*\d{1,3}\s*-|\d{1,3}|Page\s+\d{1,3}(?:\s+of\s+\d{1,3})?)[ \t]*\n")
TEXT_BLOCK = re.compile(r"<TEXT>(.*?)(?:</TEXT>|\Z)", re.I | re.S)
# Only an EDGAR submission wrapper has a <TEXT> block; an HTML exhibit may hold an SVG <text> element.
SGML_START = re.compile(r"\ufeff?\s*<(?:SEC-DOCUMENT|DOCUMENT)>", re.I)
SPACES = re.compile(r"[ \t\xa0]+")


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skipping = 0
        self.pre = 0

    def handle_starttag(self, tag, attrs):
        if tag == "pre":
            self.pre += 1
        if tag in SKIP:
            self.skipping += 1
        elif tag in BLOCK:
            self.out.append("\n")
        elif tag in ("td", "th"):
            self.out.append(" ")

    def handle_endtag(self, tag):
        if tag == "pre":
            self.pre = max(0, self.pre - 1)
        if tag in SKIP:
            self.skipping = max(0, self.skipping - 1)
        elif tag in BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skipping:
            self.out.append(data if self.pre else data.replace("\n", " "))


def _is_html(s: str, filename: str) -> bool:
    head = s[:2000].lower()
    return filename.lower().endswith((".htm", ".html")) or "<html" in head or "<body" in head


def to_text(raw: bytes, filename: str) -> str:
    try:
        s = raw.decode("utf-8")
    except UnicodeDecodeError:
        s = raw.decode("cp1252", errors="replace")
    m = TEXT_BLOCK.search(s) if filename.lower().endswith(".txt") or SGML_START.match(s) else None
    if m:
        s = m.group(1)
    if _is_html(s, filename):
        p = _Text()
        p.feed(s)
        p.close()
        s = "".join(p.out)
    s = canonical(s)
    s = "\n".join(SPACES.sub(" ", line).strip() for line in s.split("\n"))
    s = PAGE_LINE.sub("", s + "\n")
    s = re.sub(r"\n{3,}", "\n\n", s).strip("\n")
    return s + "\n"
