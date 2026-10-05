import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_service_is_a_packaged_module():
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "service" in cfg["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    import service  # noqa: F401
