from evals.answer_score import score
from evals.answer_sets import AnswerItem

M = "haiku"


def th(cid, q, exp, split):
    return AnswerItem(f"{cid}|{q}", "thuman", "Cat", split, cid, q, ("A", "B"), exp)


def ans(state="answered", choice=None, cid="c", claims=1, dropped=0, tin=100, tout=10):
    return {"answer": {"state": state, "choice": choice, "contract_id": cid, "tokens_in": tin, "tokens_out": tout,
                       "claims": [{"text": "t", "quote": "q"}] * claims,
                       "dropped": [{"reason": "quote_not_found"}] * dropped}, "error": None}


def test_thuman_accuracy_baseline_out_of_list_and_errors():
    items = [th("c1", "Q", "A", "tune"), th("c2", "Q", "A", "tune"), th("c3", "Q", "B", "tune"),
             th("c4", "Q", "A", "report"), th("c5", "Q", "B", "report"), th("c6", "Q", "A", "report"),
             th("c7", "Q", "A", "report")]
    answers = {("thuman", M): {"c4|Q": ans(choice="A"), "c5|Q": ans(choice="B"), "c6|Q": ans(choice="Z"),
                               "c7|Q": {"answer": None, "error": "parse: x"}}}
    s = score({"thuman": items}, answers, {}, {}, (M,), n_boot=50)
    r = s["thuman"][M]["report"]
    assert r["n"] == 3 and abs(r["accuracy"]["mean"] - 2 / 3) < 1e-9
    assert abs(r["baseline"]["mean"] - 2 / 3) < 1e-9  # tune majority "A": right on c4, c6; wrong on c5
    assert r["out_of_list"] == 1 and r["errors"] == 1
    assert s["gate"]["thuman"]["report"]["pass_rate"] == 1.0 and s["tokens"][M]["thuman"]["report"]["in_mean"] == 100


def test_tmachine_judge_and_abstention():
    tm = [AnswerItem(f"edgar_{k}|termination_fee", "tmachine", "termination_fee", "report", None, "q", (),
                     f"edgar_{k}", {}) for k in range(4)]
    answers = {("tmachine", M): {tm[0].item_id: ans(cid="edgar_0"), tm[1].item_id: ans(cid="edgar_9"),
                                 tm[2].item_id: ans(state="not_stated", cid="edgar_2"),
                                 tm[3].item_id: ans(cid="edgar_3", claims=1, dropped=1)}}
    judge = {M: {tm[0].item_id: {"verdict": "agree"}, tm[1].item_id: {"verdict": "partial"},
                 tm[2].item_id: {"verdict": "declined"}, tm[3].item_id: {"verdict": None}}}
    ab = [AnswerItem("x1", "abstain", "earnout", "report", "c", "q", (), "not_stated"),
          AnswerItem("x2", "abstain", "earnout", "report", "c", "q", (), "not_stated"),
          AnswerItem("x3", "abstain", "unknown_deal", "report", None, "q", (), "which_deal")]
    answers[("abstain", M)] = {"x1": ans(state="not_stated"), "x2": ans(), "x3": ans(state="which_deal")}
    refute = {"a#0": {"refuted": False}, "a#1": {"refuted": True}, "b#0": {"refuted": None}}
    s = score({"tmachine": tm, "abstain": ab}, answers, judge, refute, (M,), n_boot=50)
    t = s["tmachine"][M]["report"]
    assert t["n"] == 3 and abs(t["agree"]["mean"] - 1 / 3) < 1e-9 and abs(t["agree_or_partial"]["mean"] - 2 / 3) < 1e-9
    assert t["declined"] == 1 and t["judge_unparsed"] == 1 and t["wrong_deal"] == 1
    e = s["abstain"]["earnout"]
    assert e["n"] == 2 and e["correct"] == 1 and e["false_answer"] == 1 and e["correct_rate"] == 0.5
    assert s["abstain"]["unknown_deal"]["correct"] == 1
    assert s["gate"]["tmachine"]["report"]["returned"] == 5 and s["gate"]["tmachine"]["report"]["kept"] == 4
    assert s["refute"] == {"claims": 3, "not_refuted": 1, "unparsed": 1, "survival_rate": 0.5}


def test_missing_records_and_cited_and_vs_baseline():
    items = [th("c1", "Q", "A", "tune"), th("c4", "Q", "A", "report"), th("c5", "Q", "B", "report"),
             th("c6", "Q", "A", "report"), th("c7", "Q", "A", "report")]
    answers = {("thuman", M): {"c4|Q": ans(choice="A"), "c5|Q": ans(choice="B", state="not_stated"),
                               "c6|Q": ans(choice="B")}}
    r = score({"thuman": items}, answers, {}, {}, (M,), n_boot=50)["thuman"][M]["report"]
    assert r["items"] == 4 and r["missing"] == 1 and r["n"] == 3
    assert abs(r["accuracy"]["mean"] - 2 / 3) < 1e-9 and abs(r["accuracy_cited"]["mean"] - 1 / 3) < 1e-9
    # baseline "A": diffs c4 1-1=0, c5 1-0=1, c6 0-1=-1
    assert abs(r["vs_baseline"]["mean"]) < 1e-9 and r["vs_baseline"]["n_items"] == 3
    assert abs(r["by_category"]["Cat"]["accuracy_cited"]["mean"] - 1 / 3) < 1e-9


