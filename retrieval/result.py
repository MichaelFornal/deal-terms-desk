from dataclasses import dataclass, field

from retrieval.bm25 import Hit

CONTEXT_K = 5


@dataclass(frozen=True)
class Retrieved:
    hits: list[Hit]
    ms: float
    context: list[str]
    amended: tuple[str, ...] = ()
    scope: object = None  # retrieval.scope.Scope | None; set by R7 only (object avoids an import cycle)
    # passage_id -> {"bm25": {"rank", "score"} | None, "dense": {"rank", "score"} | None}: where each returned hit
    # stood in each leg before fusion. Filled for the hybrid rungs (R3-R6, R6n, R7/R7n through them); {} otherwise.
    stages: dict = field(default_factory=dict)
