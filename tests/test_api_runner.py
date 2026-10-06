from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from answer.api_runner import KINDS, RunnerError, make_api_runner

REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
HAIKU = "claude-haiku-4-5-20251001"


def message(text='{"state": "not_stated", "claims": []}', stop="end_turn", **usage):
    u = {"input_tokens": 120, "output_tokens": 30, "cache_creation_input_tokens": None,
         "cache_read_input_tokens": None} | usage
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop,
                           usage=SimpleNamespace(**u))


class FakeClient:
    """Stands in for anthropic.Anthropic: `client.messages.create(**kw)` records kw, then returns or raises."""
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if self.error is not None:
            raise self.error
        return self.reply


def status(cls, code, text):
    return cls(text, response=httpx2.Response(code, request=REQ), body=None)


def test_one_call_returns_text_usage_and_stop_reason():
    client = FakeClient(message())
    got = make_api_runner(1024, client=client)("PROMPT", HAIKU)
    assert got == {"result": '{"state": "not_stated", "claims": []}', "stop_reason": "end_turn",
                   "usage": {"input_tokens": 120, "output_tokens": 30, "cache_creation_input_tokens": 0,
                             "cache_read_input_tokens": 0}}
    # one plain call: no system prompt, no thinking, no temperature
    assert client.calls == [{"model": HAIKU, "max_tokens": 1024,
                             "messages": [{"role": "user", "content": "PROMPT"}]}]


def test_only_text_blocks_are_joined():
    msg = message()
    msg.content = [SimpleNamespace(type="thinking", thinking="hmm"), SimpleNamespace(type="text", text='{"a": '),
                   SimpleNamespace(type="text", text="1}")]
    assert make_api_runner(64, client=FakeClient(msg))("p", HAIKU)["result"] == '{"a": 1}'


@pytest.mark.parametrize("stop", ["max_tokens", "model_context_window_exceeded"])
def test_a_truncated_reply_is_an_error_that_carries_its_usage(stop):
    with pytest.raises(RunnerError) as e:
        make_api_runner(64, client=FakeClient(message(stop=stop, output_tokens=64)))("p", HAIKU)
    assert e.value.kind == "truncated" and e.value.usage["output_tokens"] == 64
    assert str(e.value).startswith("truncated: ") and isinstance(e.value, RuntimeError)


def test_a_refusal_is_an_error_that_carries_its_usage():
    with pytest.raises(RunnerError) as e:
        make_api_runner(64, client=FakeClient(message(stop="refusal", output_tokens=3)))("p", HAIKU)
    assert e.value.kind == "refusal" and e.value.usage["output_tokens"] == 3


@pytest.mark.parametrize("error, kind", [
    (status(anthropic.RateLimitError, 429, "rate limited"), "rate_limited"),
    (status(anthropic.OverloadedError, 529, "overloaded"), "overloaded"),
    (status(anthropic.InternalServerError, 500, "internal error"), "overloaded"),
    (anthropic.APITimeoutError(request=REQ), "timeout"),
    (anthropic.APIConnectionError(request=REQ), "connection"),
    (status(anthropic.BadRequestError, 400, "Your credit balance is too low to access the API"), "billing"),
    (status(anthropic.PermissionDeniedError, 403, "This workspace has reached its spend limit"), "billing"),
    (status(anthropic.APIStatusError, 402, "billing required"), "billing"),
    (status(anthropic.BadRequestError, 400, "max_tokens: exceeds the model's limit"), "bad_request"),
    (status(anthropic.AuthenticationError, 401, "invalid x-api-key"), "bad_request"),
])
def test_sdk_errors_map_to_kinds_with_no_usage(error, kind):
    with pytest.raises(RunnerError) as e:
        make_api_runner(64, client=FakeClient(error=error))("p", HAIKU)
    assert e.value.kind == kind and e.value.usage == {}


def test_unknown_kind_is_refused():
    with pytest.raises(ValueError):
        RunnerError("weird", "x")
    assert {"truncated", "refusal", "billing", "timeout"} <= set(KINDS)


def test_the_client_is_built_lazily_once_with_one_retry(monkeypatch):
    built = []

    class Recorder(FakeClient):
        def __init__(self, **kw):
            built.append(kw)
            super().__init__(message())
    monkeypatch.setattr("answer.api_runner.anthropic.Anthropic", Recorder)
    run = make_api_runner(64, timeout=12.5)
    assert built == []
    run("p", HAIKU)
    run("q", HAIKU)
    assert built == [{"max_retries": 0, "timeout": 12.5}]


@pytest.mark.model
def test_one_real_call_through_the_dev_key():
    from pipeline.env import anthropic_key
    try:
        key = anthropic_key()
    except RuntimeError:
        pytest.skip("ANTHROPIC_API_KEY (the dtd-dev key) is not set")
    run = make_api_runner(16, client=anthropic.Anthropic(api_key=key, max_retries=0, timeout=30.0))
    got = run("Reply with the single word: ok", HAIKU)
    assert got["result"].strip() and got["usage"]["input_tokens"] > 0 and got["stop_reason"] == "end_turn"


def test_a_client_error_outside_the_sdk_is_a_lost_connection_with_no_usage():
    """A missing key surfaces at request time as a TypeError, outside the SDK's error classes. It must reach Desk as
    a RunnerError (booked at worst case, state error), never escape as a 500."""
    error = TypeError("Could not resolve authentication method. Expected either api_key or auth_token to be set.")
    with pytest.raises(RunnerError) as e:
        make_api_runner(64, client=FakeClient(error=error))("p", HAIKU)
    assert e.value.kind == "connection" and e.value.usage == {}
    assert "TypeError" in str(e.value) and "auth" in str(e.value)


def test_a_thinking_budget_is_sent_on_every_call_and_only_text_reaches_the_parser():
    msg = message()
    msg.content = [SimpleNamespace(type="thinking", thinking="PICK (B)"), SimpleNamespace(type="text", text="{}")]
    client = FakeClient(msg)
    runner = make_api_runner(6144, client=client, thinking_budget=4096)
    assert runner("p", HAIKU)["result"] == "{}"
    runner("p", HAIKU)
    assert [c["thinking"] for c in client.calls] == [{"type": "enabled", "budget_tokens": 4096}] * 2
    assert all("temperature" not in c and c["max_tokens"] == 6144 for c in client.calls)


def test_the_default_timeout_leaves_room_for_thinking(monkeypatch):
    built = []
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: built.append(kw) or FakeClient(message()))
    make_api_runner(64)("p", HAIKU)
    assert built == [{"max_retries": 0, "timeout": 90.0}]


def test_no_budget_sends_no_thinking_key():
    client = FakeClient(message())
    make_api_runner(1024, client=client)("p", HAIKU)
    make_api_runner(1024, client=client, thinking_budget=None)("p", HAIKU)
    assert all("thinking" not in c for c in client.calls)


@pytest.mark.parametrize("budget, cap", [(512, 6144), (1023, 6144), (6144, 6144), (7000, 6144)])
def test_a_budget_outside_the_api_range_is_refused_when_the_runner_is_made(budget, cap):
    with pytest.raises(ValueError, match=rf"{budget}.*{cap}"):
        make_api_runner(cap, client=FakeClient(message()), thinking_budget=budget)


def test_a_thinking_reply_cut_off_at_the_cap_is_still_truncated():
    with pytest.raises(RunnerError) as e:
        make_api_runner(2048, client=FakeClient(message(stop="max_tokens", output_tokens=2048)),
                        thinking_budget=1024)("p", HAIKU)
    assert e.value.kind == "truncated" and e.value.usage["output_tokens"] == 2048
