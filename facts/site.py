import html
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from facts.labels import HUMAN, MACHINE
from facts.m2 import CHAR_KS
from facts.report_m4 import GROUPS, LABELS

SITE = Path(__file__).resolve().parent.parent / "site"
TEMPLATES, STATIC = SITE / "templates", SITE / "static"
DISCLAIMER = "This is not legal advice."
PENDING = "pending"
NAV = (("/", "ask", "Ask"), ("/search.html", "search", "Search"), ("/results.html", "results", "Results"),
       ("/method.html", "method", "Method"))


@dataclass(frozen=True)
class K:
    """A fact shown as it is."""
    key: str


@dataclass(frozen=True)
class CI:
    """A fact with its interval: key (key_lo to key_hi)."""
    key: str


@dataclass(frozen=True)
class D:
    """A paired difference: key_delta (key_lo to key_hi; helps / hurts / no measurable change)."""
    key: str


@dataclass(frozen=True)
class V:
    """A difference stored under its own name with _lo and _hi, read like D."""
    key: str


@dataclass(frozen=True)
class A:
    """A link in page copy."""
    text: str
    href: str


@dataclass(frozen=True)
class Judge:
    """The sentence naming the judge model, worded by whether it also helped build the machine-built key."""


@dataclass(frozen=True)
class Row:
    cells: tuple
    tier: str | None = None  # the answer key behind this row's facts, when rows differ within a table


@dataclass(frozen=True)
class Table:
    id: str
    title: str
    tier: str | None  # the answer key behind every fact in the table, shown in the caption
    head: tuple  # (header text, tier or None) per column
    rows: tuple
    note: tuple = ()


class Facts:
    """Facts for the pages. A missing M5 fact (measured late in M5) renders as pending unless strict; any other
    missing fact is a bug and raises KeyError."""

    def __init__(self, facts, strict: bool = False):
        self.facts, self.strict = facts, strict

    def get(self, key: str):
        try:
            return self.facts[key]
        except KeyError:
            if key.startswith("m5_") and not self.strict:
                return None
            raise


def cell_keys(c) -> list[str]:
    if isinstance(c, K):
        return [c.key]
    if isinstance(c, (CI, V)):
        return [c.key, c.key + "_lo", c.key + "_hi"]
    if isinstance(c, D):
        return [c.key + "_delta", c.key + "_lo", c.key + "_hi"]
    return []


def _s(x) -> str:
    if x is None:
        return PENDING
    return ("yes" if x else "no") if isinstance(x, bool) else html.escape(str(x))


def _change(v, lo, hi) -> str:
    if v is None or lo is None or hi is None:
        return PENDING
    word = "helps" if lo > 0 else "hurts" if hi < 0 else "no measurable change"
    return f"{_s(v)} ({_s(lo)} to {_s(hi)}; {word})"


def render_cell(F: Facts, c) -> str:
    if isinstance(c, str):
        return html.escape(c)
    if isinstance(c, A):
        return f'<a href="{html.escape(c.href)}">{html.escape(c.text)}</a>'
    if isinstance(c, K):
        return _s(F.get(c.key))
    if isinstance(c, Judge):
        judge = F.get("m4_judge_model")
        if judge in (F.get("m3_tm_model_a"), F.get("m3_tm_model_b")):
            return (f"The judge model ({_s(judge)}) is one of those two models, so it judged answers against a key "
                    "it helped build; it may favour answers like its own, and its agreement rates should be read "
                    "with that in mind.")
        return f"A separate model ({_s(judge)}) judged answers against that key."
    if isinstance(c, CI):
        v = F.get(c.key)
        return PENDING if v is None else f"{_s(v)} ({_s(F.get(c.key + '_lo'))} to {_s(F.get(c.key + '_hi'))})"
    if isinstance(c, D):
        return _change(F.get(c.key + "_delta"), F.get(c.key + "_lo"), F.get(c.key + "_hi"))
    if isinstance(c, V):
        return _change(F.get(c.key), F.get(c.key + "_lo"), F.get(c.key + "_hi"))
    raise TypeError(f"not a cell: {c!r}")


def _tag(tier) -> str:
    return f' <span class="tier">{html.escape(tier)}</span>' if tier else ""


