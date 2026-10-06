import os
from pathlib import Path


def _value(name: str, env_file: Path) -> str:
    """The variable from the environment, else from the gitignored .env (KEY=value lines, quotes stripped)."""
    value = os.environ.get(name, "").strip()
    if not value and Path(env_file).exists():
        for line in Path(env_file).read_text(encoding="utf-8").splitlines():
            key, sep, val = line.partition("=")
            if sep and key.strip() == name:
                value = val.strip().strip('"').strip("'")
    return value


def sec_contact(env_file: Path = Path(".env")) -> str:
    value = _value("SEC_CONTACT", env_file)
    if "@" not in value:
        raise RuntimeError("SEC_CONTACT is not set: export it, or put SEC_CONTACT=<email> in the gitignored .env")
    return value


def anthropic_key(env_file: Path = Path(".env")) -> str:
    """The API key for offline calls (calibration, the real-call test): the dtd-dev workspace key, never the live one."""
    value = _value("ANTHROPIC_API_KEY", env_file)
    if not value:
        raise RuntimeError("ANTHROPIC_API_KEY is not set: export it, or put ANTHROPIC_API_KEY=<the dtd-dev key> in "
                           "the gitignored .env")
    return value
