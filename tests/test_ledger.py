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
