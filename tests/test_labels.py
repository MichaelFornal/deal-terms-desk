import collections
import json
import re
from pathlib import Path

from facts.labels import HUMAN, MACHINE, is_machine_built, tier_label

NUM = re.compile(r"[-+]?\d+\.\d+")


def test_known_keys_are_classified():
    assert is_machine_built("m3_t_r6_report_recall_at_5") and is_machine_built("m3_tier_r1_machine_recall_at_5")
    assert is_machine_built("m2_r5_llm_report_recall_at_5") and is_machine_built("m4_cmp_model_haiku_tmachine_tune_agree")
    assert not is_machine_built("m3_tier_r1_human_recall_at_5") and not is_machine_built("m4_tokens_haiku_report_in_mean")
    assert tier_label("m2_r5_report_recall_at_5") == HUMAN and tier_label("m4_thuman_haiku_report_accuracy") == HUMAN
    assert tier_label("m4_refute_survival_rate") == MACHINE and tier_label("m4_gate_thuman_report_pass_rate") is None


def test_every_number_the_reports_print_as_machine_built_is_classified_so():
    """Cross-check against the committed M0-M4 reports. Take every number on a line that says machine-built, or
    under a heading ending "(machine-built)". When it is a float held by exactly one fact, that fact must be
    machine-built. "machine-built lexicon" describes R5's method, not the number beside it."""
    f = json.loads(Path("facts.json").read_text())
    by_value = collections.defaultdict(list)
    for k, v in f.items():
        if isinstance(v, float):
            by_value[v].append(k)
    unique = {v: ks[0] for v, ks in by_value.items() if len(ks) == 1}
    checked, wrong = 0, []
    for report in sorted(Path("docs").glob("m*/REPORT.md")):
        for section in re.split(r"\n(?=## )", report.read_text()):
            whole = "(machine-built)" in section.splitlines()[0]
            for line in section.splitlines():
                line = line.replace("machine-built lexicon", "")
                if not (whole or "machine-built" in line):
                    continue
                for n in NUM.findall(line):
                    key = unique.get(float(n))
                    if key is not None and n.lstrip("+") == str(f[key]):
                        checked += 1
                        if not is_machine_built(key):
                            wrong.append((report.parent.name, key))
    assert checked > 100 and wrong == []  # planning measured 159 checks, 0 wrong
