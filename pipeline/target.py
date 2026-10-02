import re
from dataclasses import dataclass
from datetime import date

TECH_SIC = ((3570, 3579), (3661, 3679), (7370, 7379))
PREAMBLE_CHARS = 6000
MONTHS = ("January February March April May June July August September October November December").split()
_Q = "[“\"]"
_QE = "[”\"]"
# A party name is a run of capitalised words (with "of", "and", "de", "la", "the" inside), so a match cannot
# start back in the preamble's prose ("dated as of March 1, 2016, ... among Big Buyer Corp.").
NAME = r"(?P<name>[A-Z0-9][\w.&'’\-]*(?:,?\s+(?:[A-Z0-9&][\w.&'’\-]*|of|and|de|la|the))*)"
PARTY = re.compile(
    NAME + r",?\s+(?:a|an)\s+[A-Za-z .’'\-]{0,80}?"
    r"(?:corporation|company|partnership|N\.V\.|B\.V\.|S\.A\.|plc|Ltd\.?|limited)\b[^()“”\"]{0,120}?"
    r"\(\s*(?:the\s+)?" + _Q + r"(?P<role>[A-Z][A-Za-z ]{1,40})" + _QE + r"\s*\)", re.S)
COMPANY_ROLES = ("Company", "Target")
PARENT_ROLES = ("Parent", "Acquiror", "Acquirer", "Buyer", "Purchaser")
MONTH = "(" + "|".join(MONTHS) + ")"
DATED_AS_OF = re.compile(r"dated\s+as\s+of\s+" + MONTH + r"\s+(\d{1,2}),?\s+(\d{4})", re.I)
DATED = re.compile(r"dated\s+(?:as\s+of\s+)?" + MONTH + r"\s+(\d{1,2}),?\s+(\d{4})", re.I)
PROSE_END = re.compile(r"[.;:]\s+|" + MONTH + r"\s+\d{1,2},\s+\d{4},?\s+|"
                       r"\b(?:by\s+and\s+among|by\s+and\s+between|among|between)\s+", re.I)
ABBREVIATIONS = ("corp", "inc", "co", "ltd", "llc", "l.p", "lp", "n.v", "b.v", "s.a", "bros", "no")
DAY_OF = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+day\s+of\s+" + MONTH + r",?\s+(\d{4})", re.I)
AMENDMENT = re.compile(r"\bAmendment\s+No\.?\s*\d|\b(?:First|Second|Third)\s+Amendment\b|"
                       r"\bAmendment\s+to\s+(?:the\s+)?Agreement\s+and\s+Plan\s+of\s+Merger", re.I)
SUFFIX = re.compile(r"\b(?:incorporated|inc|corporation|corp|company|co|ltd|limited|llc|plc|nv|holdings|holding|"
                    r"group|the)\b")


@dataclass(frozen=True)
class Preamble:
    company: str | None
    parent: str | None
    signed: date | None
    amendment: bool


def is_tech(sic) -> bool:
    try:
        n = int(str(sic).strip())
    except (TypeError, ValueError):
        return False
    return any(lo <= n <= hi for lo, hi in TECH_SIC)


def _signed(head: str) -> date | None:
    m = DATED_AS_OF.search(head) or DATED.search(head)
    if m:
        return _date(int(m.group(3)), m.group(1), int(m.group(2)))
    m = DAY_OF.search(head)
    if m:
        return _date(int(m.group(3)), m.group(2), int(m.group(1)))
    return None


def _date(year: int, month: str, day: int) -> date | None:
    try:
        return date(year, MONTHS.index(month.capitalize()) + 1, day)
    except ValueError:
        return None


def _trim(name: str) -> str:
    end = 0
    for m in PROSE_END.finditer(name):
        if name[m.start()] == "." and name[:m.start()].lower().split(" ")[-1].split(",")[-1] in ABBREVIATIONS:
            continue
        end = m.end()
    return name[end:].strip(" ,")


def preamble(text: str) -> Preamble:
    head = text[:PREAMBLE_CHARS]
    roles: dict[str, str] = {}
    for m in PARTY.finditer(head):
        roles.setdefault(m.group("role").strip(), _trim(m.group("name")))
    company = next((roles[r] for r in COMPANY_ROLES if r in roles), None)
    parent = next((roles[r] for r in PARENT_ROLES if r in roles), None)
    return Preamble(company, parent, _signed(head), bool(AMENDMENT.search(head[:1500])))


def norm(name: str) -> str:
    s = name.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = SUFFIX.sub(" ", s)
    return " ".join(s.split())


def deal_key(p: Preamble) -> tuple[str, str, str] | None:
    if not (p.company and p.parent and p.signed):
        return None
    return norm(p.company), norm(p.parent), p.signed.isoformat()


def resolve(company: str, ciks: list[str], names: list[str]) -> str | None:
    if len(ciks) != len(names):
        raise ValueError(f"{len(ciks)} CIKs but {len(names)} names")
    target = norm(company)
    if not target:
        return None
    found = []
    for cik, display in zip(ciks, names):
        n = norm(re.sub(r"\(.*?\)", " ", display))
        if not n:
            continue
        short, long_ = sorted((n, target), key=lambda x: len(x.split()))
        if n == target or (long_.startswith(short + " ") and len(short.split()) >= 2):
            found.append(cik)
    return found[0] if len(found) == 1 else None
