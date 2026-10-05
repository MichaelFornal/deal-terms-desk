import re

MACHINE = "machine-built"
HUMAN = "human-labelled (MAUD)"

# Facts whose numbers come from model passes, not lawyers. Each carries "machine-built" wherever it is printed.
# Checked against the labels the committed M0-M4 reports already print (tests/test_labels.py).
MACHINE_BUILT_PREFIXES = (
    "m0_sample_", "m0_candidate_",
    "m2_lexicon_", "m2_llm_rewrite_", "m2_r5_llm_", "m2_cmp_r5_llm_", "m2_machine_disputed_",
    "m3_tm_", "m3_t_", "m3_cmp_t_", "m3_r5_llm_append_", "m3_cmp_r5_llm_append_", "m3_r7_",
    "m3_tier_kept", "m3_tier_match_", "m3_tier_tau", "m3_tier_machine_order",
    "m4_tmachine_", "m4_t_", "m4_cmp_t_", "m4_abstain_", "m4_refute_",
)
MACHINE_BUILT_PATTERNS = (re.compile(r"m3_tier_r\d_machine_"), re.compile(r"m4_cmp_model_[a-z]+_tmachine_"))
# Facts scored against MAUD's lawyers' labels.
HUMAN_PREFIXES = ("r1_", "m2_r1_", "m2_r2_", "m2_r3_", "m2_r4_", "m2_r5_", "m2_r6_", "m2_cmp_", "m2_cat_", "m2_fail_",
                  "m2_best_corpus", "m2_report_", "m3_tier_human_order", "m4_thuman_", "m4_r6n_", "m4_cmp_r6n_",
                  "m4_cmp_model_haiku_thuman_", "m4_cmp_model_sonnet_thuman_", "m5_bundle_r6n_")
HUMAN_PATTERNS = (re.compile(r"m3_tier_r\d_human_"),)


def is_machine_built(key: str) -> bool:
    return key.startswith(MACHINE_BUILT_PREFIXES) or any(p.match(key) for p in MACHINE_BUILT_PATTERNS)


def tier_label(key: str) -> str | None:
    """The label a fact must be shown under, or None when it depends on no answer key (sizes, timings, prices)."""
    if is_machine_built(key):
        return MACHINE
    if key.startswith(HUMAN_PREFIXES) or any(p.match(key) for p in HUMAN_PATTERNS):
        return HUMAN
    return None
