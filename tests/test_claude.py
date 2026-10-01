import json
import subprocess

import pytest

from pipeline import claude


def _patch(monkeypatch, *, stdout="", stderr="", code=0, exc=None):
    def fake(cmd, **kw):
        if exc:
            raise exc
        if code:
            raise subprocess.CalledProcessError(code, cmd, output=stdout, stderr=stderr)
        return subprocess.CompletedProcess(cmd, 0, stdout, stderr)
    monkeypatch.setattr(claude.subprocess, "run", fake)


def test_success_returns_the_parsed_reply(monkeypatch):
    _patch(monkeypatch, stdout=json.dumps({"result": "hi", "usage": {}}))
    assert claude.run_claude("p", "m")["result"] == "hi"


def test_non_zero_exit_includes_stderr(monkeypatch):
    _patch(monkeypatch, code=3, stderr="rate limited")
    with pytest.raises(RuntimeError, match="exited 3: rate limited"):
        claude.run_claude("p", "m")


def test_is_error_reply_and_missing_result_raise(monkeypatch):
    _patch(monkeypatch, stdout=json.dumps({"is_error": True, "result": "boom"}))
    with pytest.raises(RuntimeError, match="error reply"):
        claude.run_claude("p", "m")
    _patch(monkeypatch, stdout=json.dumps({"usage": {}}))
    with pytest.raises(RuntimeError, match="error reply"):
        claude.run_claude("p", "m")


def test_non_json_stdout_raises(monkeypatch):
    _patch(monkeypatch, stdout="not json")
    with pytest.raises(RuntimeError, match="non-JSON"):
        claude.run_claude("p", "m")


def test_missing_binary_and_timeout_raise(monkeypatch):
    _patch(monkeypatch, exc=FileNotFoundError())
    with pytest.raises(RuntimeError, match="not found"):
        claude.run_claude("p", "m")
    _patch(monkeypatch, exc=subprocess.TimeoutExpired("claude", 1))
    with pytest.raises(RuntimeError, match="timed out"):
        claude.run_claude("p", "m")
