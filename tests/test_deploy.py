import importlib.util
import json
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest

CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; "
       "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
spec = importlib.util.spec_from_file_location("smoke", Path("deploy/smoke.py"))
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def test_caddy_sets_the_exact_csp_and_proxies_only_the_api():
    text = Path("deploy/Caddyfile").read_text()
    assert f'Content-Security-Policy "{CSP}"' in text and smoke.CSP == CSP
    assert "unsafe-inline" not in text and "unsafe-eval" not in text
    assert "handle /api/*" in text and "reverse_proxy 127.0.0.1:8000" in text
    assert "root * /srv/dtd/current/site/dist" in text and not re.search(r"^\s*log\b", text, re.M)


def test_caddy_caps_the_api_request_body():
    text = Path("deploy/Caddyfile").read_text()
    block = re.search(r"handle /api/\* \{(.*?)\n\t\}", text, re.S).group(1)
    assert re.search(r"request_body\s*\{\s*max_size 16KB\s*\}", block)
    assert block.index("request_body") < block.index("reverse_proxy")


def test_service_unit_runs_one_worker_without_access_logs():
    text = Path("deploy/dtd.service").read_text()
    for flag in ("--factory service.app:create_app", "--host 127.0.0.1", "--port 8000", "--workers 1",
                 "--no-access-log", "--forwarded-allow-ips 127.0.0.1"):
        assert flag in text
    for line in ("User=dtd", "WorkingDirectory=/srv/dtd/current", "EnvironmentFile=/etc/dtd/env",
                 "ProtectSystem=strict", "ReadWritePaths=/var/lib/dtd", "MemoryMax=2G", "Restart=always",
                 "WantedBy=multi-user.target"):
        assert line in text


def test_push_refuses_a_dirty_tree_and_ships_only_committed_code():
    text = Path("deploy/push.sh").read_text()
    for s in ("set -euo pipefail", "git status --porcelain", "git archive", "dtd facts --check", "dtd bundle",
              "dtd site", "uv sync --frozen --no-dev", "UV_PYTHON_PREFERENCE=only-system", "/api/health",
              "sha256sum -c", "dtd warm"):
        assert s in text, s
    assert not re.search(r"rsync[^\n]*\s\.\s", text)  # the code never leaves as the working tree
    subprocess.run(["bash", "-n", "deploy/push.sh"], check=True)


def test_push_validates_before_the_swap_and_can_revert():
    text = Path("deploy/push.sh").read_text()
    swap = text.index("current.next")
    assert text.index("caddy validate --adapter caddyfile --config") < swap
    assert text.index("systemd-analyze verify") < swap
    assert text.index('PREV="$(ssh') < text.index('install_release "$REL"')
    assert 'install_release "$PREV"' in text and "reverting to the previous release" in text
    assert "readlink /srv/dtd/current" in text


def test_push_warms_every_time_and_checks_the_result():
    text = Path("deploy/push.sh").read_text()
    assert "dtd warm --examples" in text and "TEMPLATE_SHA" not in text and '"$OLD"' not in text
    assert '"unfiled_schedule"' in text and 'got["states"]' in text and "warm failed" in text


def test_push_checks_env_file_bounds_curl_and_chowns_rsync():
    text = Path("deploy/push.sh").read_text()
    assert "stat -c '%U %a' /etc/dtd/env" in text and '"root 600"' in text
    for line in text.splitlines():
        if "curl " in line and not line.lstrip().startswith("#"):
            assert "--max-time 10" in line, line
        if line.lstrip().startswith("rsync "):
            assert "--chown=root:root" in line, line
    assert "cd $REL &&" not in text


def test_provision_is_resumable_noninteractive_and_keeps_a_way_in():
    text = Path("deploy/provision.sh").read_text()
    assert "gpg --batch --yes --dearmor" in text
    assert "--force-confdef" in text and "--force-confold" in text and "</dev/null" in text
    assert text.index("/root/.ssh/authorized_keys") < text.index("PasswordAuthentication no")
    assert "[ ! -s /root/.ssh/authorized_keys ]" in text


def test_provision_locks_the_box_down():
    text = Path("deploy/provision.sh").read_text()
    for s in ("set -euo pipefail", "ufw allow 22/tcp", "ufw allow 80/tcp", "ufw allow 443/tcp",
              "PasswordAuthentication no", "unattended-upgrades", "useradd --system", "SystemMaxUse=",
              "UV_INSTALL_DIR=/usr/local/bin"):
        assert s in text, s
    subprocess.run(["bash", "-n", "deploy/provision.sh"], check=True)


def test_hosting_record_has_every_field_the_facts_read():
    h = json.loads(Path("deploy/hosting.json").read_text())
    assert set(h) == {"provider", "plan", "eur_month", "extras_eur_month", "eur_usd", "eur_usd_date",
                      "eur_usd_source", "budget_usd_month", "day_cap_usd", "checked"}
    assert h["budget_usd_month"] == 10.0 and h["eur_month"] > 0


