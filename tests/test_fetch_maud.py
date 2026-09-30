import io
import urllib.error

import pytest

from pipeline.fetch_maud import contract_names, fetch, fetch_all
from pipeline.ledger import Ledger


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class BrokenResponse(FakeResponse):
    """Yields some bytes, then the connection dies."""

    def __init__(self, data):
        super().__init__(data)
        self.calls = 0

    def read(self, n=-1):
        self.calls += 1
        if self.calls > 1:
            raise ConnectionError("killed mid-download")
        return super().read(4)


def opener_for(files, calls=None):
    def opener(req):
        url = req.full_url
        if calls is not None:
            calls.append(url)
        if url not in files:
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
        return FakeResponse(files[url])
    return opener


def test_fetch_writes_file_and_ledger(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    rec = fetch("http://x/a.txt", tmp_path / "a.txt", led, opener_for({"http://x/a.txt": b"hello"}))
    assert rec["status"] == "ok" and rec["bytes"] == 5
    assert (tmp_path / "a.txt").read_bytes() == b"hello"


def test_fetch_is_skipped_when_already_done(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    calls = []
    op = opener_for({"http://x/a.txt": b"hello"}, calls)
    fetch("http://x/a.txt", tmp_path / "a.txt", led, op)
    fetch("http://x/a.txt", tmp_path / "a.txt", Ledger(tmp_path / "l.jsonl"), op)
    assert calls == ["http://x/a.txt"]


def test_interrupted_download_is_not_treated_as_complete(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    dest = tmp_path / "a.txt"
    with pytest.raises(ConnectionError):
        fetch("http://x/a.txt", dest, led, lambda req: BrokenResponse(b"hello world"))
    assert not dest.exists()
    assert Ledger(tmp_path / "l.jsonl").get("http://x/a.txt") is None
    rec = fetch("http://x/a.txt", dest, Ledger(tmp_path / "l.jsonl"), opener_for({"http://x/a.txt": b"hello world"}))
    assert rec["status"] == "ok" and dest.read_bytes() == b"hello world"


def test_missing_file_is_recorded_not_raised(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    rec = fetch("http://x/gone.txt", tmp_path / "gone.txt", led, opener_for({}))
    assert rec["status"] == "missing"
    assert not (tmp_path / "gone.txt").exists()


def test_contract_names_skips_pseudo_contract(tmp_path):
    p = tmp_path / "MAUD_dev.csv"
    p.write_text(
        "data_type,contract_name,text,answer,label,question,subquestion,text_type,id,category\n"
        "main,contract_2,t,a,0,q,<NONE>,tt,1,c\n"
        "rare_answers,<RARE_ANSWERS>,t,a,0,q,<NONE>,tt,2,c\n"
        "main,contract_10,t,a,0,q,<NONE>,tt,3,c\n",
        encoding="utf-8",
    )
    assert contract_names([p]) == ["contract_10", "contract_2"]


def test_fetch_all_counts_missing_contracts(tmp_path, monkeypatch):
    import pipeline.fetch_maud as fm

    monkeypatch.setattr(fm, "CSV_NAMES", ("MAUD_dev.csv",))
    monkeypatch.setattr(fm, "MAUD_BASE", "http://x")
    csv = (
        "data_type,contract_name,text,answer,label,question,subquestion,text_type,id,category\n"
        "main,contract_1,t,a,0,q,<NONE>,tt,1,c\n"
        "main,contract_2,t,a,0,q,<NONE>,tt,2,c\n"
    ).encode()
    files = {"http://x/MAUD_dev.csv": csv, "http://x/contracts/contract_1.txt": b"AGREEMENT"}
    summary = fetch_all(tmp_path, opener_for(files))
    assert summary == {"ok": 2, "missing": 1}
    assert (tmp_path / "contracts" / "contract_1.txt").exists()
