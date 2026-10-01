import json
import subprocess


def run_claude(prompt: str, model: str, timeout: int = 900) -> dict:
    """One non-interactive `claude -p` call on the Max plan; $0 cash.

    Every failure raises RuntimeError with a plain message.
    """
    try:
        done = subprocess.run(["claude", "-p", "--model", model, "--output-format", "json"],
                              input=prompt, capture_output=True, text=True, timeout=timeout, check=True)
    except FileNotFoundError:
        raise RuntimeError("claude CLI not found on PATH") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"claude timed out after {timeout}s") from None
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"claude exited {e.returncode}: {(e.stderr or '')[:500]}") from None
    try:
        reply = json.loads(done.stdout)
    except ValueError:
        raise RuntimeError(f"claude returned non-JSON output: {done.stdout[:200]!r}") from None
    if not isinstance(reply, dict) or reply.get("is_error") or "result" not in reply:
        raise RuntimeError(f"claude returned an error reply: {str(reply)[:500]}")
    return reply
