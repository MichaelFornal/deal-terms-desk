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
                          "output_tokens": 20, "api_ms": 50,
                          "usage": {"input_tokens": 100, "output_tokens": 20}}
    again = fake_claude("never used")
    assert rewrite_all(["fee", "options"], cache, runner=again, model="m") == out
    assert again.calls == []


def test_input_tokens_sum_the_cache_fields_and_raw_usage_is_kept(tmp_path):
    usage = {"input_tokens": 2, "cache_creation_input_tokens": 20437, "cache_read_input_tokens": 11904,
             "output_tokens": 11207, "output_tokens_details": {"thinking_tokens": 76}}

    def runner(prompt, model):
        return {"result": "x", "usage": usage, "duration_api_ms": 5}
    out = rewrite_all(["fee"], tmp_path / "rw.jsonl", runner=runner, model="m")
    assert out["fee"]["input_tokens"] == 2 + 20437 + 11904
    assert out["fee"]["output_tokens"] == 11207
    assert out["fee"]["usage"] == usage


def test_missing_usage_keys_count_zero(tmp_path):
    def runner(prompt, model):
        return {"result": "x", "usage": {"output_tokens": 3}}
    out = rewrite_all(["fee"], tmp_path / "rw.jsonl", runner=runner, model="m")
    assert out["fee"]["input_tokens"] == 0 and out["fee"]["usage"] == {"output_tokens": 3}
