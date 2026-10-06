import json

import pytest
from fastapi.testclient import TestClient

from answer.api_runner import RunnerError
from service.app import create_app
from service.warm import warm, warm_ok
from tests.fakes import fake_claude
from tests.test_desk import NOT_STATED, Scripted, make_desk


def client(tmp_path, runner=None, host="203.0.113.7", **kw):
    desk = make_desk(tmp_path, runner or Scripted(), **kw)
    return TestClient(create_app(desk.config, desk), client=(host, 50000)), desk


def test_round_trip(tmp_path):
    c, _ = client(tmp_path, Scripted(NOT_STATED))
    h = c.get("/api/health").json()
    assert h["ok"] is True and h["git_sha"] == "abc123"
    assert {d["id"] for d in c.get("/api/deals").json()} == {"contract_1", "edgar_0001"}
    s = c.get("/api/search", params={"q": "What is the Acme Software outside date?"}).json()
    assert s["hits"] and s["scope"]["deal"] == "edgar_0001"
    a = c.post("/api/ask", json={"question": "termination fee", "deal": "edgar_0001"}).json()
    assert a["state"] == "not_stated" and a["served_from"] == "live"
    assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404


def test_invalid_input_is_422_and_never_retrieves(tmp_path, monkeypatch):
    c, desk = client(tmp_path)

    def boom(*a, **k):
        raise AssertionError("retrieval ran for an invalid request")
    monkeypatch.setattr(desk.answerer, "prepare", boom)
    assert c.post("/api/ask", json={"question": "   "}).status_code == 422
    assert c.post("/api/ask", json={"question": "x" * 301}).status_code == 422
    assert c.post("/api/ask", json={"question": 7}).status_code == 422
    assert c.post("/api/ask", json={"question": "fee", "deal": 7}).status_code == 422
    assert c.post("/api/ask", json={"question": "fee", "deal": "edgar_9999"}).status_code == 422
    assert c.get("/api/search", params={"q": ""}).status_code == 422
    assert c.get("/api/search", params={"q": "fee", "deal": "edgar_9999"}).status_code == 422


def test_rate_limits_answer_429_with_retry_after(tmp_path):
    c, _ = client(tmp_path, Scripted(NOT_STATED), ask_per_hour=1, search_per_minute=1)
    assert c.post("/api/ask", json={"question": "termination fee", "deal": "edgar_0001"}).status_code == 200
    r = c.post("/api/ask", json={"question": "termination fee", "deal": "edgar_0001"})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    assert c.get("/api/search", params={"q": "outside date"}).status_code == 200
    assert c.get("/api/search", params={"q": "outside date"}).status_code == 429


def test_ipv6_neighbours_in_one_slash_64_share_a_bucket(tmp_path):
    c1, _ = client(tmp_path, host="2001:db8::1", search_per_minute=1)
    same = TestClient(c1.app, client=("2001:db8::2", 50000))
    other = TestClient(c1.app, client=("2001:db8:0:1::2", 50000))
    assert c1.get("/api/search", params={"q": "outside date"}).status_code == 200
    assert same.get("/api/search", params={"q": "outside date"}).status_code == 429
    assert other.get("/api/search", params={"q": "outside date"}).status_code == 200


def test_the_request_log_holds_no_address_and_no_question(tmp_path, capsys):
    c, _ = client(tmp_path, Scripted(NOT_STATED))
    c.post("/api/ask", json={"question": "termination fee secretword", "deal": "edgar_0001"})
    c.get("/api/search", params={"q": "outside date secretword"})
    err = capsys.readouterr().err
    assert '"route": "ask"' in err and '"route": "search"' in err
    assert "secretword" not in err and "203.0.113.7" not in err


def test_warm_answers_each_example_once(tmp_path):
    run = fake_claude(NOT_STATED)
    desk = make_desk(tmp_path, run)
    examples = [{"family": "termination_fee", "question": "What is the Acme Software termination fee?"},
                {"family": "equity_awards", "question": "What happens to options in the Gamma deal?"}]
    assert warm(desk, examples) == {"asked": 2, "cached": 0, "states": {"not_stated": 2}}
    assert warm(desk, examples)["cached"] == 2 and len(run.calls) == 2


