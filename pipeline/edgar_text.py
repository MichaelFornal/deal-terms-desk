import re
from collections import Counter

UNICODE_SPACES = re.compile(r"[   -​  　]")
SPLIT_HEADING = re.compile(r"(?m)^([ \t]*(?:(?:Section|SECTION)[ \t]+)?\d{1,2}\.\d{1,2}\.?)[ \t]*\n+[ \t]*(?=[A-Z])")
HEADING_LINE = re.compile(r"(?i)^(?:section|article)\b|^\(?[a-z0-9]{1,4}\)")
RUNNING_MIN = 8
TITLES = ("agreement and plan of merger", "plan and agreement of merger", "agreement of merger", "plan of merger",
          "merger agreement")
NOT_THE_AGREEMENT = ("termination", "voting", "support", "tender", "letter")


def _drop_running_lines(text: str) -> str:
    lines = text.split("\n")
    counts = Counter(s for s in (l.strip() for l in lines) if 3 < len(s) < 80)
    drop = {s for s, n in counts.items() if n >= RUNNING_MIN and not HEADING_LINE.match(s)}
    return "\n".join(l for l in lines if l.strip() not in drop)


def normalise_edgar(text: str) -> str:
    t = UNICODE_SPACES.sub(" ", text)
    t = SPLIT_HEADING.sub(r"\1 ", t)
    t = _drop_running_lines(t)
    return re.sub(r"\n{3,}", "\n\n", t)


def own_title(text: str) -> str:
    for line in text[:3000].split("\n"):
        if len(line) < 160 and re.search(r"\b(?:AGREEMENT|PLAN)\b", line):
            return " ".join(line.split()).lower()
    return " ".join(text[:200].split()).lower()


def is_merger_agreement(text: str) -> bool:
    title = own_title(text)
    title = re.sub(r"^exhibit\s+[\d.]+\s*", "", title)
    return any(t in title for t in TITLES) and not title.startswith(NOT_THE_AGREEMENT)
