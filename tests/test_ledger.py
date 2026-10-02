from pipeline.ledger import Ledger


def test_put_then_get_survives_reopen(tmp_path):
    p = tmp_path / "ledger.jsonl"
    Ledger(p).put({"url": "u1", "status": "ok", "bytes": 3})
    assert Ledger(p).get("u1") == {"url": "u1", "status": "ok", "bytes": 3}
    assert Ledger(p).get("absent") is None


def test_later_record_wins(tmp_path):
    p = tmp_path / "ledger.jsonl"
    led = Ledger(p)
    led.put({"url": "u1", "status": "missing"})
    led.put({"url": "u1", "status": "ok", "bytes": 9})
    assert Ledger(p).get("u1")["status"] == "ok"


def test_unterminated_last_line_is_ignored(tmp_path):
    p = tmp_path / "ledger.jsonl"
    p.write_text('{"url": "u1", "status": "ok", "bytes": 1}\n{"url": "u2", "sta')
    led = Ledger(p)
    assert led.get("u1") is not None
    assert led.get("u2") is None


def test_torn_line_truncated_on_load_survives_resume(tmp_path):
    p = tmp_path / "ledger.jsonl"
    # Write a complete record and a torn one
    p.write_text('{"url": "u1", "status": "ok", "bytes": 5}\n{"url": "u2", "sta')
    # Open ledger (truncates torn line)
    led = Ledger(p)
    # Put a new record
    led.put({"url": "u3", "status": "ok", "bytes": 10})
    # Reopen and verify all readable records survive
    led2 = Ledger(p)
    assert led2.get("u1") == {"url": "u1", "status": "ok", "bytes": 5}
    assert led2.get("u2") is None
    assert led2.get("u3") == {"url": "u3", "status": "ok", "bytes": 10}


def test_ledger_key_is_configurable(tmp_path):
    from pipeline.ledger import Ledger
    led = Ledger(tmp_path / "l.jsonl", key="query")
    led.put({"query": "fee", "rewrite": "termination fee"})
    assert Ledger(tmp_path / "l.jsonl", key="query").get("fee")["rewrite"] == "termination fee"


def test_the_torn_line_rewrite_is_atomic(tmp_path, monkeypatch):
    from pathlib import Path
    p = tmp_path / "ledger.jsonl"
    good = '{"url": "u1", "status": "ok", "bytes": 5}\n'
    p.write_text(good + '{"url": "u2", "sta')
    real = Path.write_text

    def torn(self, text, **kw):
        real(self, text[:7], **kw)
        raise OSError("disk full")
    monkeypatch.setattr(Path, "write_text", torn)
    try:
        Ledger(p)
    except OSError:
        pass
    monkeypatch.setattr(Path, "write_text", real)
    assert p.read_text().startswith(good)
    led = Ledger(p)
    assert led.get("u1") is not None and led.get("u2") is None
    assert p.read_text() == good
    assert [x.name for x in tmp_path.iterdir()] == ["ledger.jsonl"]
