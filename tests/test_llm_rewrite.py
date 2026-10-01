from evals.llm_rewrite import clean, rewrite_all
from tests.fakes import fake_claude


def test_clean_takes_the_first_line_and_falls_back_to_the_query():
    assert clean('"Termination Fee payable by the Company"\nextra', "fee") == "Termination Fee payable by the Company"
    assert clean("  \n ", "fee") == "fee"


def test_rewrite_all_calls_once_per_distinct_query_and_resumes(tmp_path):
    runner = fake_claude("Company Termination Fee")
    cache = tmp_path / "rw.jsonl"
    out = rewrite_all(["fee", "fee", "options"], cache, runner=runner, model="m")
    assert set(out) == {"fee", "options"} and len(runner.calls) == 2
    assert out["fee"] == {"query": "fee", "rewrite": "Company Termination Fee", "input_tokens": 100,
                          "output_tokens": 20, "api_ms": 50}
    again = fake_claude("never used")
    assert rewrite_all(["fee", "options"], cache, runner=again, model="m") == out
    assert again.calls == []
