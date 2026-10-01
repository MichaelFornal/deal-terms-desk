from evals.failures import CLASSES, NOT_APPLICABLE
from evals.tune import GRID_RERANK_DEPTH
from facts.m2 import CHAR_KS, LADDER, LBR_METHODS, slug
from facts.queries import CATEGORIES
from retrieval.models import RERANKERS

ADDS = {
    "r1": "BM25 over section-aware passages",
    "r2": "Dense only ({model} in sqlite-vec)",
    "r3": "R1 and R2 fused by reciprocal rank",
    "r4": "R3 reranked by a cross-encoder",
    "r5": "R4 with the lexicon rewrite (machine-built lexicon)",
    "r6": "R5 with defined-term expansion",
}
CLASS_LABELS = {
    "definition_missing": "Right passage found, answer is in a definition it uses",
    "right_section_wrong_passage": "Right section, other passage of it",
    "unsectioned_gold": "Answer in text with no section heading",
    "wrong_section": "Wrong section",
}
LBR_LABELS = {"naive": "naive chunks", "rcts": "recursive splitter", "rcts_cohere": "recursive splitter, Cohere rerank"}


def _ci(f, p):
    return f"{f[p]} ({f[p + '_lo']} to {f[p + '_hi']})"


def _d(f, p):
    return f"{f[p + '_delta']:+} ({f[p + '_lo']:+} to {f[p + '_hi']:+})"


def _verdict(f, p):
    if f[p + "_lo"] > 0:
        return "helps"
    if f[p + "_hi"] < 0:
        return "hurts"
    return "no measurable change"


def _tokens(f, r):
    value = f[f"m2_{r}_context_tokens_mean"]
    return "not measured" if value is None else value


def _ladder(f):
    rows = []
    for i, r in enumerate(LADDER):
        p = f"m2_{r}_report"
        vs_r1 = "baseline" if r == "r1" else f"{_d(f, f'm2_cmp_{r}_vs_r1_recall_at_5')}, {_verdict(f, f'm2_cmp_{r}_vs_r1_recall_at_5')}"
        vs_prev = "" if i < 2 else f"{_d(f, f'm2_cmp_{r}_vs_prev_recall_at_5')}, {_verdict(f, f'm2_cmp_{r}_vs_prev_recall_at_5')}"
        rows.append(f"| {r.upper()} | {ADDS[r].format(model=f['m2_vec_model'])} | {_ci(f, p + '_recall_at_5')} | {f[p + '_recall_at_10']} "
                    f"| {f[p + '_mrr_at_10']} | {f[p + '_ndcg_at_10']} | {vs_r1} | {vs_prev} "
                    f"| {f[f'm2_{r}_latency_ms_p50']} / {f[f'm2_{r}_latency_ms_p95']} "
                    f"| {_tokens(f, r)} |")
    return "\n".join(rows)


def _families(f):
    rows = []
    for s, category in CATEGORIES.items():
        if not f[f"m2_cat_{s}_items"]:
            rows.append(f"| {category} | no report-split items |" + " |" * (len(LADDER) + 1))
            continue
        values = " | ".join(str(f[f"m2_{r}_cat_{s}_recall_at_5"]) for r in LADDER)
        note = "ceiling under R1: gains cannot show here" if f[f"m2_cat_{s}_ceiling"] else ""
        rows.append(f"| {category} | {f[f'm2_cat_{s}_items']} | {values} | {note} |")
    return "\n".join(rows)


def _family_deltas(f):
    rows = []
    for s, category in CATEGORIES.items():
        if not f[f"m2_cat_{s}_items"]:
            continue
        cells = " | ".join(_d(f, f"m2_cmp_{r}_vs_r1_cat_{s}_recall_at_5") for r in LADDER[1:])
        rows.append(f"| {category} | {cells} |")
    return "\n".join(rows)


def _failures(f):
    return "\n".join(
        f"| {r.upper()} | {f[f'm2_fail_{r}_misses']} | " + " | ".join(str(f[f"m2_fail_{r}_{c}"]) for c in CLASSES) + " |"
        for r in LADDER)


def _bake(f):
    return "\n".join(f"| {name} | {f[f'm2_bake_{slug(name)}_recall_at_5']} | {f[f'm2_bake_{slug(name)}_p95_ms']} |"
                     for name in RERANKERS)