def test_not_judged_vs_unparsed_and_abstain_missing():
    tm = [AnswerItem(f"edgar_{k}|f", "tmachine", "f", "report", None, "q", (), f"edgar_{k}", {}) for k in range(4)]
    answers = {("tmachine", M): {t.item_id: ans(cid=t.expected) for t in tm[:3]}}
    judge = {M: {tm[0].item_id: {"verdict": "agree"}, tm[1].item_id: {"verdict": None}}}
    ab = [AnswerItem(f"x{k}", "abstain", "earnout", "report", "c", "q", (), "not_stated") for k in range(3)]
    answers[("abstain", M)] = {"x0": ans(state="not_stated")}
    s = score({"tmachine": tm, "abstain": ab}, answers, judge, {}, (M,), n_boot=50)
    t = s["tmachine"][M]["report"]
    assert t["n"] == 1 and t["judge_unparsed"] == 1 and t["not_judged"] == 1
    assert t["items"] == 4 and t["missing"] == 1
    assert s["abstain"]["earnout"]["items"] == 3 and s["abstain"]["earnout"]["missing"] == 2


def test_choice_scoring_folds_typographic_quotes_and_none_is_wrong():
    opts = ("“Publicly disclosed” applies", "Other")
    items = [AnswerItem(f"c{k}|Q", "thuman", "Cat", "report", f"c{k}", "Q", opts, opts[0]) for k in range(2)]
    answers = {("thuman", M): {"c0|Q": ans(choice='"Publicly  disclosed" applies'), "c1|Q": ans(choice=None)}}
    r = score({"thuman": items}, answers, {}, {}, (M,), n_boot=50)["thuman"][M]["report"]
    assert r["n"] == 2 and abs(r["accuracy"]["mean"] - 0.5) < 1e-9 and abs(r["accuracy_cited"]["mean"] - 0.5) < 1e-9
    assert r["out_of_list"] == 1  # only the None choice is outside the options


def test_absent_group_is_judged_and_other_groups_keep_the_state_rule():
    ab = [AnswerItem(f"a{k}", "abstain", "absent", "report", "c", "q", (), "not_stated", {"a": "x", "b": "y"})
          for k in range(6)]
    ab.append(AnswerItem("nf", "abstain", "absent_not_filed", "report", "c", "q", (), "not_stated"))
    answers = {("abstain", M): {"a0": ans(), "a1": ans(), "a2": ans(), "a3": ans(state="not_stated"), "a4": ans(),
                                "a5": ans(state="unfiled_schedule"), "nf": ans()}}
    judge = {"abstain:" + M: {"a0": {"verdict": "agree"}, "a1": {"verdict": "disagree"}, "a4": {"verdict": None},
                              "a5": {"verdict": "declined"}},
             "nf": {"nf": {"verdict": "agree"}}}
    s = score({"abstain": ab}, answers, judge, {}, (M,), n_boot=50)["abstain"]
    a = s["absent"]
    assert (a["correct"], a["false_answer"], a["other"]) == (2, 1, 1)  # a0 agree, a3 not_stated; a1; a5
    assert a["not_judged"] == 1 and a["judge_unparsed"] == 1 and a["n"] == 4 and a["correct_rate"] == 0.5
    nf = s["absent_not_filed"]
    assert nf["false_answer"] == 1 and nf["n"] == 1 and nf["not_judged"] == 0  # plain state rule, no judge


def test_tokens_are_split_by_item_split_and_count_only_called_answers():
    items = [th("c1", "Q", "A", "tune"), th("c2", "Q", "A", "tune"), th("c3", "Q", "A", "report")]
    answers = {("thuman", M): {"c1|Q": ans(choice="A", tin=100, tout=10), "c2|Q": ans(choice="A", tin=300, tout=30),
                               "c3|Q": ans(choice="A", tin=50, tout=5)}}
    t = score({"thuman": items}, answers, {}, {}, (M,), n_boot=50)["tokens"][M]["thuman"]
    assert t == {"tune": {"in_mean": 200.0, "out_mean": 20.0, "n": 2}, "report": {"in_mean": 50.0, "out_mean": 5.0, "n": 1}}
    answers[("thuman", M)]["c3|Q"] = ans(choice="A", tin=0, tout=0)  # no model call (e.g. no hits)
    t = score({"thuman": items}, answers, {}, {}, (M,), n_boot=50)["tokens"][M]["thuman"]
    assert set(t) == {"tune"}


def test_gate_is_counted_per_split():
    items = [th("c1", "Q", "A", "tune"), th("c2", "Q", "A", "report"), th("c3", "Q", "A", "report")]
    answers = {("thuman", M): {"c1|Q": ans(choice="A", claims=2, dropped=2), "c2|Q": ans(choice="A", claims=1),
                               "c3|Q": ans(choice="A", claims=1, dropped=1), "zz|Q": ans(claims=5)}}
    g = score({"thuman": items}, answers, {}, {}, (M,), n_boot=50)["gate"]["thuman"]
    assert g["tune"] == {"returned": 4, "kept": 2, "by_reason": {"quote_not_found": 2}, "pass_rate": 0.5}
    assert g["report"]["returned"] == 3 and g["report"]["kept"] == 2 and g["report"]["pass_rate"] == 0.6667
