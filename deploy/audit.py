"""Pre-public audit: what the public would see in the repo and its whole history. Never prints a secret: values
read from .env are compared in memory, and only names, counts and paths are reported. Exit 1 on any finding.

Usage: uv run python deploy/audit.py [--repo .] [--env .env]"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

KEY = re.compile(rb"sk-ant-[A-Za-z0-9_-]{20,}")
SECRETS = ("SEC_CONTACT", "ANTHROPIC_API_KEY", "HCLOUD_TOKEN")
MIN_SECRET = 8  # shorter values would match by chance
PRIVATE = re.compile(r"^(data/|\.env$|\.superpowers/|\.claude/)|\.(db|jsonl)$|(^|/)live\.db")
MAX_BYTES = 1_000_000


def env_values(path: Path) -> dict[str, bytes]:
    """The secret values in .env, as bytes. Missing file → {}."""
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        name = name.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if sep and name in SECRETS and len(value) >= MIN_SECRET:
            out[name] = value.encode()
    return out


def _git(repo: Path, *args: str, stdin: bytes | None = None) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], input=stdin, capture_output=True, check=True).stdout


def tracked_problems(repo: Path) -> list[str]:
    out = []
    for path in _git(repo, "ls-files", "-z").decode().split("\0"):
        if not path:
            continue
        if PRIVATE.search(path):
            out.append(f"tracked file that must stay private: {path}")
        elif (repo / path).is_file() and (repo / path).stat().st_size > MAX_BYTES:
            out.append(f"tracked file over 1 MB: {path}")
    return out


def history_problems(repo: Path, secrets: dict[str, bytes]) -> list[str]:
    """Every object reachable from any ref (commits carry author, committer and message), searched for key-shaped
    strings and for each secret value."""
    where: dict[str, str] = {}
    for row in _git(repo, "rev-list", "--all", "--objects").decode().splitlines():
        sha, _, path = row.partition(" ")
        where.setdefault(sha, path)
    if not where:
        return []
    batch = _git(repo, "cat-file", "--batch", stdin=("\n".join(where) + "\n").encode())
    out, i = [], 0
    while i < len(batch):
        end = batch.index(b"\n", i)
        sha, kind, size = batch[i:end].split()
        body = batch[end + 1:end + 1 + int(size)]
        i = end + 1 + int(size) + 1
        name = where[sha.decode()] or f"{'commit' if kind == b'commit' else 'object'} {sha.decode()[:12]}"
        if KEY.search(body):
            out.append(f"key-shaped sk-ant- string in history: {name}")
        for secret, value in secrets.items():
            if value in body:
                out.append(f"{secret} value in history: {name}")
    return out


def audit(repo: Path, env: Path) -> list[str]:
    return tracked_problems(repo) + history_problems(repo, env_values(env))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--env", default=".env")
    args = ap.parse_args(argv)
    repo, env = Path(args.repo), Path(args.env)
    secrets = env_values(env)
    missing = [s for s in SECRETS if s not in secrets]
    if missing:
        print(f"not in .env: {', '.join(missing)}; their values are not searched for", file=sys.stderr)
    problems = audit(repo, env)
    for p in problems:
        print(p)
    print(f"searched for: key-shaped sk-ant- strings, {', '.join(sorted(secrets)) or 'no .env values'}")
    print("audit clean" if not problems else f"{len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
