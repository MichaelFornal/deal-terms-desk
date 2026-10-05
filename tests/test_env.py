import pytest

from pipeline.env import anthropic_key, sec_contact


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


def test_api_key_comes_from_the_environment_first(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=file-key\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    assert anthropic_key(tmp_path / ".env") == "env-key"


def test_api_key_falls_back_to_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / ".env").write_text('SEC_CONTACT=a@b.c\nANTHROPIC_API_KEY="file-key"\n')
    assert anthropic_key(tmp_path / ".env") == "file-key"


def test_missing_api_key_refuses_without_echoing_anything(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / ".env").write_text("SEC_CONTACT=a@b.c\n")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY") as e:
        anthropic_key(tmp_path / ".env")
    assert "a@b.c" not in str(e.value)
