from collections import Counter

# The states an example may come back in: each is an answer a visitor can read. Anything else (busy, error, a spent
# budget, which_deal) means the example chip would not show what it promises.
WARM_OK = frozenset({"answered", "not_stated", "unfiled_schedule"})


def warm(desk, examples: list[dict]) -> dict:
    """Ask every example through the live path, so the example chips never cost a visitor's call and the
    "budget reached" state still has answers to show. A rerun costs nothing: answered examples are cache hits."""
    states, cached = Counter(), 0
    for ex in examples:
        got = desk.ask(ex["question"], ex.get("deal"))
        states[got["state"]] += 1
        cached += got["served_from"] == "cache"
    return {"asked": len(examples), "cached": cached, "states": dict(sorted(states.items()))}


def warm_ok(result: dict) -> bool:
    """True when at least one example was asked and every one came back in an answering state."""
    return result["asked"] > 0 and set(result["states"]) <= WARM_OK
