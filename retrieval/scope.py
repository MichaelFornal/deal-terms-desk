import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass

RAW_WORD = re.compile(r"[A-Za-z0-9]+|&")
# Corporate suffixes and the possessive "s" that follow a company's name; dropped with the name.
SUFFIXES = frozenset({"inc", "incorporated", "corp", "corporation", "co", "ltd", "limited", "llc", "plc", "s"})
# A token in at least this many passages is an ordinary contract word ("base", "true", "fair"), so a
# Titlecase copy of it at the start of a sentence is not taken for a company. Measured on deals.db in M4 planning.
COMMON_MIN_PASSAGES = 100
SENTENCE_END = re.compile(r"[.?!:]\s*$")


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
    query if nothing else is left. Corporate suffixes and a possessive 's' right after the alias go with it."""
    a, words = tokens(alias), _words(query)
    if not a:
        return query
    keep, i, n = [], 0, len(a)
    while i < len(words):
        run = tuple(t for _, t in words[i:i + n])
        if run == a and (n > 1 or _capital(words[i][0])):
            i += n
            while i < len(words) and words[i][1] in SUFFIXES:
                i += 1
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
        self.conn = conn
        self.has_fts = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'passages_fts'").fetchone() is not None
        self._common: dict[str, bool] = {}
        self.by_kind: dict[str, dict[tuple[str, ...], set[str]]] = {"target": defaultdict(set),
                                                                     "parent": defaultdict(set)}
        for alias, cid, kind in conn.execute("SELECT alias, contract_id, kind FROM aliases"):
            t = tokens(alias)
            if t:
                self.by_kind[kind][t].add(cid)

    def _is_common(self, token: str) -> bool:
        if not self.has_fts:
            return False
        if token not in self._common:
            n = self.conn.execute("SELECT COUNT(*) FROM passages_fts WHERE passages_fts MATCH ?",
                                  (f'"{token}"',)).fetchone()[0]
            self._common[token] = n >= COMMON_MIN_PASSAGES
        return self._common[token]

    @staticmethod
    def _starts(query: str, words: list[tuple[str, str]]) -> list[bool]:
        """For each word, whether it opens a sentence (first word, or after . ? ! :)."""
        out, pos = [], 0
        for raw, _ in words:
            at = query.find(raw, pos)
            out.append(at >= 0 and (not query[:at].strip() or bool(SENTENCE_END.search(query[:at]))))
            pos = at + len(raw) if at >= 0 else pos
        return out

    def _name_like(self, i: int, words, starts) -> bool:
        """A one-word alias at word i reads as a name: capitalised, and not just a common word opening a sentence."""
        raw, tok = words[i]
        if not _capital(raw):
            return False
        if raw.isupper() or not starts[i]:
            return True
        nxt = words[i + 1][1] if i + 1 < len(words) else ""
        return nxt in SUFFIXES - {"s"} or not self._is_common(tok)

    @staticmethod
    def _occurs(alias: tuple[str, ...], q: tuple[str, ...]) -> bool:
        n = len(alias)
        return any(q[i:i + n] == alias for i in range(len(q) - n + 1))

    def resolve(self, query: str) -> Scope:
        words = _words(query)
        q = tuple(t for _, t in words)
        starts = self._starts(query, words)
        single = {t for i, (_, t) in enumerate(words) if self._name_like(i, words, starts)}
        for kind in ("target", "parent"):
            hits = [a for a in self.by_kind[kind] if (len(a) > 1 or a[0] in single) and self._occurs(a, q)]
            if not hits:
                continue
            longest = max(len(a) for a in hits)
            top = [a for a in hits if len(a) == longest]
            cids = sorted(set().union(*(self.by_kind[kind][a] for a in top)))
            alias = " ".join(sorted(top)[0])
            return Scope(cids[0], alias, tuple(cids)) if len(cids) == 1 else Scope(None, alias, tuple(cids))
        return Scope(None, None, ())
