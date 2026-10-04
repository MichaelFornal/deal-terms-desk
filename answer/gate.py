import re

from answer.blocks import Block, Part

# Typographic quotes and dashes fold to ASCII; this changes no word, and models routinely retype them.
FOLD = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-"})
REF = re.compile(r"^\[?\s*[Pp](\d+)\s*\]?$")


def normalise(s: str) -> str:
    return " ".join(s.translate(FOLD).split())


def check(quote: str, ref: str, blocks: list[Block]) -> tuple[Block, Part] | str:
    """The block and part a quote occurs in, word for word after normalisation, or the reason it fails."""
    q = normalise(quote or "")
    if not q:
        return "empty_quote"
    m = REF.match(str(ref or "").strip())
    blk = next((b for b in blocks if m and b.ref == f"P{m.group(1)}"), None)
    if blk is None:
        return "bad_ref"
    for part in blk.parts:
        if q in normalise(part.text):
            return blk, part
    return "quote_not_found"
