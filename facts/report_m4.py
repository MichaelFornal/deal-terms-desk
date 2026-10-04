from evals.answer_sets import ABSTAIN_GROUPS
from evals.tmachine import FAMILIES

LABELS = {"equity_awards": "Employee equity awards", "termination_fee": "Termination (break-up) fee",
          "employee_benefits": "Employees' pay and benefits after the deal"}
GROUPS = {"absent": "Lead question, both passes found no such clause",
          "earnout": "Earn-out question (one machine pass found none)",
          "unknown_deal": "A company name that matches no deal's aliases",
          "ambiguous_deal": "A name matching several deals",
          "schedule": "Answer sits in an unfiled schedule (weakest key)"}


def _v(x) -> str:
    return "n/a" if x is None else str(x)


def _ci(f, name) -> str:
    return f"{_v(f.get(name))} ({_v(f.get(name + '_lo'))} to {_v(f.get(name + '_hi'))})"


def _d(f, name) -> str:
    delta, lo, hi = f.get(name + "_delta"), f.get(name + "_lo"), f.get(name + "_hi")
    if delta is None or lo is None or hi is None:
        return f"{_v(delta)} ({_v(lo)} to {_v(hi)})"
    verdict = "helps" if lo > 0 else "hurts" if hi < 0 else "no measurable change"
    return f"{delta} ({lo} to {hi}; {verdict})"


def _verdict(f, name) -> str:
    """Like _d, for a CI block whose name is the fact itself (mean, _lo, _hi)."""
    m, lo, hi = f.get(name), f.get(name + "_lo"), f.get(name + "_hi")
    if m is None or lo is None or hi is None:
        return f"{_v(m)} ({_v(lo)} to {_v(hi)})"
    verdict = "helps" if lo > 0 else "hurts" if hi < 0 else "no measurable change"
    return f"{m} ({lo} to {hi}; {verdict})"


def _path(f) -> str:
    return ("## Answer path\n\nThe answerer retrieves with R7n: R6 (hybrid search, lexicon rewrite, definitions) "
            "without the reranker, which lowered recall in M2 and M3, inside the deal the question names or the "
            "visitor picks. A question that names no deal, or a name matching several, gets \"which agreement?\" "
            "and no model call.\n\n| Comparison (report split, recall@5) | Value | Change |\n|---|---|---|\n"
            f"| T-human, R6n vs R6 | {_ci(f, 'm4_r6n_report_recall_at_5')} | {_d(f, 'm4_cmp_r6n_vs_r6_recall_at_5')} |\n"
            f"| T-machine (machine-built), R6n vs R6 | {_ci(f, 'm4_t_r6n_report_recall_at_5')} | "
            f"{_d(f, 'm4_cmp_t_r6n_vs_t_r6_recall_at_5')} |\n"
            f"| T-machine (machine-built), corpus-wide R7n vs R7 | {_ci(f, 'm4_t_r7n_corpus_report_recall_at_5')} | "
            f"{_d(f, 'm4_cmp_t_r7n_vs_t_r7_corpus_recall_at_5')} |\n")


def _thuman(f) -> str:
    return ("## T-human answers\n\nOn MAUD's lawyer-labelled questions the answerer is shown the question's answer "
            "options and must pick one, with quoted support. Accuracy here is how often it picks the option the "
            "lawyers chose. The baseline always picks the option most common on the tune split.\n\n"
            f"Answered {_v(f.get('m4_thuman_haiku_report_n'))} of {_v(f.get('m4_thuman_haiku_report_items'))} items "
            f"on the report split; {_v(f.get('m4_thuman_haiku_report_missing'))} have no answer yet "
            f"({_v(f.get('m4_thuman_items'))} items built in all; {_v(f.get('m4_thuman_excluded_disputed'))} left out "
            f"because the label rows disagree, {_v(f.get('m4_thuman_excluded_too_many_options'))} because their "
            f"question has too many options to list ({_v(f.get('m4_thuman_questions_too_many_options'))} questions)).\n\n"
            "| | Accuracy |\n|---|---|\n"
            f"| Answerer ({_v(f.get('m4_answer_model'))}) | {_ci(f, 'm4_thuman_haiku_report_accuracy')} |\n"
            f"| Answerer, counting only picks whose citations survived the gate | "
            f"{_ci(f, 'm4_thuman_haiku_report_accuracy_cited')} |\n"
            f"| Majority-answer baseline | {_ci(f, 'm4_thuman_haiku_report_baseline')} |\n\n"
            f"Difference from the baseline: {_verdict(f, 'm4_thuman_haiku_report_vs_baseline')}.\n\n"
            f"Replies with an answer outside the options: {_v(f.get('m4_thuman_haiku_report_out_of_list'))}; "
            f"failed calls left out: {_v(f.get('m4_thuman_haiku_report_errors'))}.\n")


