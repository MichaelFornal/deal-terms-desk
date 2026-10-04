import hashlib
import re
import time
from dataclasses import dataclass, field

from answer.blocks import Block, build_blocks
from answer.gate import check
from answer.prompt import render
from pipeline.m0 import _json_object
from retrieval.result import CONTEXT_K
from retrieval.scope import strip_alias

INPUT_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
MODEL_STATES = ("answered", "not_stated", "unfiled_schedule")


# After a quote inside a string: what makes it the closing quote. }, ] or a key colon (followed by a value start),
# or a comma then the start of the next key or element. Anything else means the quote is part of the text.
_CLOSES = re.compile(r'\s*(?:[}\]]|:\s*(?:["{\[]|(?:true|false|null)\b)|,\s+["{\[]|,["{\[]|\s*$)')


def _repair_inner_quotes(s: str) -> str:
    """Escape a double quote inside a JSON string value: models copy contract text such as (a "Term") into a string
    unescaped. A quote opens a string when none is open; inside one it closes it only when the next non-space
    character is one of , } ] : and is otherwise escaped. Works on the text from the first { to the last };
    an already-escaped quote stays."""
    a, b = s.find("{"), s.rfind("}")
    if a < 0 or b < a:
        return s
    body, out, i, inside = s[a:b + 1], [], 0, False
    while i < len(body):
        ch = body[i]
        if inside and ch == "\\" and i + 1 < len(body):
            out.append(body[i:i + 2])
            i += 2
            continue
        if ch == '"':
            if not inside:
                inside = True
            elif _CLOSES.match(body, i + 1):
                inside = False
            else:
                out.append("\\")
        out.append(ch)
        i += 1
    return "".join(out)


class ParseError(RuntimeError):
    """The model's reply held no usable answer object. An error, never an abstention."""


@dataclass(frozen=True)
class Claim:
    text: str
    quote: str
    ref: str
    passage_id: int
    contract_id: str
    section_path: str
    part: str
    amendment_no: int | None


@dataclass(frozen=True)
class Dropped:
    text: str
    quote: str
    ref: str
    reason: str


@dataclass(frozen=True)
class Answer:
    state: str
    claims: tuple[Claim, ...] = ()
    dropped: tuple[Dropped, ...] = ()
    amended: bool = False
    choice: str | None = None
    contract_id: str | None = None
    candidates: tuple[str, ...] = ()
    tokens_in: int = 0
    tokens_out: int = 0
    ms: float = 0.0
    retrieval_ms: float = 0.0
    prompt_sha: str | None = None
    usage: dict = field(default_factory=dict)  # the reply's raw usage, so the CLI's own share can be separated


@dataclass(frozen=True)
class Prepared:
    question: str
    contract_id: str
    blocks: list[Block]
    prompt: str
    prompt_sha: str
    choices: tuple[str, ...] = ()
    retrieval_ms: float = 0.0
    candidates: tuple[str, ...] = field(default=())


class Answerer:
    """The answer path: R6n inside a picked deal, or R7n's resolve-and-strip when the question names one."""

    def __init__(self, ladder, runner, model: str):
        self.ladder, self.runner, self.model = ladder, runner, model

    def prepare(self, question: str, contract_id: str | None = None, choices: tuple[str, ...] = ()) -> Prepared | Answer:
        t0 = time.perf_counter()
        q, candidates = question, ()
        if contract_id is None:
            scope = self.ladder.resolver.resolve(question) if self.ladder.resolver else None
            if scope is None or scope.contract_id is None:
                return Answer("which_deal", candidates=scope.candidates if scope else (),
                              retrieval_ms=(time.perf_counter() - t0) * 1000.0)
            contract_id, q, candidates = scope.contract_id, strip_alias(question, scope.alias), scope.candidates
        elif self.ladder.resolver is not None:
            # A picked deal: its own name says nothing about which clause to find, as on the resolved path.
            rows = self.ladder.conn.execute("SELECT alias FROM aliases WHERE contract_id = ?", (contract_id,))
            for (alias,) in sorted(rows, key=lambda r: -len(r[0])):
                q = strip_alias(q, alias)
        got = self.ladder.run("R6n", q, contract_id, CONTEXT_K)
        ms = (time.perf_counter() - t0) * 1000.0
        if not got.hits:
            return Answer("not_stated", contract_id=contract_id, retrieval_ms=ms)
        blocks = build_blocks(self.ladder, got.hits[:CONTEXT_K])
        prompt = render(question, blocks, tuple(choices))
        return Prepared(question, contract_id, blocks, prompt, hashlib.sha1(prompt.encode()).hexdigest()[:12],
                        tuple(choices), ms, candidates)

    def finish(self, p: Prepared, reply: dict, ms: float) -> Answer:
        result = reply.get("result") if isinstance(reply, dict) else None
        if not isinstance(result, str):
            raise ParseError("parse: reply has no text result")
        try:
            obj = _json_object(result, ("claims", "state"))
        except RuntimeError:
            try:
                obj = _json_object(_repair_inner_quotes(result), ("claims", "state"))
            except RuntimeError:
                raise ParseError(f"parse: no answer object in reply {result[:200]!r}") from None
        raw = obj.get("claims", [])
        if not isinstance(raw, list) or obj.get("state") not in MODEL_STATES:
            raise ParseError(f"parse: bad state or claims in {str(obj)[:200]!r}")
        kept, dropped = [], []
        for c in raw:
            c = c if isinstance(c, dict) else {}
            text, quote, ref = str(c.get("text", "")), str(c.get("quote", "")), str(c.get("ref", ""))
            got = check(quote, ref, p.blocks)
            if isinstance(got, str):
                dropped.append(Dropped(text, quote, ref, got))
            else:
                blk, part = got
                kept.append((blk, Claim(text, quote, blk.ref, blk.passage_id, blk.contract_id, blk.section_path,
                                        part.kind, part.amendment_no)))
        said = obj["state"]
        if said == "unfiled_schedule":
            state = "unfiled_schedule" if any(b.schedule_ref for b, _ in kept) else "not_stated"
        elif said == "answered" and kept:
            state = "answered"
        else:
            state = "not_stated"
        usage = reply.get("usage") or {}
        choice = obj.get("choice") if p.choices else None
        return Answer(state, tuple(c for _, c in kept), tuple(dropped),
                      state == "answered" and any(c.part == "amendment" for _, c in kept),
                      str(choice) if choice is not None else None, p.contract_id, p.candidates,
                      sum(usage.get(k, 0) for k in INPUT_KEYS), usage.get("output_tokens", 0), ms, p.retrieval_ms,
                      p.prompt_sha, dict(usage))

    def ask(self, question: str, contract_id: str | None = None, choices: tuple[str, ...] = ()) -> Answer:
        p = self.prepare(question, contract_id, choices)
        if isinstance(p, Answer):
            return p
        t0 = time.perf_counter()
        reply = self.runner(p.prompt, self.model)
        return self.finish(p, reply, (time.perf_counter() - t0) * 1000.0 + p.retrieval_ms)
