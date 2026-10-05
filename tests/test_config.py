from pathlib import Path

import pytest

from service.config import Config, from_env
from service.prices import load_prices


def test_defaults_need_only_the_month_cap(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no GIT_SHA file here
    assert from_env({"DTD_MONTH_CAP_USD": "4.5"}) == Config(
        bundle=Path("data/live/live.db"), state_dir=Path("data/state"), prices_path=Path("service/prices.json"),
        facts_path=Path("facts.json"), model="claude-haiku-4-5-20251001", max_tokens=1024, month_cap_usd=4.5,
        day_cap_usd=0.45, question_max_chars=500, ask_per_hour=20, search_per_minute=60, fresh_per_hour=60,
        ask_slots=2, git_sha="unknown")


def test_the_month_cap_is_required():
    with pytest.raises(ValueError, match="DTD_MONTH_CAP_USD"):
        from_env({})
    with pytest.raises(ValueError, match="DTD_MONTH_CAP_USD"):
        from_env({"DTD_MONTH_CAP_USD": "  "})


@pytest.mark.parametrize("name, value", [("DTD_MONTH_CAP_USD", "lots"), ("DTD_MONTH_CAP_USD", "0"),
                                         ("DTD_DAY_CAP_USD", "-1"), ("DTD_MAX_TOKENS", "-5"),
                                         ("DTD_ASK_SLOTS", "1.5")])
def test_bad_numbers_are_refused_by_name(name, value):
    with pytest.raises(ValueError, match=name):
        from_env({"DTD_MONTH_CAP_USD": "4.5"} | {name: value})


def test_a_tiny_cap_is_allowed_for_the_cap_trip_test():
    assert from_env({"DTD_MONTH_CAP_USD": "0.0001"}).month_cap_usd == 0.0001


def test_every_setting_can_be_overridden():
    env = {"DTD_BUNDLE": "/srv/dtd/bundle/live.db", "DTD_STATE": "/var/lib/dtd", "DTD_PRICES": "/p.json",
           "DTD_FACTS": "/f.json", "DTD_MODEL": "m", "DTD_MAX_TOKENS": "900", "DTD_MONTH_CAP_USD": "4.8",
           "DTD_DAY_CAP_USD": "0.6", "DTD_QUESTION_MAX_CHARS": "400", "DTD_ASK_PER_HOUR": "10",
           "DTD_SEARCH_PER_MINUTE": "30", "DTD_FRESH_PER_HOUR": "40", "DTD_ASK_SLOTS": "3", "DTD_GIT_SHA": "abc1234"}
    assert from_env(env) == Config(Path("/srv/dtd/bundle/live.db"), Path("/var/lib/dtd"), Path("/p.json"),
                                   Path("/f.json"), "m", 900, 4.8, 0.6, 400, 10, 30, 40, 3, "abc1234")


def test_the_default_model_is_the_one_the_price_table_prices():
    assert from_env({"DTD_MONTH_CAP_USD": "1"}).model == load_prices("service/prices.json").model


def test_git_sha_comes_from_the_env_then_the_release_file_then_unknown(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert from_env({"DTD_MONTH_CAP_USD": "1"}).git_sha == "unknown"
    (tmp_path / "GIT_SHA").write_text("abc1234\n")  # push.sh writes this into each release
    assert from_env({"DTD_MONTH_CAP_USD": "1"}).git_sha == "abc1234"
    assert from_env({"DTD_MONTH_CAP_USD": "1", "DTD_GIT_SHA": "def5678"}).git_sha == "def5678"


@pytest.mark.parametrize("name", ["DTD_MONTH_CAP_USD", "DTD_DAY_CAP_USD"])
@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_non_finite_caps_are_refused_by_name(name, value):
    with pytest.raises(ValueError, match=name):
        from_env({"DTD_MONTH_CAP_USD": "4.5"} | {name: value})
