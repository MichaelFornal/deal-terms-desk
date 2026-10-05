import re

MACHINE = "machine-built"
HUMAN = "human-labelled (MAUD)"

# Facts whose numbers come from model passes, not lawyers. Each carries "machine-built" wherever it is printed.
# Checked against the labels the committed reports already print (tests/test_labels.py).
# M5 labels follow where the correctness judgement comes from: a model (model-built keys, model judges,
# model-vs-model agreement) is machine-built; MAUD's key is human-labelled (MAUD); every other M5 fact is a plain
# measurement with no tier label (tokens, money, caps, hosting, latency, memory, bytes, sha, sample counts, the
# deterministic parity counts, the citation gate's pass rate, the cap-trip results).
MACHINE_BUILT_PREFIXES = (
    "m0_sample_", "m0_candidate_",
    "m2_lexicon_", "m2_llm_rewrite_", "m2_r5_llm_", "m2_cmp_r5_llm_", "m2_machine_disputed_",
    "m3_tm_", "m3_t_", "m3_cmp_t_", "m3_r5_llm_append_", "m3_cmp_r5_llm_append_", "m3_r7_",
    "m3_tier_kept", "m3_tier_match_", "m3_tier_tau", "m3_tier_machine_order",
    "m4_tmachine_", "m4_t_", "m4_cmp_t_", "m4_abstain_", "m4_refute_",
    "m5_calibration_state_agreement",  # the API's answer states against the command-line tool's: model vs model
)
MACHINE_BUILT_PATTERNS = (re.compile(r"m3_tier_r\d_machine_"), re.compile(r"m4_cmp_model_[a-z]+_tmachine_"))
# Facts scored against MAUD's lawyers' labels.
HUMAN_PREFIXES = ("r1_", "m2_r1_", "m2_r2_", "m2_r3_", "m2_r4_", "m2_r5_", "m2_r6_", "m2_cmp_", "m2_cat_", "m2_fail_",
                  "m2_best_corpus", "m2_report_", "m3_tier_human_order", "m4_thuman_", "m4_r6n_", "m4_cmp_r6n_",
                  "m4_cmp_model_haiku_thuman_", "m4_cmp_model_sonnet_thuman_", "m5_bundle_r6n_",
                  "m5_calibration_accuracy_")  # the calibration sample's T-human accuracy, API and command line
HUMAN_PATTERNS = (re.compile(r"m3_tier_r\d_human_"),)


def is_machine_built(key: str) -> bool:
    return key.startswith(MACHINE_BUILT_PREFIXES) or any(p.match(key) for p in MACHINE_BUILT_PATTERNS)


def tier_label(key: str) -> str | None:
    """MACHINE or HUMAN: the label a fact must be shown under. None when no answer key or judge decides it (sizes,
    timings, prices, counts, deterministic checks)."""
    if is_machine_built(key):
        return MACHINE
    if key.startswith(HUMAN_PREFIXES) or any(p.match(key) for p in HUMAN_PATTERNS):
        return HUMAN
    return None
