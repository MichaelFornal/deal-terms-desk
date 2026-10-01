import json
import subprocess


def run_claude(prompt: str, model: str, timeout: int = 900) -> dict:
    """One non-interactive `claude -p` call on the Max plan; $0 cash. Raises on a non-zero exit."""
    done = subprocess.run(["claude", "-p", "--model", model, "--output-format", "json"],
                          input=prompt, capture_output=True, text=True, timeout=timeout, check=True)
    return json.loads(done.stdout)
