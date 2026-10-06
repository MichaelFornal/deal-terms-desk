"""`dtd copycheck`: every number in hand-written Markdown (the README, the launch post) checked against facts.json,
and every machine-built number checked for its label. It reports and never writes: the copy is Michael's."""
import math
import re
from dataclasses import dataclass, replace

from facts.labels import MACHINE, is_machine_built

FLAGGED = ("no fact", "needs machine-built label")
SHOWN = 4  # matching keys printed per number before "+k more"

FENCE = re.compile(r"^\s*(```|~~~)")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
ROW = re.compile(r"^\s*\|")
REFDEF = re.compile(r"^\s*\[[^\]]+\]:\s*\S+.*$")  # [7]: https://… (a link reference definition)
# Code spans, link targets, footnote markers, HTML tags and bare URLs carry no copy numbers.
INLINE = re.compile(r"`[^`]*`|\]\([^)]*\)|\[\^[^\]]*\]|</?[A-Za-z][^>]*>|https?://\S+")
ORDINAL = re.compile(r"^(\s*)\d+[.)](?=\s)")
# Letters and digits are spelled out rather than \w, which holds "_": Markdown emphasis (_60%_, __88,628__) must not
# hide a number.
DATE = re.compile(r"(?<![A-Za-z0-9.-])\d{4}-\d{2}-\d{2}(?![A-Za-z0-9-])")
# A number that touches no letter, dot, hyphen or digit on either side: "M5", "R7n", "v1.5" and model ids are names.
NUMBER = re.compile(r"(?<![A-Za-z0-9.-])(-?)(\$?)(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(%?)(?![A-Za-z0-9%]|\.\d)")


@dataclass(frozen=True)
class Found:
    line: int
    raw: str
    status: str
    keys: tuple[str, ...]
    unlabelled_machine: bool = False  # plain and machine-built keys, no label nearby: a fact, counted in the summary


def _labelled(context: str) -> bool:
    return MACHINE in re.sub("machine-built lexicon", "", context.lower())


def _contexts(lines: list[str], code: list[bool]) -> list[str]:
    """For each line, the text that can label its numbers: its paragraph, list item or table row (each item and
    row stands alone), plus the nearest heading above it."""
    blocks: list[list[int]] = []
    block_of: list[int | None] = [None] * len(lines)
    heading_of = [""] * len(lines)
    heading, current = "", None
    for i, line in enumerate(lines):
        if code[i] or not line.strip():
            current = None
            continue
        if HEADING.match(line):
            heading, current = line, None
            blocks.append([i])
            block_of[i], heading_of[i] = len(blocks) - 1, line
            continue
        if current is None or ITEM.match(line) or ROW.match(line) or ROW.match(lines[i - 1]):
            blocks.append([])
            current = len(blocks) - 1
        blocks[current].append(i)
        block_of[i], heading_of[i] = current, heading
    return [("" if b is None else " ".join(lines[j] for j in blocks[b])) + "\n" + heading_of[i]
            for i, b in enumerate(block_of)]


def _match(m: re.Match, numeric: list[tuple[str, float]]) -> tuple[str, tuple[str, ...]]:
    sign, _dollar, whole, frac, pct = m.groups()
    digits = whole.replace(",", "")
    value = float(sign + digits + (frac or ""))
    places = len(frac) - 1 if frac else 0
    significant = len((digits + (frac or "")[1:]).lstrip("0"))
    exact, rounded = [], []
    for key, fact in numeric:
        # "60%": a rate shown as a percent, or a fact already held in percent (the _pct keys)
        shown = fact if (not pct or key.endswith("_pct")) else fact * 100
        if math.isclose(shown, value, rel_tol=1e-9, abs_tol=1e-9):
            exact.append(key)
        elif significant >= 2 and math.isclose(round(shown, places), value, rel_tol=1e-9, abs_tol=1e-9):
            rounded.append(key)
    if exact:
        return "fact", tuple(exact)
    if rounded:
        return "rounded", tuple(rounded)
    return "no fact", ()


def check(text: str, facts: dict) -> list[Found]:
    """Every number in `text` (Markdown), in reading order, with the facts it matches and whether it needs the
    machine-built label it lacks."""
    lines = text.splitlines()
    code, fenced = [], False
    for line in lines:
        if FENCE.match(line):
            code.append(True)
            fenced = not fenced
        else:
            code.append(fenced)
    contexts = _contexts(lines, code)
    numeric = [(k, float(v)) for k, v in facts.items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    strings = [(k, v) for k, v in facts.items() if isinstance(v, str)]
    found = []
    for i, line in enumerate(lines):
        if code[i] or REFDEF.match(line):
            continue
        prose = ORDINAL.sub(lambda m: m.group(1), INLINE.sub(" ", line))
        hits = []
        for m in DATE.finditer(prose):
            keys = tuple(k for k, v in strings if m.group() in v)
            hits.append((m.start(), m.group(), "fact" if keys else "no fact", keys))
        prose = DATE.sub(lambda m: " " * len(m.group()), prose)
        for m in NUMBER.finditer(prose):
            hits.append((m.start(), m.group(), *_match(m, numeric)))
        for _, raw, status, keys in sorted(hits):
            f = Found(i + 1, raw, status, keys)
            machine = tuple(k for k in keys if is_machine_built(k))
            # flagged only when every match is machine-built; a mixed match stays a fact, and is counted when unlabelled
            if machine and not _labelled(contexts[i]):
                if len(machine) == len(keys):
                    f = replace(f, status="needs machine-built label", keys=machine)
                else:
                    f = replace(f, unlabelled_machine=True)
            found.append(f)
    return found


def render(name: str, found: list[Found]) -> str:
    out = []
    for f in found:
        mixed = not all(is_machine_built(k) for k in f.keys)  # tag machine-built keys only among plain ones
        ordered = sorted(f.keys, key=lambda k: not is_machine_built(k))  # machine-built first: "+k more" hides none
        shown = [k + (" [machine-built]" if mixed and is_machine_built(k) else "") for k in ordered[:SHOWN]]
        keys = ", ".join(shown) + (f" +{len(f.keys) - SHOWN} more" if len(f.keys) > SHOWN else "")
        note = "  (no machine-built label nearby)" if f.unlabelled_machine else ""
        out.append(f'{name}:{f.line}  "{f.raw}"  {f.status}  {keys}{note}'.rstrip())
    exact = sum(f.status == "fact" for f in found)
    rounded = sum(f.status == "rounded" for f in found)
    flagged = sum(f.status in FLAGGED for f in found)
    unlabelled = sum(f.unlabelled_machine for f in found)
    numbers = f"{len(found)} number" + ("" if len(found) == 1 else "s")
    check_rounded = ": check each names the fact you mean" if rounded else ""
    summary = f"{name}: {numbers} ({exact} exact, {rounded} rounded{check_rounded}), {flagged} flagged"
    if unlabelled:
        also = "number also matches" if unlabelled == 1 else "numbers also match"
        summary += f"; {unlabelled} unlabelled {also} a machine-built fact"
    out.append(summary)
    return "\n".join(out)
