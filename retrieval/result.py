from dataclasses import dataclass

from retrieval.bm25 import Hit

CONTEXT_K = 5


@dataclass(frozen=True)
class Retrieved:
    hits: list[Hit]
    ms: float
    context: list[str]
