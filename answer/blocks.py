from dataclasses import dataclass


@dataclass(frozen=True)
class Part:
    kind: str  # "passage" | "definition" | "amendment"
    text: str
    amendment_no: int | None = None


@dataclass(frozen=True)
class Block:
    ref: str
    passage_id: int
    contract_id: str
    section_path: str
    schedule_ref: bool
    parts: tuple[Part, ...]


def _has_table(conn, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone() is not None


def build_blocks(ladder, hits) -> list[Block]:
    """One block per hit: the passage, the definitions it depends on, then any amending text. The same text the
    ladder shows as context (`Ladder._shown` with definitions), with the boundaries between parts kept."""
    conn, tags = ladder.conn, _has_table(ladder.conn, "passage_tags")
    out = []
    for i, h in enumerate(hits, start=1):
        text = ladder.texts[h.contract_id]
        parts = [Part("passage", text[h.start:h.end])]
        parts += [Part("definition", text[s:e]) for s, e in conn.execute(
            "SELECT def_start, def_end FROM passage_defs WHERE passage_id = ? ORDER BY rank", (h.passage_id,))]
        parts += [Part("amendment", ladder.amendment_texts[aid][a0:a1], no)
                  for aid, no, _, a0, a1 in ladder._amendments(h)]
        path = conn.execute("SELECT section_path FROM passages WHERE passage_id = ?", (h.passage_id,)).fetchone()[0]
        sched = tags and conn.execute("SELECT 1 FROM passage_tags WHERE passage_id = ? AND tag = 'schedule_ref'",
                                      (h.passage_id,)).fetchone() is not None
        out.append(Block(f"P{i}", h.passage_id, h.contract_id, path, bool(sched), tuple(parts)))
    return out