def render_table(F: Facts, t: Table) -> str:
    by_row = any(r.tier for r in t.rows)
    head = [html.escape(h) + _tag(tier) for h, tier in t.head] + (["Answer key"] if by_row else [])
    out = [f'<table id="{t.id}">', f"<caption>{html.escape(t.title)}{_tag(t.tier)}</caption>",
           "<thead><tr>" + "".join(f'<th scope="col">{h}</th>' for h in head) + "</tr></thead>", "<tbody>"]
    for r in t.rows:
        cells = [render_cell(F, c) for c in r.cells] + ([html.escape(r.tier or "")] if by_row else [])
        out.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    out.append("</tbody></table>")
    if t.note:
        out.append('<p class="note">' + "".join(render_cell(F, c) for c in t.note) + "</p>")
    return "\n".join(out)


RUNGS = ("r1", "r2", "r3", "r4", "r5", "r6")
ADDS = {"r1": "BM25 keyword search over section-aware passages",
        "r2": "Dense only: a local embedding model",
        "r3": "Hybrid: R1 and R2 fused by reciprocal rank",
        "r4": "R3 and a cross-encoder reranker",
        "r5": "R4 and a lexicon rewrite of lay words into contract words (the lexicon is machine-built)",
        "r6": "R5 and each passage's defined terms"}
# (label, slug in the M2 facts, slug in the M4 facts): the two milestones slugged MAUD's categories differently.
CATEGORIES = (("Conditions to closing", "conditions", "conditions_to_closing"),
              ("Deal protection", "deal_protection", "deal_protection_and_related_provisions"),
              ("General information", "general", "general_information"),
              ("Knowledge", "knowledge", "knowledge"),
              ("Material adverse effect", "mae", "material_adverse_effect"),
              ("Operating and efforts covenants", "covenants", "operating_and_efforts_covenant"),
              ("Remedies", "remedies", "remedies"))
FAMILY_ORDER = ("equity_awards", "termination_fee", "employee_benefits")
LBR = (("naive", "LegalBench-RAG: naive fixed-size chunks"),
       ("rcts", "LegalBench-RAG: recursive text splitter"),
       ("rcts_cohere", "LegalBench-RAG: recursive splitter and Cohere reranker"))
DASH = "—"


def _human_change(r):
    if r == "r1":
        return DASH
    return D("m2_cmp_r2_vs_r1_recall_at_5") if r == "r2" else D(f"m2_cmp_{r}_vs_prev_recall_at_5")


def _machine_change(r):
    if r == "r1":
        return DASH
    return D("m3_cmp_t_r2_vs_t_r1_recall_at_5") if r == "r2" else D(f"m3_cmp_t_{r}_vs_prev_recall_at_5")