def test_env_example_names_the_variables_and_holds_no_secret():
    text = Path("deploy/env.example").read_text()
    for name in ("ANTHROPIC_API_KEY=", "DTD_BUNDLE=", "DTD_STATE=", "DTD_MONTH_CAP_USD=", "DTD_DAY_CAP_USD=",
                 "FASTEMBED_CACHE_PATH="):
        assert name in text
    assert "sk-ant-" not in text and "@" not in text


class Box(BaseHTTPRequestHandler):
    """A fake live desk: healthy unless a test flips a class attribute."""
    csp, disclaimer, searches, limit_after = CSP, True, [0], 3

    def _send(self, code, body: bytes, ctype="application/json", headers=()):
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200, headers=()):
        self._send(code, json.dumps(obj).encode(), headers=headers)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            return self._json({"git_sha": "g", "bundle_sha": "b", "facts_sha": "f", "budget": "ok"})
        if path == "/api/deals":
            return self._json([{"id": "x"}])
        if path == "/api/search":
            Box.searches[0] += 1
            if Box.searches[0] > Box.limit_after:  # keyed on the socket address, whatever the header says
                return self._json({"error": "rate_limited"}, 429, [("Retry-After", "30")])
            return self._json({"hits": [{"stages": {"bm25": None, "dense": {"rank": 1, "score": 0.9}}}], "ms": 3.0})
        if path in smoke.PAGES:
            page = f"<p>{smoke.DISCLAIMER if Box.disclaimer else ''}</p>".encode()
            return self._send(200, page, "text/html", [("Content-Security-Policy", Box.csp)] if Box.csp else [])
        self._json({}, 404)

    def do_POST(self):
        q = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["question"]
        if len(q) > 300:
            return self._json({"error": "invalid"}, 422)
        if "Nonexistent" in q:
            return self._json({"state": "which_deal", "served_from": None, "claims": []})
        return self._json({"state": "answered", "served_from": "cache",
                           "claims": [{"link": "https://www.sec.gov/Archives/x.htm"}]})

    def log_message(self, *args):
        pass


@pytest.fixture
def box():
    Box.csp, Box.disclaimer, Box.searches = CSP, True, [0]
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Box)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_smoke_passes_against_a_healthy_box(box):
    problems = (smoke.check_health(box, {"git_sha": "g", "bundle_sha": "b", "facts_sha": "f"})
                + smoke.check_pages(box) + smoke.check_deals(box) + smoke.check_search(box, "fee")
                + smoke.check_ask(box, "fee", smoke.ANSWERED, served_from="cache", sec_link=True)
                + smoke.check_ask(box, smoke.NO_DEAL, {"which_deal"}) + smoke.check_invalid(box)
                + smoke.check_burst(box, "fee"))
    assert problems == []


def test_smoke_reports_a_stale_release_and_bare_pages(box):
    Box.csp, Box.disclaimer = None, False
    assert smoke.check_health(box, {"git_sha": "other"}) == ["health: git_sha is 'g', want 'other'"]
    problems = smoke.check_pages(box)
    assert any("no disclaimer" in p for p in problems) and any("CSP" in p for p in problems)


def test_cap_trip_reads_states_and_the_ledger(box):
    still = iter(["3|0.01", "3|0.01"])  # the ledger snapshot before and after, as `ledger_over_ssh` reads it
    got = smoke.cap_trip(box, "fresh question", "cached question", lambda: next(still))
    assert got["ledger_unchanged"] is True and got["budget_reached"] is False  # this fake box is not capped
    assert got["health_budget"] == "ok"
    moved = iter(["3|0.01", "4|0.02"])
    assert smoke.cap_trip(box, "fresh question", "cached question", lambda: next(moved))["ledger_unchanged"] is False


def test_the_ledger_is_read_over_ssh_as_the_service_user(monkeypatch):
    seen = []
    monkeypatch.setattr(smoke.subprocess, "check_output", lambda cmd, text: seen.append(cmd) or "3|0.01\n")
    assert smoke.ledger_over_ssh("root@box")() == "3|0.01"
    assert seen[0][:2] == ["ssh", "root@box"] and "sudo -u dtd sqlite3 /var/lib/dtd/budget.db" in seen[0][2]


def test_smoke_reports_a_dead_box_as_failures_not_a_traceback():
    with ThreadingHTTPServer(("127.0.0.1", 0), Box) as srv:
        dead = f"http://127.0.0.1:{srv.server_address[1]}"
    # the server is closed: connection refused
    assert smoke.check_health(dead, {}) == ["health: status 0"]
    assert smoke.check_deals(dead) and smoke.check_pages(dead) and smoke.check_invalid(dead)
    assert smoke.check_burst(dead, "q", tries=2) == ["burst: no 429 after 2 searches"]
