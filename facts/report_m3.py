from evals.tmachine import FAMILIES

LABELS = {"equity_awards": "Employee equity awards", "termination_fee": "Termination (break-up) fee",
          "employee_benefits": "Employees' pay and benefits after the deal"}
RUNGS = (("t_r1", "R1 keyword"), ("t_r2", "R2 dense"), ("t_r3", "R3 hybrid"), ("t_r4", "R4 rerank"),
         ("t_r5", "R5 lexicon rewrite"), ("t_r6", "R6 definitions"))


def _v(x) -> str:
    return "n/a" if x is None else str(x)


def _ci(f, name) -> str:
    return f"{_v(f[name])} ({_v(f[name + '_lo'])} to {_v(f[name + '_hi'])})"


def _d(f, name) -> str:
    lo, hi = f[name + "_lo"], f[name + "_hi"]
    verdict = "helps" if lo > 0 else "hurts" if hi < 0 else "no measurable change"
    return f"{_v(f[name + '_delta'])} ({_v(lo)} to {_v(hi)}; {verdict})"


def _corpus(f) -> str:
    return (f"## Corpus\n\nOf the {f['m3_corpus_deals']} tech deals M0 found, {f['m3_corpus_kept']} agreements were "
            f"ingested. Left out because the document's own title is not a merger agreement: "
            f"{f['m3_corpus_excluded_not_merger']}. The deals index holds {f['m3_deals_deals']} agreements ({f['m3_deals_maud_deals']} from MAUD) "
            f"and {f['m3_deals_passages']} passages, {f['m3_tech_passages']} of them from the tech agreements, in "
            f"{f['m3_deals_index_bytes']} bytes.\n\n"
            f"{f['m3_corpus_amendments']} amendments are linked to their deals. {f['m3_deals_amendments_linked']} name "
            f"the sections they change in the explicit form (\"Section … is hereby amended\") and mark "
            f"{f['m3_deals_passages_superseded']} passages as superseded; an answer drawn from one of them shows the "
            f"amended text beside it. The other {f['m3_deals_amendments_unlinked']} are recorded but not linked to "
            f"sections, because nothing in them says which section they change in a form a program can trust. "
            f"{f['m3_deals_schedule_tagged']} passages refer to a disclosure letter or schedule, which is never filed.\n")


def _tmachine(f) -> str:
    rows = "\n".join(f"| {LABELS[fam]} | {f[f'm3_tm_{fam}_kept']} | {f[f'm3_tm_{fam}_absent']} | "
                     f"{f[f'm3_tm_{fam}_disagree']} | {f[f'm3_tm_{fam}_one_found']} | "
                     f"{_v(f[f'm3_tm_{fam}_agreement_rate'])} |" for fam in FAMILIES)
    return (f"## T-machine labels (machine-built)\n\nTwo independent passes ({f['m3_tm_model_a']} and "
            f"{f['m3_tm_model_b']}) each read the agreement's section outline, chose the sections to read, then quoted "
            f"the governing clause and answered. Neither pass sees a retrieval result, so the labels do not favour "
            f"any rung. An item is kept only when both passes found the clause and their quotes overlap or sit in the "
            f"same section. {f['m3_tm_complete']} of {f['m3_tm_contracts']} agreements are labelled, in "
            f"{f['m3_tm_calls']} model calls; {f['m3_tm_fallback_contracts']} had no usable section numbering and "
            f"were shown fixed-size chunks instead.\n\n"
            "| Family | Kept | Both passes: absent | Passes disagree | One pass only | Agreement rate (machine-built) |\n"
            "|---|---|---|---|---|---|\n" + rows + "\n\nItems both passes found absent are held for M4's "
            "abstention questions; they are not retrieval items.\n")