def _tmachine(f) -> str:
    rows = "\n".join(f"| {LABELS[fam]} | {_v(f.get(f'm4_tmachine_haiku_{fam}_agree'))} | "
                     f"{_v(f.get(f'm4_tmachine_haiku_{fam}_agree_or_partial'))} |" for fam in FAMILIES)
    return ("## T-machine answers (machine-built)\n\nOn the tech deals the question names the company, so the whole "
            f"live path runs. A judge ({_v(f.get('m4_judge_model'))}) compares each answer with the two kept "
            "machine-built answers. These numbers are machine-built: no lawyer checked them.\n\n"
            f"Agree: {_ci(f, 'm4_tmachine_haiku_report_agree')}; agree or partly: "
            f"{_ci(f, 'm4_tmachine_haiku_report_agree_or_partial')}; judged "
            f"{_v(f.get('m4_tmachine_haiku_report_n'))} of {_v(f.get('m4_tmachine_haiku_report_items'))} items. "
            f"Declined to answer: {_v(f.get('m4_tmachine_haiku_report_declined'))}; answered from the wrong "
            f"deal: {_v(f.get('m4_tmachine_haiku_report_wrong_deal'))}; judge reply unreadable: "
            f"{_v(f.get('m4_tmachine_haiku_report_judge_unparsed'))}; answered but not yet judged: "
            f"{_v(f.get('m4_tmachine_haiku_report_not_judged'))}; no answer yet: "
            f"{_v(f.get('m4_tmachine_haiku_report_missing'))}; failed calls: "
            f"{_v(f.get('m4_tmachine_haiku_report_errors'))}.\n\n"
            "| Family | Agree (machine-built) | Agree or partly (machine-built) |\n|---|---|---|\n" + rows + "\n")


def _abstain(f) -> str:
    rows = "\n".join(f"| {GROUPS[g]} | {_v(f.get(f'm4_abstain_{g}_n'))} | {_v(f.get(f'm4_abstain_{g}_missing'))} | "
                     f"{_v(f.get(f'm4_abstain_{g}_correct_rate'))} | "
                     f"{_v(f.get(f'm4_abstain_{g}_false_answer_rate'))} |" for g in ABSTAIN_GROUPS if g in GROUPS)
    return ("## Abstention\n\nQuestions whose right answer is a decline: \"not stated in this agreement\", \"in a "
            "schedule that was not filed\", or \"which agreement?\". The keys are machine-built.\n\n"
            "| Group | Items | Missing | Correct decline (machine-built key) | False answer (machine-built key) |\n"
            "|---|---|---|---|---|\n" + rows + "\n\n"
            "For the lead question, an answer also counts as correct when the judge finds it matches the two "
            f"machine passes; answered but not yet judged: {_v(f.get('m4_abstain_absent_not_judged'))}; judge reply "
            f"unreadable: {_v(f.get('m4_abstain_absent_judge_unparsed'))}.\n\n"
            "### Machine key contradicted by retrieval\n\nThese are kept out of the abstention figures above: the "
            "machine key says \"not stated\", but the key is likely wrong.\n\n"
            "| Group | Items | Answered share (machine-built key) |\n|---|---|---|\n"
            "| Lead question where the machine passes saw only the section's title, and the answerer found the "
            f"clause text | {_v(f.get('m4_abstain_absent_not_filed_n'))} | "
            f"{_v(f.get('m4_abstain_absent_not_filed_answered_rate'))} |\n")


def _citation(f) -> str:
    return ("## Citation accuracy\n\nEvery claim must quote its passage word for word; a claim whose quote is not "
            "found is dropped before anyone sees it.\n\n"
            f"Claims kept by the gate: T-human {_v(f.get('m4_gate_thuman_pass_rate'))} "
            f"({_v(f.get('m4_gate_thuman_kept'))} of {_v(f.get('m4_gate_thuman_returned'))}); T-machine "
            f"{_v(f.get('m4_gate_tmachine_pass_rate'))} ({_v(f.get('m4_gate_tmachine_kept'))} of "
            f"{_v(f.get('m4_gate_tmachine_returned'))}).\n\nA second model, shown only a kept claim and its quote and "
            f"told to refute it, failed to in {_v(f.get('m4_refute_survival_rate'))} of "
            f"{_v(f.get('m4_refute_claims'))} claims (machine-built; unreadable replies: "
            f"{_v(f.get('m4_refute_unparsed'))}).\n")


def _models(f) -> str:
    def row(s, name):
        return (f"| {name} | {_v(f.get(f'm4_cmp_model_{s}_thuman_tune_accuracy'))} | "
                f"{_v(f.get(f'm4_cmp_model_{s}_tmachine_tune_agree'))} | "
                f"{_v(f.get(f'm4_cmp_model_{s}_tokens_in_mean'))} | {_v(f.get(f'm4_cmp_model_{s}_tokens_out_mean'))} |")
    return ("## Model comparison\n\nThe same tune-split questions answered by two models; tokens are per called answer "
            "on the same items. The citation gate figures above are for the answer model only.\n\n"
            "| Model | T-human accuracy | T-machine agree (machine-built) | Tokens in | Tokens out |\n"
            "|---|---|---|---|---|\n"
            + row("haiku", "claude-haiku-4-5-20251001") + "\n" + row("sonnet", "claude-sonnet-5-5") + "\n\n"
            "Mean tokens per answer on the report split (answer model): "
            f"in {_v(f.get('m4_tokens_haiku_report_in_mean'))}, out {_v(f.get('m4_tokens_haiku_report_out_mean'))}. "
            "These price the live demo in M5.\n")


def render_m4(f) -> str:
    head = ("# M4: answers, the citation gate and abstention\n\nGenerated from `facts.json` by `dtd report`; do not "
            "edit by hand. Numbers marked machine-built come from model passes, not lawyers.\n")
    return "\n".join([head, _path(f), _thuman(f), _tmachine(f), _abstain(f), _citation(f), _models(f),
                      "This is not legal advice.\n"])