def results_tables() -> tuple[Table, ...]:
    return (
        Table("ladder_human", "The retrieval ladder on MAUD's questions (report split)", HUMAN,
              (("Rung", None), ("What it adds", None), ("recall@5", None), ("recall@10", None), ("MRR@10", None),
               ("nDCG@10", None), ("recall@5 change from the rung above", None), ("ms p50", None),
               ("ms p95", None), ("Context tokens", None)),
              tuple(Row((r.upper(), ADDS[r], CI(f"m2_{r}_report_recall_at_5"), K(f"m2_{r}_report_recall_at_10"),
                         K(f"m2_{r}_report_mrr_at_10"), K(f"m2_{r}_report_ndcg_at_10"), _human_change(r),
                         K(f"m2_{r}_latency_ms_p50"), K(f"m2_{r}_latency_ms_p95"),
                         K(f"m2_{r}_context_tokens_mean"))) for r in RUNGS)
              + (Row(("R6n", "R6 without the reranker: the path the live desk answers from",
                      CI("m4_r6n_report_recall_at_5"), DASH, DASH, DASH, D("m4_cmp_r6n_vs_r6_recall_at_5"),
                      DASH, DASH, DASH)),
                 Row(("R6n, live index", "The same rung over the one index file the live desk reads",
                      CI("m5_bundle_r6n_report_recall_at_5"), DASH, DASH, DASH, DASH, DASH, DASH, DASH))),
              ("Report split: ", K("m2_report_items"), " questions from ", K("m2_report_contracts"),
               " agreements. Intervals are bootstrap intervals clustered by agreement; changes are paired. Timings "
               "were measured on the development machine; the live path's and the live server's are in the last "
               "table.")),
        Table("ladder_machine", "The retrieval ladder on the tech deals (report split)", MACHINE,
              (("Rung", None), ("What it adds", None), ("recall@5", None), ("MRR@10", None),
               ("recall@5 change from the rung above", None), ("ms p95", None), ("Context tokens", None)),
              tuple(Row((r.upper(), ADDS[r], CI(f"m3_t_{r}_report_recall_at_5"), K(f"m3_t_{r}_report_mrr_at_10"),
                         _machine_change(r), K(f"m3_t_{r}_latency_ms_p95"), K(f"m3_t_{r}_context_tokens_mean")))
                    for r in RUNGS)
              + (Row(("R6, all agreements", "No deal scoping: every agreement searched at once",
                      CI("m3_t_r6_corpus_report_recall_at_5"), K("m3_t_r6_corpus_report_mrr_at_10"), DASH,
                      K("m3_t_r6_corpus_latency_ms_p95"), K("m3_t_r6_corpus_context_tokens_mean"))),
                 Row(("R7, all agreements (first run)", "R6 inside the deal the question names",
                      CI("m3_t_r7_corpus_report_recall_at_5"), K("m3_t_r7_corpus_report_mrr_at_10"),
                      D("m3_cmp_t_r7_vs_t_r6_corpus_recall_at_5"), K("m3_t_r7_corpus_latency_ms_p95"),
                      K("m3_t_r7_corpus_context_tokens_mean"))),
                 Row(("R7, re-run for the answers, all agreements",
                      "The same R7 as re-run in the answer milestone: the rung the live path's change is paired against",
                      CI("m4_t_r7_corpus_report_recall_at_5"), DASH, DASH, DASH, DASH)),
                 Row(("R7n, all agreements", "R7 without the reranker: the live path",
                      CI("m4_t_r7n_corpus_report_recall_at_5"), DASH, D("m4_cmp_t_r7n_vs_t_r7_corpus_recall_at_5"),
                      DASH, DASH))),
              ("Report split: ", K("m3_t_report_items"), " machine-built questions about ",
               K("m3_t_report_contracts"), " tech agreements, each a lay question naming the company. Across all "
               "agreements, a passage from the wrong agreement counts as a miss.")),
        Table("side", "Side comparisons, not rungs (MAUD's questions, report split)", None,
              (("Comparison", None), ("recall@5", None), ("Change", None)),
              (Row(("Fixed-size chunks instead of section-aware passages, on R3",
                    CI("m2_r3_fixed_report_recall_at_5"), D("m2_cmp_r3_fixed_vs_r3_recall_at_5")), HUMAN),
               Row(("A live model rewriting the question instead of the lexicon, on R5",
                    CI("m2_r5_llm_report_recall_at_5"), D("m2_cmp_r5_llm_vs_r5_recall_at_5")), MACHINE))),
        Table("families_human", "By MAUD deal-point category (report split)", HUMAN,
              (("Category", None), ("R6 recall@5", None), ("R6 change from R1", None), ("Answer accuracy", None),
               ("Most-common-answer baseline", None)),
              tuple(Row((label, K(f"m2_r6_cat_{a}_recall_at_5"), D(f"m2_cmp_r6_vs_r1_cat_{a}_recall_at_5"),
                         CI(f"m4_thuman_haiku_{b}_accuracy"), CI(f"m4_thuman_haiku_{b}_baseline")))
                    for label, a, b in CATEGORIES)),
        Table("families_machine", "By lead question family (tech deals, report split)", MACHINE,
              (("Family", None), ("Kept items", None), ("Two-pass agreement rate", None),
               ("R6 recall@5 inside the deal", None), ("R7 recall@5 across all agreements", None),
               ("Answer agrees", None), ("Agrees or partly", None)),
              tuple(Row((LABELS[fam], K(f"m3_tm_{fam}_kept"), K(f"m3_tm_{fam}_agreement_rate"),
                         K(f"m3_t_r6_{fam}_recall_at_5"), K(f"m3_t_r7_corpus_{fam}_recall_at_5"),
                         K(f"m4_tmachine_haiku_{fam}_agree"), K(f"m4_tmachine_haiku_{fam}_agree_or_partial")))
                    for fam in FAMILY_ORDER)),
        Table("tier_agreement", "The rung order under the lawyers' key and under the machine-built key", None,
              (("Rung", None), ("recall@5, lawyers' key", HUMAN), ("recall@5, machine-built key", MACHINE)),
              tuple(Row((r.upper(), K(f"m3_tier_{r}_human_recall_at_5"), K(f"m3_tier_{r}_machine_recall_at_5")))
                    for r in RUNGS),
              ("The same two-pass procedure that built the tech-deal key was run on MAUD's own questions, so those "
               "questions have two keys.",)),
        Table("tier_summary", "How far the machine-built key can be trusted", MACHINE,
              (("Measure", None), ("Value", None)),
              (Row(("The machine span overlaps the lawyers' span", CI("m3_tier_match_rate"))),
               Row(("Kendall's tau between the two rung orders", CI("m3_tier_tau"))),
               Row(("Items where both machine passes agreed", K("m3_tier_kept"))),
               Row(("Items asked", K("m3_tier_items"))),
               Row(("Agreements", K("m3_tier_contracts")))),
              ("This is evidence for or against trusting the machine-built key, not proof.",)),
        Table("answers_human", "Answers to MAUD's questions (report split)", HUMAN,
              (("Measure", None), ("Value", None)),
              (Row(("The answerer picks MAUD's answer", CI("m4_thuman_haiku_report_accuracy"))),
               Row(("The same, counting only picks whose citations survived the gate",
                    CI("m4_thuman_haiku_report_accuracy_cited"))),
               Row(("Always picking each question's most common answer (baseline)",
                    CI("m4_thuman_haiku_report_baseline"))),
               Row(("Answerer minus baseline", V("m4_thuman_haiku_report_vs_baseline"))),
               Row(("Questions scored", K("m4_thuman_haiku_report_n"))),
               Row(("Questions asked", K("m4_thuman_haiku_report_items")))),
              ("Answer model: ", K("m4_answer_model"), ".")),
        Table("answers_machine", "Answers to the tech-deal questions (report split)", MACHINE,
              (("Measure", None), ("Value", None)),
              (Row(("A judge model finds the answer agrees with the kept machine answers",
                    CI("m4_tmachine_haiku_report_agree"))),
               Row(("Agrees or partly agrees", CI("m4_tmachine_haiku_report_agree_or_partial"))),
               Row(("The judge declined to rate", K("m4_tmachine_haiku_report_declined"))),
               Row(("Questions", K("m4_tmachine_haiku_report_items")))),
              ("Judge model: ", K("m4_judge_model"), ". The judge compares each answer with the two kept machine "
               "answers.")),
        Table("abstention", "Declining when the answer is not there", MACHINE,
              (("Group", None), ("Questions", None), ("Correct decline", None), ("False answer", None)),
              tuple(Row((GROUPS[g], K(f"m4_abstain_{g}_items"), K(f"m4_abstain_{g}_correct_rate"),
                         K(f"m4_abstain_{g}_false_answer_rate")))
                    for g in ("absent", "earnout", "schedule", "unknown_deal", "ambiguous_deal")),
              ("The right answer to each of these is a decline: \"not stated in this agreement\", \"in a schedule "
               "that was not filed\" or \"which agreement?\". The two name groups hold by construction: they test "
               "the deal resolver, which makes no model call.",)),
        Table("gate", "The citation gate", None,
              (("Questions", None), ("Claims returned", None), ("Claims kept", None), ("Share kept", None)),
              (Row(("MAUD's questions", K("m4_gate_thuman_report_returned"), K("m4_gate_thuman_report_kept"),
                    K("m4_gate_thuman_report_pass_rate"))),
               Row(("Tech-deal questions", K("m4_gate_tmachine_report_returned"), K("m4_gate_tmachine_report_kept"),
                    K("m4_gate_tmachine_report_pass_rate")))),
              ("A claim is kept only if its quote occurs word for word in the passage it cites. This check needs "
               "no answer key.",)),
        Table("refute", "A second model tries to refute each kept claim", MACHINE,
              (("Measure", None), ("Value", None)),
              (Row(("Share of claims it failed to refute", K("m4_refute_survival_rate"))),
               Row(("Claims checked", K("m4_refute_claims"))),
               Row(("Unreadable replies", K("m4_refute_unparsed"))))),
        Table("misses", "Why retrieval misses or answers go wrong", None,
              (("Class", None), ("Value", None), ("What it counts", None)),
              (Row(("All misses (R6, MAUD)", K("m2_fail_r6_misses"),
                    "Report-split questions whose gold span is not in the top five passages"), HUMAN),
               Row(("Wrong section", K("m2_fail_r6_wrong_section"), "The gold span sits in another section"), HUMAN),
               Row(("Right section, definition missing", K("m2_fail_r6_definition_missing"),
                    "The section was found but the definition it depends on was not"), HUMAN),
               Row(("Right section, wrong passage", K("m2_fail_r6_right_section_wrong_passage"),
                    "Another passage of the right section was returned"), HUMAN),
               Row(("Wrong deal", K("m3_r7_wrong"),
                    "Tech-deal questions that R7 scoped to the wrong agreement"), MACHINE),
               Row(("Answer in an unfiled schedule", K("m4_abstain_schedule_false_answer_rate"),
                    "Share answered anyway when the answer sits in a schedule that was not filed (weakest key)"),
                   MACHINE),
               Row(("Label disputed", CI("m2_machine_disputed_share"),
                    "Share of sampled misses where a model judged the first result to answer the question"),
                   MACHINE),
               Row(("Superseded text", "not classified",
                    "Amended passages are shown with their amendment; misses on them were not counted apart"))),
              ),
        Table("lbr", "Against LegalBench-RAG's published MAUD baselines (all agreements, character recall, percent)",
              None, (("Method", None),) + tuple((f"recall@{k}", None) for k in CHAR_KS),
              tuple(Row((label,) + tuple(K(f"m2_lbr_{m}_recall_at_{k}_pct") for k in CHAR_KS), "published")
                    for m, label in LBR)
              + (Row(("This project, R1",) + tuple(K(f"m2_r1_corpus_char_recall_at_{k}_pct") for k in CHAR_KS),
                     HUMAN),
                 Row(("This project, its best rung",)
                     + tuple(K(f"m2_best_corpus_char_recall_at_{k}_pct") for k in CHAR_KS), HUMAN)),
              ("Published figures: ", K("m2_lbr_source"), ". The setups differ (chunking, query wording, and k "
               "counted in their chunks against our passages), so read this as indicative, not head to head.")),
        Table("live", "The live desk", None, (("Measure", None), ("Value", None)),
              (Row(("Answer model", K("m5_price_model"))),
               Row(("Price per million input tokens, US dollars", K("m5_price_input_per_mtok"))),
               Row(("Price per million output tokens, US dollars", K("m5_price_output_per_mtok"))),
               Row(("Prices checked on", K("m5_price_checked"))),
               Row(("Hosting per month, US dollars", K("m5_hosting_usd_month"))),
               Row(("Model budget per month, US dollars", K("m5_model_cap_usd"))),
               Row(("Model budget per day, US dollars", K("m5_day_cap_usd"))),
               Row(("Input tokens per answer, mean", K("m5_api_tokens_in_mean"))),
               Row(("Output tokens per answer, mean", K("m5_api_tokens_out_mean"))),
               Row(("Cost per new answer, mean, US dollars", K("m5_cost_per_answer_mean"))),
               Row(("New answers the monthly budget covers", K("m5_answers_per_month"))),
               Row(("Live-path retrieval inside one agreement (R6n), development machine, ms p50",
                    K("m5_live_r6n_latency_ms_p50"))),
               Row(("Live-path retrieval inside one agreement (R6n), development machine, ms p95",
                    K("m5_live_r6n_latency_ms_p95"))),
               Row(("Live-path retrieval across all agreements (R7n), development machine, ms p95",
                    K("m5_live_t_r7n_corpus_latency_ms_p95"))),
               Row(("Search on the server, ms p50", K("m5_server_search_latency_ms_p50"))),
               Row(("Search on the server, ms p95", K("m5_server_search_latency_ms_p95"))),
               Row(("A new answer on the server, ms p50", K("m5_server_ask_fresh_latency_ms_p50"))),
               Row(("A new answer on the server, ms p95", K("m5_server_ask_fresh_latency_ms_p95"))),
               Row(("A cached answer on the server, ms p50", K("m5_server_ask_cached_latency_ms_p50"))),
               Row(("Peak memory of the service, MB", K("m5_server_rss_mb"))),
               Row(("Index file, bytes", K("m5_bundle_bytes"))),
               Row(("The cap trips: a new question is refused", K("m5_cap_trip_budget_reached"))),
               Row(("The cap trips: a cached answer is still shown", K("m5_cap_trip_budget_cached")))),
              ("Token counts come from a calibration sample of ", K("m5_calibration_n"),
               " questions sent to the API. Server timings leave out the network.")),
    )


