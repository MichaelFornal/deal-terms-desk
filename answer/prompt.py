import hashlib

TEMPLATE = """You answer questions about one signed merger agreement, using only the numbered passages below. This is not legal advice.

Question: {question}

Passages (each starts with its label; definitions and amending text belong to the passage above them):
{passages}
{choices}
Rules:
- Answer in two to four short claims. Each claim is one plain sentence a non-lawyer can follow.
- Every claim needs a quote copied word for word from one passage (no ellipses, no edits) and that passage's label.
- If the agreement uses its own categories (for example vested and unvested options), state each category; do not pick one for the reader.
- If the passages do not answer the question, use state "not_stated" and no claims.
- If a passage says the answer is set out in a disclosure letter or schedule that is not included, use state "unfiled_schedule" with one claim quoting that reference.

Reply with one JSON object and nothing else:
{{"state": "answered" | "not_stated" | "unfiled_schedule",{choice_key} "claims": [{{"text": "...", "quote": "...", "ref": "P1"}}]}}
"""
CHOICES = ("\nChoose exactly one of these answers and copy it into \"choice\" exactly as written:\n{options}\n"
           "Always fill \"choice\": pick the answer the passages best support, or the likeliest one if they are silent. "
           "\"state\" still says \"not_stated\" when the passages do not answer the question.\n")
TEMPLATE_SHA = hashlib.sha1((TEMPLATE + CHOICES).encode("utf-8")).hexdigest()[:12]


def _block(b) -> str:
    lines = [f"[{b.ref}] {b.section_path}", b.parts[0].text]
    defs = [p.text for p in b.parts if p.kind == "definition"]
    if defs:
        lines += ["Definitions used:"] + defs
    for p in b.parts:
        if p.kind == "amendment":
            lines += [f"[Amended by Amendment No. {p.amendment_no}]", p.text]
    return "\n".join(lines)


def render(question: str, blocks, choices: tuple[str, ...] = ()) -> str:
    opts = CHOICES.format(options="\n".join(f"- {c}" for c in choices)) if choices else ""
    return TEMPLATE.format(question=question.strip(), passages="\n\n".join(_block(b) for b in blocks),
                           choices=opts, choice_key=' "choice": "...",' if choices else "")
