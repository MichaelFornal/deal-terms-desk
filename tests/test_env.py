import pytest

from pipeline.env import sec_contact


def test_contact_comes_from_the_environment_first(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("SEC_CONTACT=file@example.com\n")
    monkeypatch.setenv("SEC_CONTACT", "env@example.com")
    assert sec_contact(tmp_path / ".env") == "env@example.com"


def test_contact_falls_back_to_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("SEC_CONTACT", raising=False)
    (tmp_path / ".env").write_text('# comment\nOTHER=x\nSEC_CONTACT="file@example.com"\n')
    assert sec_contact(tmp_path / ".env") == "file@example.com"


def test_missing_contact_refuses(tmp_path, monkeypatch):
    monkeypatch.delenv("SEC_CONTACT", raising=False)
    with pytest.raises(RuntimeError, match="SEC_CONTACT"):
        sec_contact(tmp_path / ".env")