SECTIONS = (("Retrieval", ("ladder_human", "ladder_machine", "side")),
            ("By question family", ("families_human", "families_machine")),
            ("Do the two answer keys agree?", ("tier_agreement", "tier_summary")),
            ("Answers", ("answers_human", "answers_machine", "abstention")),
            ("Citations", ("gate", "refute")),
            ("Why things go wrong", ("misses",)),
            ("Against the published baselines", ("lbr",)),
            ("The live desk", ("live",)))
RESULTS_INTRO = ("Every number on this page is generated from the project's measured facts. Numbers marked "
                 "human-labelled (MAUD) are scored against lawyers' labels; numbers marked machine-built come from "
                 "model passes, not lawyers.")

METHOD = (
    ("What this is", (
        ("Ask what a signed acquisition agreement says about employee stock, break-up fees, or employees' pay and "
         "benefits after the deal, and get the clause quoted from the contract with a link to its source text. ",
         DISCLAIMER, " The system can be wrong; every claim shows its source so you can check it."),
    )),
    ("The agreements", (
        ("Two sources. The first is MAUD, a dataset in which lawyers labelled ", K("maud_label_contracts"),
         " merger agreements with ", K("maud_question_types"), " question types in ", K("maud_label_rows_all"),
         " label rows. ", K("maud_label_contracts_with_text"), " of those agreements have published text; ",
         K("m3_deals_maud_deals"), " of them are in the live index after ", K("m3_deals_maud_duplicates"),
         " copies of tech deals were dropped as duplicates."),
        ("The second is technology-company acquisitions filed on EDGAR: the merger agreement attached to a "
         "current report, signed on or after ", K("m0_start"), ", whose target's industry code is in ",
         K("m0_sic_ranges"), ". They are chosen by that rule, not by hand: ", K("m3_corpus_kept"),
         " agreements. The live index holds ", K("m5_bundle_contracts"), " agreements in ", K("m5_bundle_passages"),
         " passages, cut on article and section boundaries."),
    )),
    ("Which numbers a person checked", (
        ("Numbers marked ", HUMAN, " are scored against the lawyers' labels in MAUD."),
        ("Numbers marked machine-built come from model passes, not lawyers. For the tech deals, two models (",
         K("m3_tm_model_a"), " and ", K("m3_tm_model_b"), ") each located the governing clause and stated the "
         "answer; only items where both agreed were kept. ", Judge(), " The lexicon that maps lay words to contract words was machine-built by ",
         K("m2_lexicon_model"), "."),
        ("To test whether the machine-built key can be trusted, the same two-pass procedure was run on MAUD's own "
         "questions, so those questions have two keys; the Results page shows how often they agree. That is "
         "evidence, not proof.",),
    )),
    ("What is not new", (
        ("Retrieval over MAUD is a published benchmark: ", K("m2_lbr_source"), ". This project does not claim the "
         "task. It claims a working, measured, deployed system on top of that benchmark, plus three question "
         "families its labels do not cover: employee equity awards, break-up fees, and employees' pay and "
         "benefits after the deal. The Results page compares against the published baselines."),
    )),
    ("How an answer is made", (
        ("The question is matched to one agreement by the company it names, or the one you pick. Inside that "
         "agreement, keyword search and a local embedding model (", K("m2_vec_model"), ") each rank passages and "
         "the two rankings are fused. Lay words are rewritten into the agreement's own vocabulary, and each "
         "passage is shown with the definitions it depends on."),
        ("The model (", K("m4_answer_model"), ") must return claims, each with a quote copied from a passage. A "
         "claim whose quote does not occur word for word in that passage is dropped; if none survives, the answer "
         "is \"not stated in this agreement\". A question that names no agreement, or several, gets \"which "
         "agreement?\" and no model call. Search shows the same ranked passages with no model call."),
    )),
    ("What it costs", (
        ("The desk runs under a hard monthly cap. Hosting costs ", K("m5_hosting_usd_month"), " US dollars a month; "
         "the model budget is the rest, ", K("m5_model_cap_usd"), ", with a daily ceiling of ",
         K("m5_day_cap_usd"), ". Prices were checked on ", K("m5_price_checked"), ": ",
         K("m5_price_input_per_mtok"), " US dollars per million input tokens and ", K("m5_price_output_per_mtok"),
         " per million output tokens. When the budget is spent, the desk shows cached answers only and says so. "
         "Search never spends model budget."),
    )),
    ("Stated limits", (
        ("The tech half is public-company acquisitions: small private exits rarely file their agreements.",),
        ("The tech-deal labels are machine-built. Two-pass agreement and the comparison with MAUD's lawyers are "
         "evidence, not proof.",),
        ("MAUD's agreements are older than many of the tech deals, follow one annotation scheme and are not "
         "tech-specific, so results on MAUD may not carry over to the tech deals; nothing here measures that "
         "directly.",),
        ("Lay questions are ambiguous. \"What happens to my options\" depends on vesting and on the agreement's own "
         "categories; the answer quotes the categories and does not pick one for you.",),
        ("The answer evaluations ran through the Claude command-line tool, not the API the live desk calls. A "
         "calibration sample of ", K("m5_calibration_n"), " questions run both ways agreed on the answer state in ",
         K("m5_calibration_state_agreement"), " of cases (", MACHINE, ": the two runs were compared with each other, "
         "not with lawyers' labels)."),
        ("Answer accuracy on MAUD was measured on an index of MAUD agreements alone. On the live index, which also "
         "holds the tech deals, the live rung's recall@5 on MAUD's questions is ",
         CI("m5_bundle_r6n_report_recall_at_5"), " (", HUMAN, ")."),
        ("Ladder timings were measured on the development machine; the live server's own timings are on the "
         "Results page.",),
        (DISCLAIMER,),
    )),
    ("What is logged", (
        ("The service logs one line per request: the endpoint, the outcome, the time taken and the tokens used. It "
         "does not log your address or your question. Answers are kept in a cache with the question that produced "
         "them, so a repeated question costs nothing. Rate limits count requests per address in memory only.",),
    )),
    ("Data and licences", (
        ("MAUD (the Merger Agreement Understanding Dataset) is by The Atticus Project, under the ",
         A("Creative Commons Attribution licence", "https://creativecommons.org/licenses/by/4.0/"), "; ",
         A("the dataset", "https://huggingface.co/datasets/theatticusproject/maud"), "."),
        ("Agreements from EDGAR: the SEC states that its content \"is considered public information and may be "
         "copied or further distributed by users of the web site without the SEC's permission\". This site quotes "
         "clauses and links to each filing; the source repository ships the fetch script and filing identifiers, "
         "not the documents.",),
        ("Source code: ", A("github.com/MichaelFornal/deal-terms-desk",
                            "https://github.com/MichaelFornal/deal-terms-desk"), "."),
    )),
)