def _depths(f):
    return "\n".join(f"| {d} | {f[f'm2_tune_depth_{d}_recall_at_5']} | {f[f'm2_tune_depth_{d}_p95_ms']} |"
                     for d in GRID_RERANK_DEPTH)


def _probe_clause(f):
    return "" if f["m2_tune_probe_qualified"] else "; no reranker qualified at the probe depth"


def _lbr(f, what):
    rows = []
    for k in CHAR_KS:
        theirs = " | ".join(str(f[f"m2_lbr_{m}_{what}_at_{k}_pct"]) for m in LBR_METHODS)
        rows.append(f"| {k} | {theirs} | {f[f'm2_r1_corpus_char_{what}_at_{k}_pct']} "
                    f"| {f[f'm2_best_corpus_char_{what}_at_{k}_pct']} |")
    return "\n".join(rows)


def _disputed(f) -> str:
    if not f["m2_machine_disputed_n"]:
        return ("**Label disputed (machine-built):** no sampled misses, so there is no estimate of how much of the "
                "miss rate is label incompleteness.")
    return (f"**Label disputed (machine-built):** on a sample of {f['m2_machine_disputed_n']} report-split items where "
            f"{f['m2_machine_disputed_rung']}'s first result was not gold, `{f['m2_machine_disputed_model']}` judged "
            f"that the first result also answers the question in {_ci(f, 'm2_machine_disputed_share')} of cases, "
            "counting a judgement only when its supporting quote occurs verbatim in that result. This estimates how "
            "much of the miss rate is label incompleteness; it relabels nothing.")


