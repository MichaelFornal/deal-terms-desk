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
    # Word for word: a quote that starts or ends on a word character must sit on a token boundary there.
    pat = re.compile((r"(?<!\w)" if re.match(r"\w", q) else "") + re.escape(q) + (r"(?!\w)" if re.search(r"\w$", q) else ""))
    for part in blk.parts:
        if pat.search(normalise(part.text)):
            return blk, part
    return "quote_not_found"