def _ladder(f) -> str:
    rows = "\n".join(
        f"| {label} | {_ci(f, f'm3_{r}_report_recall_at_5')} | "
        f"{'' if r == 't_r1' else _d(f, f'm3_cmp_{r}_vs_t_r1_recall_at_5')} | "
        f"{_d(f, f'm3_cmp_{r}_vs_prev_recall_at_5') if r not in ('t_r1', 't_r2') else ''} | "
        f"{f[f'm3_{r}_latency_ms_p95']} |" for r, label in RUNGS)
    fam_rows = "\n".join(f"| {label} | " + " | ".join(_v(f[f'm3_{r}_{fam}_recall_at_5']) for fam in FAMILIES) + " |"
                         for r, label in RUNGS)
    return (f"## The ladder on T-machine (machine-built)\n\nReport split: {f['m3_t_report_items']} machine-built "
            f"items from {f['m3_t_report_contracts']} tech agreements, each asked as a lay question naming the target. "
            f"Recall@5 with a bootstrap interval clustered by agreement; differences are paired.\n\n"
            "| Rung | recall@5 | vs R1 | vs previous rung | p95 latency (ms) |\n|---|---|---|---|---|\n" + rows +
            "\n\n| Rung | " + " | ".join(LABELS[fam] for fam in FAMILIES) + " |\n|---|---|---|---|\n" + fam_rows + "\n")


def _r7(f) -> str:
    return (f"## R7: finding the deal from the question\n\nCorpus-wide, over every agreement in the deals index, with "
            f"a hit from another agreement counted as a miss (machine-built items): R6 "
            f"{_ci(f, 'm3_t_r6_corpus_report_recall_at_5')}, R7 {_ci(f, 'm3_t_r7_corpus_report_recall_at_5')}; "
            f"difference {_d(f, 'm3_cmp_t_r7_vs_t_r6_corpus_recall_at_5')}. On the report split R7 resolved "
            f"{f['m3_r7_right']} questions to the right deal and {f['m3_r7_wrong']} to a wrong one. "
            f"{f['m3_r7_ambiguous']} named a company shared by several deals, so R7 searched everything rather than "
            f"guess, and {f['m3_r7_none']} named no company it knew.\n")


def _tier(f) -> str:
    rows = "\n".join(f"| {label} | {_v(f[f'm3_tier_{r[2:]}_human_recall_at_5'])} | "
                     f"{_v(f[f'm3_tier_{r[2:]}_machine_recall_at_5'])} |" for r, label in RUNGS)
    return (f"## Tier agreement (machine-built key against MAUD's lawyers)\n\nThe same two-pass procedure was run on "
            f"MAUD's own deal points in {f['m3_tier_contracts']} agreements from the report split "
            f"({f['m3_tier_items']} items), so those questions have two answer keys. Both passes agreed on "
            f"{f['m3_tier_kept']}. Of those, the machine-built span overlaps the lawyers' span in "
            f"{_ci(f, 'm3_tier_match_rate')} of items. Kendall's tau between the rung ordering under the lawyers' key "
            f"and under the machine-built key is {_v(f['m3_tier_tau'])} ({_v(f['m3_tier_tau_lo'])} to "
            f"{_v(f['m3_tier_tau_hi'])}). With six rungs, tau moves in coarse steps and its interval is wide, so both "
            f"orderings are shown: lawyers' key {f['m3_tier_human_order']}; machine-built key "
            f"{f['m3_tier_machine_order']}. This is evidence for or against trusting T-machine, not proof.\n\n"
            "| Rung | recall@5, lawyers' key | recall@5, machine-built key |\n|---|---|---|\n" + rows + "\n")


def _append(f) -> str:
    return (f"## The LLM rewrite, appended\n\nM2 compared the lexicon, which appends terms to the question, with an "
            f"LLM rewrite that replaced the question. Appending the same cached rewrite instead gives recall@5 "
            f"{_ci(f, 'm3_r5_llm_append_report_recall_at_5')} on T-human's report split: against R5 "
            f"{_d(f, 'm3_cmp_r5_llm_append_vs_r5_recall_at_5')}; against the replacing rewrite "
            f"{_d(f, 'm3_cmp_r5_llm_append_vs_r5_llm_recall_at_5')}.\n")


def render_m3(f) -> str:
    head = ("# M3: tech deals, deal scoping and the machine-built tier\n\nGenerated from `facts.json` by `dtd report`; "
            "do not edit by hand. Numbers marked machine-built come from model passes, not lawyers.\n")
    return "\n".join([head, _corpus(f), _tmachine(f), _ladder(f), _r7(f), _tier(f), _append(f),
                      "This is not legal advice.\n"])
