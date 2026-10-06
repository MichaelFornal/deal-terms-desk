import importlib.util
import subprocess
from pathlib import Path

spec = importlib.util.spec_from_file_location("audit", Path("deploy/audit.py"))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

FAKE_KEY = "sk-ant-api03-" + "x" * 30
FAKE_CONTACT = "someone.private@example.net"
FAKE_TOKEN = "hc" + "y" * 30


def make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    git("init", "-q")
    git("config", "user.email", "a@example.com")
    git("config", "user.name", "A")
    (repo / "ok.txt").write_text("nothing here\n")
    git("add", ".")
    git("commit", "-qm", "first")
    return repo, git


def env_file(tmp_path, text=None):
    env = tmp_path / ".env"
    env.write_text(text if text is not None else
                   f"SEC_CONTACT={FAKE_CONTACT}\nANTHROPIC_API_KEY={FAKE_KEY}\nexport HCLOUD_TOKEN=\"{FAKE_TOKEN}\"\n")
    return env


def test_env_values_reads_the_three_secrets(tmp_path):
    assert audit.env_values(env_file(tmp_path)) == {"SEC_CONTACT": FAKE_CONTACT.encode(),
                                                    "ANTHROPIC_API_KEY": FAKE_KEY.encode(),
                                                    "HCLOUD_TOKEN": FAKE_TOKEN.encode()}


def test_a_clean_repo_passes(tmp_path):
    repo, _ = make_repo(tmp_path)
    assert audit.audit(repo, env_file(tmp_path)) == []


def test_secrets_in_history_are_found_and_never_printed(tmp_path, capsys):
    repo, git = make_repo(tmp_path)
    (repo / "notes.md").write_text(f"key {FAKE_KEY}\n")
    git("add", ".")
    git("commit", "-qm", "add notes")
    git("rm", "-q", "notes.md")
    git("commit", "-qm", "remove notes")  # gone from HEAD, still in history
    git("commit", "--allow-empty", "-qm", f"ping {FAKE_CONTACT}")
    assert audit.main(["--repo", str(repo), "--env", str(env_file(tmp_path))]) == 1
    out = capsys.readouterr()
    lines = out.out.splitlines()
    assert "key-shaped sk-ant- string in history: notes.md" in lines
    assert "ANTHROPIC_API_KEY value in history: notes.md" in lines
    assert any(line.startswith("SEC_CONTACT value in history: commit ") for line in lines)
    for secret in (FAKE_KEY, FAKE_CONTACT, FAKE_TOKEN):
        assert secret not in out.out + out.err


def test_private_and_big_files_must_not_be_tracked(tmp_path):
    repo, git = make_repo(tmp_path)
    (repo / "data").mkdir()
    (repo / "data" / "x.jsonl").write_text("{}\n")
    (repo / "big.bin").write_bytes(b"0" * 1_000_001)
    git("add", "-f", ".")
    git("commit", "-qm", "oops")
    got = audit.tracked_problems(repo)
    assert "tracked file that must stay private: data/x.jsonl" in got
    assert "tracked file over 1 MB: big.bin" in got


def test_secrets_missing_from_env_are_named(tmp_path, capsys):
    repo, _ = make_repo(tmp_path)
    assert audit.main(["--repo", str(repo), "--env", str(env_file(tmp_path, f"SEC_CONTACT={FAKE_CONTACT}\n"))]) == 0
    assert "not in .env: ANTHROPIC_API_KEY, HCLOUD_TOKEN" in capsys.readouterr().err
