import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass

RAW_WORD = re.compile(r"[A-Za-z0-9]+|&")


def _words(s: str) -> list[tuple[str, str]]:
    """(raw word, token) pairs; the tokens are exactly `tokens(s)`."""
    return [(w, "and" if w == "&" else w.lower()) for w in RAW_WORD.findall(s)]


def tokens(s: str) -> tuple[str, ...]:
    return tuple(t for _, t in _words(s))


def _capital(raw: str) -> bool:
    return raw[0].isupper() or raw.isupper()


def strip_alias(query: str, alias: str) -> str:
    """The query without each run of the alias's tokens, other words kept in order. A one-word alias is dropped
    only where it is capitalised, as the resolver matched it. Unchanged if the alias is absent; the original
    query if nothing else is left."""
    a, words = tokens(alias), _words(query)
    if not a:
        return query
    keep, i, n = [], 0, len(a)
    while i < len(words):
        run = tuple(t for _, t in words[i:i + n])
        if run == a and (n > 1 or _capital(words[i][0])):
            i += n
            continue
        keep.append(words[i][0])
        i += 1
    if len(keep) == len(words) or not keep:
        return query
    return " ".join(keep)


@dataclass(frozen=True)
class Scope:
    contract_id: str | None
    alias: str | None
    candidates: tuple[str, ...]


class Resolver:
    def __init__(self, conn: sqlite3.Connection):
        self.by_kind: dict[str, dict[tuple[str, ...], set[str]]] = {"target": defaultdict(set),
                                                                     "parent": defaultdict(set)}
        for alias, cid, kind in conn.execute("SELECT alias, contract_id, kind FROM aliases"):
            t = tokens(alias)
            if t:
                self.by_kind[kind][t].add(cid)

    @staticmethod
    def _occurs(alias: tuple[str, ...], q: tuple[str, ...]) -> bool:
        n = len(alias)
        return any(q[i:i + n] == alias for i in range(len(q) - n + 1))

    def resolve(self, query: str) -> Scope:
        words = _words(query)
        q = tuple(t for _, t in words)
        capital = {t for w, t in words if _capital(w)}  # "true" or "base" as a plain word is not a company
        for kind in ("target", "parent"):
            hits = [a for a in self.by_kind[kind] if (len(a) > 1 or a[0] in capital) and self._occurs(a, q)]
            if not hits:
                continue
            longest = max(len(a) for a in hits)
            top = [a for a in hits if len(a) == longest]
            cids = sorted(set().union(*(self.by_kind[kind][a] for a in top)))
            alias = " ".join(sorted(top)[0])
            return Scope(cids[0], alias, tuple(cids)) if len(cids) == 1 else Scope(None, alias, tuple(cids))
        return Scope(None, None, ())
