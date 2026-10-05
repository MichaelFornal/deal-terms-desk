import math
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    bundle: Path
    state_dir: Path
    prices_path: Path
    facts_path: Path
    model: str
    max_tokens: int
    month_cap_usd: float
    day_cap_usd: float
    question_max_chars: int
    ask_per_hour: int
    search_per_minute: int
    fresh_per_hour: int
    ask_slots: int
    git_sha: str


def _num(env, name: str, cast, default):
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = cast(raw)
    except ValueError:
        raise ValueError(f"{name} must be a {cast.__name__}, got {raw!r}") from None
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive, finite number, got {raw!r}")
    return value


def _git_sha(env) -> str:
    """The deployed commit: DTD_GIT_SHA, else the GIT_SHA file push.sh writes into each release, else unknown."""
    if (env.get("DTD_GIT_SHA") or "").strip():
        return env["DTD_GIT_SHA"].strip()
    f = Path("GIT_SHA")
    return (f.read_text(encoding="utf-8").strip() or "unknown") if f.exists() else "unknown"


def from_env(env=os.environ) -> Config:
    """The service's settings from DTD_* variables (on the box: /etc/dtd/env). The month cap has no default:
    a service that does not know its budget must not start."""
    if not (env.get("DTD_MONTH_CAP_USD") or "").strip():
        raise ValueError("DTD_MONTH_CAP_USD is not set: the month's model budget in USD (the $10 cap minus "
                         "hosting, from deploy/hosting.json)")
    month = _num(env, "DTD_MONTH_CAP_USD", float, None)
    return Config(
        bundle=Path(env.get("DTD_BUNDLE") or "data/live/live.db"),
        state_dir=Path(env.get("DTD_STATE") or "data/state"),
        prices_path=Path(env.get("DTD_PRICES") or "service/prices.json"),
        facts_path=Path(env.get("DTD_FACTS") or "facts.json"),
        model=env.get("DTD_MODEL") or "claude-haiku-4-5-20251001",
        max_tokens=_num(env, "DTD_MAX_TOKENS", int, 1024),
        month_cap_usd=month,
        day_cap_usd=_num(env, "DTD_DAY_CAP_USD", float, month / 10),
        question_max_chars=_num(env, "DTD_QUESTION_MAX_CHARS", int, 500),
        ask_per_hour=_num(env, "DTD_ASK_PER_HOUR", int, 20),
        search_per_minute=_num(env, "DTD_SEARCH_PER_MINUTE", int, 60),
        fresh_per_hour=_num(env, "DTD_FRESH_PER_HOUR", int, 60),
        ask_slots=_num(env, "DTD_ASK_SLOTS", int, 2),
        git_sha=_git_sha(env),
    )
