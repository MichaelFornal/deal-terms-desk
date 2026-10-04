import hashlib
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from evals.bootstrap import split_of
from evals.items import ANSWER_SUFFIX
from evals.maud_labels import LabelRow
from evals.tmachine import TEMPLATES
from retrieval.scope import Scope

ABSTAIN_GROUPS = ("absent", "absent_not_filed", "earnout", "unknown_deal", "ambiguous_deal", "schedule")
EARNOUT_TEMPLATE = ("Is any part of the price for {target} paid later as an earn-out, contingent value right or "
                    "milestone payment?")
NOT_FILED = re.compile(r"\b(?:isn't|is not|not) included\b", re.I)
SCHEDULE = re.compile(r"\b(?:disclosure\s+(?:letter|schedule)|schedule)\b", re.I)
NAME_NOISE = re.compile(r"\s*\([^)]*\)|\s*/[A-Z]{2,3}/")  # "(TICKER)", "(CIK …)", "/DE/"


@dataclass(frozen=True)
class AnswerItem:
    item_id: str
    set: str
    group: str
    split: str
    contract_id: str | None
    question: str
    choices: tuple[str, ...] = ()
    expected: str = ""
    meta: dict = field(default_factory=dict, compare=True, hash=False)


def write_items(path: Path, items: list[AnswerItem]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(json.dumps(asdict(i), sort_keys=True) + "\n" for i in items), encoding="utf-8")
    tmp.replace(path)


def read_items(path: Path) -> list[AnswerItem]:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            out.append(AnswerItem(**(d | {"choices": tuple(d["choices"])})))
    return out


def _question(text_type: str, question: str) -> str:
    """The MAUD label query: the question type plus the stem (as evals.items._query), once if they are the same."""
    stem = ANSWER_SUFFIX.sub("", question).strip()
    return text_type if stem == text_type.strip() else f"{text_type}: {stem}"


def thuman_items(rows: list[LabelRow], contract_ids: set[str], max_options: int = 10):
    """One item per (agreement, MAUD answer question). Choices are every answer MAUD gives that question."""
    options: dict[str, set[str]] = defaultdict(set)
    answers: dict[tuple[str, str], set[str]] = defaultdict(set)
    category: dict[tuple[str, str], str] = {}
    text_type: dict[str, str] = {}
    for r in rows:
        options[r.question].add(r.answer)
        answers[(r.contract_id, r.question)].add(r.answer)
        category[(r.contract_id, r.question)] = r.category
        text_type[r.question] = r.text_type
    wide = {q for q, o in options.items() if len(o) > max_options}
    ex = {"disputed": 0, "not_indexed": 0, "too_many_options": 0, "questions_too_many_options": len(wide)}
    items = []
    for (cid, q), got in sorted(answers.items()):
        if cid not in contract_ids:
            ex["not_indexed"] += 1
        elif q in wide:
            ex["too_many_options"] += 1
        elif len(got) > 1:
            ex["disputed"] += 1
        else:
            items.append(AnswerItem(f"{cid}|{q}", "thuman", category[(cid, q)], split_of(cid), cid,
                                    _question(text_type[q], q), tuple(sorted(options[q])), next(iter(got))))
    return items, ex


def tmachine_items(rows: list[dict]) -> list[AnswerItem]:
    return [AnswerItem(f"{r['contract_id']}|{r['family']}", "tmachine", r["family"], split_of(r["contract_id"]), None,
                       TEMPLATES[r["family"]].format(target=r["target"]), (), r["contract_id"],
                       {"a": r["a"]["answer"], "b": r["b"]["answer"], "gold": r["gold"]})
            for r in rows if r["status"] == "kept"]


def _stable(names, n):
    return sorted(names, key=lambda s: hashlib.sha1(s.encode()).hexdigest())[:n]


def _clean(name: str) -> str:
    return " ".join(NAME_NOISE.sub("", name).split())


def abstain_items(tm_rows, sample_rows, deals: dict, candidate_names, resolver, conn, n: int = 30):
    """The four abstention groups (spec §2). All deterministic; no model call and no sec.gov."""
    fams = sorted(TEMPLATES)
    out = []
    for r in tm_rows:
        if r["status"] != "absent":
            continue
        g = "absent_not_filed" if NOT_FILED.search(r["a"]["answer"] + " " + r["b"]["answer"]) else "absent"
        out.append(AnswerItem(f"{g}|{r['contract_id']}|{r['family']}", "abstain", g, split_of(r["contract_id"]),
                              r["contract_id"], TEMPLATES[r["family"]].format(target=r["target"]), (), "not_stated"))
    for s in sample_rows:
        cid = "edgar_" + s["adsh"].replace("-", "")
        if s["contingent_consideration"]["present"] or cid not in deals:
            continue
        out.append(AnswerItem(f"earnout|{cid}", "abstain", "earnout", split_of(cid), cid,
                              EARNOUT_TEMPLATE.format(target=deals[cid]["target"]), (), "not_stated"))
    unknown = []
    for name in dict.fromkeys(_clean(x) for x in candidate_names):
        q = TEMPLATES[fams[len(unknown) % len(fams)]].format(target=name)
        if name and resolver.resolve(q) == Scope(None, None, ()):
            unknown.append((name, q))
    for name, q in [u for u in unknown if u[0] in set(_stable([x for x, _ in unknown], n))]:
        out.append(AnswerItem(f"unknown_deal|{name}", "abstain", "unknown_deal", "report", None, q, (), "which_deal",
                              {"name": name}))
    amb = []
    for alias, in conn.execute("SELECT DISTINCT alias FROM aliases ORDER BY alias"):
        name = alias.title()
        q = TEMPLATES[fams[len(amb) % len(fams)]].format(target=name)
        s = resolver.resolve(q)
        if s.contract_id is None and len(s.candidates) > 1:
            amb.append((name, q))
    for name, q in [a for a in amb if a[0] in set(_stable([x for x, _ in amb], n))]:
        out.append(AnswerItem(f"ambiguous_deal|{name}", "abstain", "ambiguous_deal", "report", None, q, (),
                              "which_deal", {"name": name}))
    tagged = defaultdict(list)
    for cid, s0, e0 in conn.execute("SELECT p.contract_id, p.start_char, p.end_char FROM passage_tags t "
                                    "JOIN passages p USING(passage_id) WHERE t.tag = 'schedule_ref'"):
        tagged[cid].append((s0, e0))
    for r in tm_rows:
        if r["status"] != "kept" or not all(SCHEDULE.search(r[p]["answer"]) for p in ("a", "b")):
            continue
        if any(s0 < ge and gs < e0 for gs, ge in r["gold"] for s0, e0 in tagged[r["contract_id"]]):
            out.append(AnswerItem(f"schedule|{r['contract_id']}|{r['family']}", "abstain", "schedule",
                                  split_of(r["contract_id"]), r["contract_id"],
                                  TEMPLATES[r["family"]].format(target=r["target"]), (), "unfiled_schedule"))
    return out
