import threading

import anthropic

KINDS = ("rate_limited", "overloaded", "timeout", "connection", "bad_request", "billing", "refusal", "truncated")
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
# A 400/402/403 that says one of these is the account's money running out (a Console spend limit or no credit),
# which the service shows as the budget state. "limit" alone is not enough: "max_tokens exceeds the limit" is a bug.
BILLING_WORDS = ("credit", "billing", "spend", "usage limit")
TRUNCATED = ("max_tokens", "model_context_window_exceeded")


class RunnerError(RuntimeError):
    """A failed API call. `kind` is one of KINDS; `usage` is what the call was billed for ({} when nothing came
    back), so the spend ledger settles actual tokens. A RuntimeError, so evals.run_answers ledgers it as
    `runner: <kind>: …` like any runner failure."""

    def __init__(self, kind: str, message: str, usage: dict | None = None):
        if kind not in KINDS:
            raise ValueError(f"unknown runner error kind {kind!r}")
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.usage = dict(usage or {})


def _usage(u) -> dict:
    return {k: int(getattr(u, k, None) or 0) for k in USAGE_KEYS}


def _kind(e: Exception) -> str:
    if isinstance(e, anthropic.APITimeoutError):  # a subclass of APIConnectionError: test it first
        return "timeout"
    if isinstance(e, anthropic.APIConnectionError):
        return "connection"
    if isinstance(e, anthropic.RateLimitError):
        return "rate_limited"
    if isinstance(e, (anthropic.OverloadedError, anthropic.InternalServerError)):
        return "overloaded"
    if (isinstance(e, anthropic.APIStatusError) and e.status_code in (400, 402, 403)
            and any(w in str(e).lower() for w in BILLING_WORDS)):
        return "billing"
    return "bad_request"


def make_api_runner(max_tokens: int, client=None, timeout: float = 30.0):
    """runner(prompt, model) -> {"result", "usage", "stop_reason"}: the `run_claude` contract over the Messages API.
    One user turn, no system prompt, no thinking, at most `max_tokens` out. The client is built on first use
    (no SDK retry: one billed attempt per reservation; `timeout` seconds) unless one is given. A truncated or refused reply raises RunnerError with its
    usage; it is never returned as an answer."""
    state, lock = {"client": client}, threading.Lock()

    def runner(prompt: str, model: str) -> dict:
        with lock:
            if state["client"] is None:
                state["client"] = anthropic.Anthropic(max_retries=0, timeout=timeout)
            c = state["client"]
        try:
            msg = c.messages.create(model=model, max_tokens=max_tokens,
                                    messages=[{"role": "user", "content": prompt}])
        except anthropic.AnthropicError as e:
            raise RunnerError(_kind(e), str(e)[:300]) from None
        usage = _usage(msg.usage)
        if msg.stop_reason in TRUNCATED:
            raise RunnerError("truncated", f"reply stopped at {msg.stop_reason} (max_tokens={max_tokens})", usage)
        if msg.stop_reason == "refusal":
            raise RunnerError("refusal", "the model declined to answer", usage)
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        return {"result": text, "usage": usage, "stop_reason": msg.stop_reason}
    return runner
