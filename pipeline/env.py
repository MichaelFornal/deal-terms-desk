import os
from pathlib import Path


def sec_contact(env_file: Path = Path(".env")) -> str:
    value = os.environ.get("SEC_CONTACT", "").strip()
    if not value and Path(env_file).exists():
        for line in Path(env_file).read_text(encoding="utf-8").splitlines():
            key, sep, val = line.partition("=")
            if sep and key.strip() == "SEC_CONTACT":
                value = val.strip().strip('"').strip("'")
    if "@" not in value:
        raise RuntimeError("SEC_CONTACT is not set: export it, or put SEC_CONTACT=<email> in the gitignored .env")
    return value