def test_dtd_warm_builds_the_service_desk(tmp_path, monkeypatch, capsys):
    from pipeline import cli
    desk = make_desk(tmp_path, fake_claude(NOT_STATED))
    seen = {}

    def build(config):
        seen["config"] = config
        return desk
    monkeypatch.setattr(cli, "from_env", lambda: desk.config)
    monkeypatch.setattr(cli, "build_desk", build)
    path = tmp_path / "examples.json"
    path.write_text(json.dumps([{"family": "termination_fee", "question": "What is the Acme Software termination fee?"}]))
    assert cli.entry(["warm", "--examples", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["asked"] == 1
    assert seen["config"].fresh_per_hour >= 1


def test_build_desk_makes_its_runner_with_the_thinking_settings(tmp_path, monkeypatch):
    import dataclasses

    from service import app
    seen = {}

    def runner_for(*args, **kw):
        seen["args"], seen["kw"] = args, kw
        raise StopIteration  # nothing past the runner is needed

    monkeypatch.setattr(app, "make_api_runner", runner_for)
    monkeypatch.setattr(app, "Embedder", lambda *a, **k: type("E", (), {"embed_query": lambda s, q: None})())
    monkeypatch.setattr(app, "build_live_ladder", lambda *a, **k: None)
    monkeypatch.setattr(app, "load_lexicon", lambda *a, **k: {})
    monkeypatch.setattr(app, "load_settings", lambda *a, **k: None)
    monkeypatch.setattr(app, "Budget", lambda *a, **k: None)
    base = make_desk(tmp_path, fake_claude(NOT_STATED)).config
    for budget, want in ((3000, 3000), (0, None)):
        cfg = dataclasses.replace(base, thinking_budget=budget, api_timeout_s=77.0, max_tokens=6000)
        with pytest.raises(StopIteration):
            app.build_desk(cfg)
        assert seen["args"] == (6000,) and seen["kw"] == {"timeout": 77.0, "thinking_budget": want}


def test_build_desk_refuses_a_model_the_prices_do_not_describe(tmp_path, monkeypatch):
    """The ledger prices every call at prices.json's rates: another model would be priced as Haiku and could
    under-reserve. Checked before anything is loaded."""
    import dataclasses

    from service import app
    monkeypatch.setattr(app, "Embedder", lambda *a, **k: pytest.fail("loaded the embedder before the check"))
    base = make_desk(tmp_path, fake_claude(NOT_STATED)).config
    cfg = dataclasses.replace(base, model="claude-sonnet-5-5")
    with pytest.raises(ValueError, match=r"DTD_MODEL is claude-sonnet-5-5 but .*prices\.json.* claude-haiku-4-5"):
        app.build_desk(cfg)


def test_warm_ok_needs_an_answering_state_for_every_example():
    assert warm_ok({"asked": 2, "cached": 0, "states": {"answered": 1, "unfiled_schedule": 1}})
    assert not warm_ok({"asked": 0, "cached": 0, "states": {}})
    assert not warm_ok({"asked": 2, "cached": 0, "states": {"answered": 1, "error": 1}})
    assert not warm_ok({"asked": 1, "cached": 1, "states": {"budget_cached": 1}})


def test_dtd_warm_exits_non_zero_when_an_example_fails(tmp_path, monkeypatch, capsys):
    from pipeline import cli
    desk = make_desk(tmp_path, Scripted(RunnerError("overloaded", "overloaded")))
    monkeypatch.setattr(cli, "from_env", lambda: desk.config)
    monkeypatch.setattr(cli, "build_desk", lambda config: desk)
    path = tmp_path / "examples.json"
    path.write_text(json.dumps([{"family": "termination_fee", "question": "What is the Acme Software termination fee?"}]))
    assert cli.entry(["warm", "--examples", str(path)]) == 1
    assert json.loads(capsys.readouterr().out)["states"] == {"error": 1}  # the line is still printed for push.sh
