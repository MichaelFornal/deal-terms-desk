import re
from dataclasses import dataclass

_QUOTED = "[“\"]([A-Z][^“\"\n]{1,80})[”\"]"
MEANS = re.compile(_QUOTED + r"\s+(?:means|shall mean|has the meaning|shall have the meaning)\b")
PAREN = re.compile(r"\((?:the|each,? an?|collectively,? the|together,? the)?\s*" + _QUOTED + r"\)")


@dataclass(frozen=True)
class Term:
    term: str
    start: int
    end: int
    style: str


def extract_terms(text: str) -> list[Term]:
    out = [Term(m.group(1).strip(), m.start(), m.end(), "means") for m in MEANS.finditer(text)]
    out += [Term(m.group(1).strip(), m.start(), m.end(), "paren") for m in PAREN.finditer(text)]
    return sorted(out, key=lambda t: t.start)
