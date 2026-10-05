"""Checks that the live path is the measured one: prompts M4 answered, and R7n over the live bundle."""


def prompt_parity(items, answerer, records: dict[str, dict]) -> dict:
    """Re-prepare every item that has an answer record and compare its prompt's hash with the recorded one. A
    preparation that ends without a model call (which_deal, not_stated) has no hash, as its record has none. A
    record without an answer (a failed call) is skipped. Never calls the model."""
    checked, same, differ = 0, 0, []
    for item in items:
        rec = records.get(item.item_id)
        if not rec or rec.get("answer") is None:
            continue
        now = answerer.prepare(item.question, item.contract_id, item.choices).prompt_sha
        checked += 1
        if now == rec["answer"].get("prompt_sha"):
            same += 1
        else:
            differ.append(item.item_id)
    return {"checked": checked, "same": same, "differ": differ}


def r7n_parity(questions: list[tuple[str, str | None]], a, b, k: int = 10) -> dict:
    """R7n through two ladders (the live bundle and the deals.db the evals used): same hits in the same order, same
    shown context and same scope for every question, or the questions where they differ."""
    checked, same, differ = 0, 0, []
    for q, cid in questions:
        ra, rb = a.run("R7n", q, cid, k), b.run("R7n", q, cid, k)
        checked += 1
        if ([h.passage_id for h in ra.hits] == [h.passage_id for h in rb.hits] and ra.context == rb.context
                and ra.scope == rb.scope):
            same += 1
        else:
            differ.append({"question": q, "contract_id": cid})
    return {"checked": checked, "same": same, "differ": differ}
