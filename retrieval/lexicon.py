import json
import re
from functools import lru_cache
from pathlib import Path

LEXICON_PATH = Path(__file__).with_name("lexicon.json")


def load_lexicon(path: Path = LEXICON_PATH) -> dict[str, list[str]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["entries"]


@lru_cache(maxsize=4096)
def _pattern(phrase: str) -> re.Pattern:
    return re.compile(r"(?<![a-z0-9])" + re.escape(phrase.lower()) + r"(?![a-z0-9])")


def rewrite(query: str, lexicon: dict[str, list[str]]) -> str:
    low = query.lower()
    extra: list[str] = []
    for phrase in sorted(lexicon, key=lambda p: (-len(p), p)):
        if _pattern(phrase).search(low):
            for term in lexicon[phrase]:
                if not _pattern(term).search(low) and term not in extra:
                    extra.append(term)
    return query if not extra else query + " " + " ".join(extra)
