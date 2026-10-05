import json
from dataclasses import dataclass
from pathlib import Path

PER = 1_000_000
CHARS_PER_TOKEN = 3  # deliberately low: contract English runs nearer four characters a token, so this over-reserves


@dataclass(frozen=True)
class Prices:
    """USD per million tokens for one model, with where and when the numbers were read."""
    model: str
    input: float
    output: float
    cache_write: float
    cache_read: float
    source: str
    checked: str


def load_prices(path) -> Prices:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return Prices(d["model"], float(d["input_per_mtok"]), float(d["output_per_mtok"]),
                  float(d["cache_write_per_mtok"]), float(d["cache_read_per_mtok"]), d["source"], d["checked"])


def cost_usd(p: Prices, usage: dict | None) -> float:
    """What one call cost, from its usage (the four API counters; missing or None count as zero)."""
    u = usage or {}

    def n(k: str) -> int:
        return int(u.get(k) or 0)
    return (n("input_tokens") * p.input + n("output_tokens") * p.output
            + n("cache_creation_input_tokens") * p.cache_write + n("cache_read_input_tokens") * p.cache_read) / PER


def worst_case_usd(p: Prices, prompt_chars: int, max_tokens: int) -> float:
    """The most a call can cost before it is made: the prompt at three characters a token, plus the full output
    cap. The budget reserves this; calibration checks it is never below an actual cost."""
    return (prompt_chars / CHARS_PER_TOKEN * p.input + max_tokens * p.output) / PER
