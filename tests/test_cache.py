import pytest

from service.cache import CACHEABLE, AnswerCache, normalise_question

PAYLOAD = {"state": "answered", "amended": True, "candidates": [],
           "claims": [{"text": "The fee is $40m.", "quote": "The Termination Fee shall be $40,000,000",
                       "agreement": "Acme Software / Big Parent", "section_path": "Article VIII › 8.3",
                       "link": "https://www.sec.gov/Archives/x.htm", "amendment_no": 2,
                       "amendment_link": "https://www.sec.gov/Archives/y.htm"}]}


def test_a_hit_returns_the_payload_unchanged(tmp_path):
    c = AnswerCache(tmp_path / "cache.db")
    assert c.get("m", "abc") is None
    c.put("m", "abc", PAYLOAD)
    assert c.get("m", "abc") == PAYLOAD


def test_the_key_is_model_and_prompt_hash(tmp_path):
    c = AnswerCache(tmp_path / "cache.db")
    c.put("m", "abc", PAYLOAD)
    assert c.get("other-model", "abc") is None and c.get("m", "abd") is None


@pytest.mark.parametrize("state", ["which_deal", "budget_cached", "budget_reached", "busy", "error"])
def test_only_model_answers_are_cached(tmp_path, state):
    c = AnswerCache(tmp_path / "cache.db")
    c.put("m", "abc", PAYLOAD | {"state": state})
    assert c.get("m", "abc") is None
    assert set(CACHEABLE) == {"answered", "not_stated", "unfiled_schedule"}


def test_a_newer_answer_replaces_the_older(tmp_path):
    c = AnswerCache(tmp_path / "cache.db")
    c.put("m", "abc", PAYLOAD)
    c.put("m", "abc", {"state": "not_stated", "claims": []})
    assert c.get("m", "abc") == {"state": "not_stated", "claims": []}


def test_the_cache_survives_a_restart_and_a_second_writer(tmp_path):
    AnswerCache(tmp_path / "cache.db").put("m", "abc", PAYLOAD)
    AnswerCache(tmp_path / "cache.db").put("m", "def", {"state": "not_stated", "claims": []})
    fresh = AnswerCache(tmp_path / "cache.db")
    assert fresh.get("m", "abc") == PAYLOAD and fresh.get("m", "def")["state"] == "not_stated"


def test_questions_are_whitespace_normalised_only():
    assert normalise_question("  What is the\n termination   fee? ") == "What is the termination fee?"
    assert normalise_question("Fee?") != normalise_question("fee?")  # case reaches the prompt, so it is kept