def render_m2(f) -> str:
    rung_heads = " | ".join(r.upper() for r in LADDER)
    delta_heads = " | ".join(f"{r.upper()} minus R1" for r in LADDER[1:])
    class_heads = " | ".join(CLASS_LABELS[c] for c in CLASSES)
    lbr_heads = " | ".join(f"LegalBench-RAG, {LBR_LABELS[m]}" for m in LBR_METHODS)
    not_applicable = "\n".join(f"- {name.replace('_', ' ')}: {why}." for name, why in NOT_APPLICABLE.items())
    return f"""# M2 report: the retrieval ladder on MAUD

Generated by `dtd report` from `facts.json`. Do not edit by hand. This is not legal advice.

## How to read this

- Human-labelled (MAUD) items only. Headline numbers are on the report split ({f['m2_report_contracts']} agreements, {f['m2_report_items']} items); settings were chosen on the tune split alone ({f['m2_tuned_contracts']} agreements, {f['m2_tuned_items']} items).
- **The queries are MAUD's label names**, one of {f['m2_deal_points']} deal points plus its question names, less their "Answer" suffixes. They are already contract vocabulary. R5 rewrites everyday words into contract vocabulary, so it is measured against R1 on these same label-name queries, and a small or zero R5 gain here says little about lay questions; those arrive with M3's machine-built set.
- Every gain is a paired difference on the same items, with a 95% interval from resampling agreements. "Helps" means the interval is above zero, "hurts" below it, and anything else is "no measurable change".
- Latency is per query on the development machine (load average {f['m2_r1_load_avg']} when R1 ran; each rung's own is in `facts.json`). M5 remeasures on the server. Context tokens: the text a model would be shown for the top five passages, counted with the embedding model's tokenizer as a stand-in; M4 measures the answering model's own count.

## The ladder (report split)

| Rung | Adds | recall@5 | recall@10 | MRR@10 | nDCG@10 | recall@5 minus R1 | recall@5 minus previous rung | p50 / p95 ms | Context tokens |
|---|---|---|---|---|---|---|---|---|---|
{_ladder(f)}

R4 uses `{f['m2_tuned_reranker']}` on the top {f['m2_tuned_rerank_depth']} fused passages; fusion takes {f['m2_tuned_depth']} from each leg with k0 = {f['m2_tuned_rrf_k0']}.

## Per question family (recall@5, report split)

Read gains here, not only on average. M1's per-family table was on all agreements; this one is on the report split for every rung.

| Family | Items | {rung_heads} | Note |
|---|---|{"---|" * len(LADDER)}---|
{_families(f)}

| Family | {delta_heads} |
|---|{"---|" * (len(LADDER) - 1)}
{_family_deltas(f)}

## Tuning (tune split only)

Rule: fusion by highest tune recall@5; then the reranker and its depth by highest tune recall@5 among settings whose p95 latency is at most {f['m2_tune_max_p95_ms']} ms on the development machine. Live path within the limit at the chosen depth ({f['m2_tuned_rerank_depth']}): {'yes' if f['m2_tuned_live_path_ok'] else 'no'}.

| Reranker | Tune recall@5 | Tune p95 ms |
|---|---|---|
{_bake(f)}

Chosen reranker by rerank depth (`{f['m2_tuned_reranker']}`):

| Rerank depth | Tune recall@5 | Tune p95 ms |
|---|---|---|
{_depths(f)}

For reference, the hybrid without a reranker (R3) scored {f['m2_tune_r3_recall_at_5']} on the tune split (p95 {f['m2_tune_r3_p95_ms']} ms). The rule chooses among rerankers only{_probe_clause(f)}.

## Chunking: section-aware versus fixed-size (on R3)

Fixed-size chunks are {f['m2_fixed_size_chars']} characters, the median section-aware passage, so that length does not decide the comparison ({f['m2_fixed_passages_indexed']} fixed-size passages indexed). Fixed-size R3 recall@5: {_ci(f, 'm2_r3_fixed_report_recall_at_5')}. Fixed minus section-aware: {_d(f, 'm2_cmp_r3_fixed_vs_r3_recall_at_5')}, {_verdict(f, 'm2_cmp_r3_fixed_vs_r3_recall_at_5')}.

## Query rewriting: the lexicon versus a live LLM (offline comparison, machine-built rewrites)

The lexicon ({f['m2_lexicon_entries']} entries, machine-built by `{f['m2_lexicon_model']}` from defined terms in tune-split agreements, never shown an eval query) costs no model call. The LLM rewrite (machine-built) used `{f['m2_llm_rewrite_model']}` on {f['m2_llm_rewrite_queries']} distinct queries, at a mean of {f['m2_llm_rewrite_input_tokens_mean']} input and {f['m2_llm_rewrite_output_tokens_mean']} output tokens per query, measured through `claude -p` (includes the CLI's own prompt and any thinking); a direct API call would cost less; its latency includes the model's reported API time (p50 / p95 {f['m2_r5_llm_latency_ms_p50']} / {f['m2_r5_llm_latency_ms_p95']} ms). LLM rewrite (machine-built) minus lexicon, recall@5: {_d(f, 'm2_cmp_r5_llm_vs_r5_recall_at_5')}, {_verdict(f, 'm2_cmp_r5_llm_vs_r5_recall_at_5')}.

## Why retrieval misses (report split, gold spans not touched by the top five)

| Rung | Misses | {class_heads} |
|---|---|{"---|" * len(CLASSES)}
{_failures(f)}

Under R6 a definition-class miss is one where the definition was shown to the model but the retrieval metric, which credits passages only, does not count it.

Not applicable to these items:
{not_applicable}

{_disputed(f)}

## Index

Vectors: {f['m2_vec_passages']} passages embedded with `{f['m2_vec_model']}`; {f['m2_vec_truncated']} were longer than the model's window and embedded truncated. Definitions attached per passage, mean: {f['m2_defs_per_passage_mean']}; share of passages with at least one: {f['m2_passages_with_defs_share']}. Index file: {f['m2_index_bytes']} bytes.

## Against LegalBench-RAG

The numbers are **not directly comparable**. LegalBench-RAG ({f['m2_lbr_source']}) searches the whole corpus with questions that name the document, scores precision and recall over characters, and uses short fixed-size or recursive chunks. This project's headline searches one agreement with MAUD's label names and counts a gold span found when a retrieved passage overlaps it. To narrow the gap, R1 and the best rung ({f['m2_best_corpus_rung']}) were also run over the whole corpus and scored over characters, below; the queries and the chunks still differ. Their figures are in percent as printed (Tables {f['m2_lbr_naive_table']}, {f['m2_lbr_rcts_table']} and {f['m2_lbr_rcts_cohere_table']}); ours are in percent over all agreements, which includes the tune split the settings were chosen on.

Recall over characters, top k:

| k | {lbr_heads} | This project, R1, whole corpus | This project, best rung, whole corpus |
|---|---|---|---|---|---|
{_lbr(f, 'recall')}

Precision over characters, top k:

| k | {lbr_heads} | This project, R1, whole corpus | This project, best rung, whole corpus |
|---|---|---|---|---|---|
{_lbr(f, 'precision')}

Our own metric over the whole corpus, recall@5: R1 {f['m2_r1_corpus_recall_at_5']}, best rung {f['m2_best_corpus_recall_at_5']}.
"""
