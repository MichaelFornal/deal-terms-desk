import json
from pathlib import Path

LEXICON_PATH = Path(__file__).with_name("lexicon.json")


def load_lexicon(path=LEXICON_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))["entries"]


def rewrite(query: str, lexicon: dict) -> str:
    return query
