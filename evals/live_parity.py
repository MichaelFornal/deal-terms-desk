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