def results_main(F: Facts) -> str:
    tables = {t.id: t for t in results_tables()}
    parts = ["<h1>Results</h1>", f'<p class="lede">{html.escape(RESULTS_INTRO)}</p>']
    for title, ids in SECTIONS:
        parts.append(f"<h2>{html.escape(title)}</h2>")
        parts += [render_table(F, tables[i]) for i in ids]
    return "\n".join(parts)


def method_main(F: Facts) -> str:
    out = ["<h1>Method</h1>"]
    for title, paragraphs in METHOD:
        out.append(f"<h2>{html.escape(title)}</h2>")
        out += ["<p>" + "".join(render_cell(F, c) for c in p) + "</p>" for p in paragraphs]
    return "\n".join(out)


def _read(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def _nav(current: str) -> str:
    return "".join(f'<a href="{href}"' + (' aria-current="page"' if page == current else "") + f">{text}</a>"
                   for href, page, text in NAV)


def _page(page: str, title: str, main: str) -> str:
    return (_read("base.html").replace("{{title}}", html.escape(title)).replace("{{page}}", page)
            .replace("{{nav}}", _nav(page)).replace("{{main}}", main))


def render_site(facts: dict, out: Path, examples: list[dict], strict: bool = False) -> list[Path]:
    """The four pages, the static files and the example questions. Every page is built before anything is written,
    so a missing fact leaves the previous site in place."""
    F, out = Facts(facts, strict), Path(out)
    pages = {"index.html": ("ask", "Ask", _read("index.html")), "search.html": ("search", "Search", _read("search.html")),
             "results.html": ("results", "Results", results_main(F)), "method.html": ("method", "Method", method_main(F))}
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, (page, title, main) in pages.items():
        (out / name).write_text(_page(page, title, main), encoding="utf-8")
        written.append(out / name)
    shutil.copytree(STATIC, out / "static", dirs_exist_ok=True)
    (out / "examples.json").write_text(json.dumps(examples, indent=2) + "\n", encoding="utf-8")
    return written + [out / "examples.json"]
