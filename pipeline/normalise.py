from pathlib import Path


def canonical(raw: str) -> str:
    """The text every character offset in this project refers to."""
    if raw.startswith("﻿"):
        raw = raw[1:]
    return raw.replace("\r\n", "\n").replace("\r", "\n")


def load_contract(path: Path) -> str:
    return canonical(Path(path).read_bytes().decode("utf-8", errors="replace"))


def squash(text: str) -> tuple[str, list[int]]:
    """Remove all whitespace; index[i] is the offset in text of squashed[i]."""
    chars: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        if not ch.isspace():
            chars.append(ch)
            index.append(i)
    return "".join(chars), index
