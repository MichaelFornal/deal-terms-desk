from collections import Counter


def warm(desk, examples: list[dict]) -> dict:
    """Ask every example through the live path, so the example chips never cost a visitor's call and the
    "budget reached" state still has answers to show. A rerun costs nothing: answered examples are cache hits."""
    states, cached = Counter(), 0
    for ex in examples:
        got = desk.ask(ex["question"], ex.get("deal"))
        states[got["state"]] += 1
        cached += got["served_from"] == "cache"
    return {"asked": len(examples), "cached": cached, "states": dict(sorted(states.items()))}
