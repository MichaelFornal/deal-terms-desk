#!/usr/bin/env bash
# Ship HEAD to the Deal Terms Desk box. Safe to rerun: a release, bundle or site already on the box is kept, and an
# interrupted run resumes. Needs DTD_HOST, the ssh target (for example root@deals.forn.al).
set -euo pipefail
: "${DTD_HOST:?set DTD_HOST to the ssh target, for example root@deals.forn.al}"
BASE="${DTD_BASE:-https://deals.forn.al}"
cd "$(git rev-parse --show-toplevel)"
# Sourced first, so a missing helper fails the push before anything ships.
. deploy/hostport.sh

dirty() { [ -n "$(git status --porcelain)" ]; }
if dirty; then
  echo "refusing to deploy: the working tree is dirty; commit or stash first" >&2
  exit 1
fi

# Release gates: CI's checks plus the ones that need data/.
uv run pytest -q
uv run dtd facts --check
uv run dtd bundle
uv run dtd site --strict
if dirty; then
  echo "refusing to deploy: the release gates changed tracked files; review and commit them first" >&2
  exit 1
fi

SHA="$(git rev-parse HEAD)"
BUNDLE_SHA="$(uv run python -c 'import json; print(json.load(open("data/live/bundle.json"))["sha256"])')"
FACTS_SHA="$(uv run python -c 'import hashlib; print(hashlib.sha256(open("facts.json", "rb").read()).hexdigest())')"
REL="/srv/dtd/releases/$SHA"
BUN="/srv/dtd/bundles/$BUNDLE_SHA"
# Run a command in the release directory as the service user, with /etc/dtd/env loaded (it is root-only, so it is
# sourced as root and the values are passed through sudo).
LOAD_ENV="set -a; . /etc/dtd/env; set +a"
AS_DTD="sudo -E -u dtd env HOME=/var/lib/dtd"

# The env file holds the API key: refuse unless it is root-owned and mode 600.
if [ "$(ssh "$DTD_HOST" "stat -c '%U %a' /etc/dtd/env" 2>/dev/null || true)" != "root 600" ]; then
  echo "refusing to deploy: /etc/dtd/env must exist, owned by root, mode 600." >&2
  echo "  fix: write it from deploy/env.example, then: ssh $DTD_HOST 'chown root:root /etc/dtd/env && chmod 600 /etc/dtd/env'" >&2
  exit 1
fi

# The caps the box enforces (/etc/dtd/env, read as root) must be the caps the site publishes (facts.json, computed
# from deploy/hosting.json). Checked before anything ships.
caps_match() {  # $1 = "<DTD_MONTH_CAP_USD>|<DTD_DAY_CAP_USD>" as the box has them
  uv run python - "$1" <<'CAPS'
import json, sys
facts = json.load(open("facts.json"))
box = (sys.argv[1].split("|") + ["", ""])[:2]
bad = []
for env, key, raw in (("DTD_MONTH_CAP_USD", "m5_model_cap_usd", box[0]), ("DTD_DAY_CAP_USD", "m5_day_cap_usd", box[1])):
    want, raw = facts.get(key), raw.strip()
    if want is None:
        bad.append(f"facts.json has no {key} (fill in deploy/hosting.json, then run dtd facts)")
    elif not raw:
        bad.append(f"/etc/dtd/env does not set {env}; facts.json {key}={want}")
    else:
        try:
            have = float(raw)
        except ValueError:
            bad.append(f"/etc/dtd/env {env}={raw!r} is not a number; facts.json {key}={want}")
            continue
        if not abs(have - want) <= 1e-6:
            bad.append(f"/etc/dtd/env {env}={raw} but facts.json {key}={want}")
for b in bad:
    print(f"refusing to deploy: the box would enforce a cap the site does not publish: {b}", file=sys.stderr)
sys.exit(1 if bad else 0)
CAPS
}
BOX_CAPS="$(ssh "$DTD_HOST" "$LOAD_ENV; printf '%s|%s' \"\${DTD_MONTH_CAP_USD:-}\" \"\${DTD_DAY_CAP_USD:-}\"" || true)"
if ! caps_match "$BOX_CAPS"; then
  echo "  fix: set DTD_MONTH_CAP_USD and DTD_DAY_CAP_USD in /etc/dtd/env to the published caps, or correct" \
    "deploy/hosting.json and rerun dtd facts" >&2
  exit 1
fi

# The answer settings a release runs must be the ones calibration measured and the site publishes: thinking budget,
# output cap and model (facts.json m5_thinking_budget_tokens, m5_max_output_tokens, m5_price_model). Each is checked
# when its fact exists. Used before the swap on the new release's own config, and after it on /api/health.
config_match() {  # $1 = {"thinking_budget", "max_tokens", "model"} as JSON, $2 = what each problem is prefixed with
  uv run python - "$1" "$2" <<'CONFIG'
import json, sys
facts = json.load(open("facts.json"))
raw, prefix = sys.argv[1], sys.argv[2]
try:
    box = json.loads(raw.strip().splitlines()[-1])
except (ValueError, IndexError):
    box = None
if not isinstance(box, dict):
    print(f"{prefix}: could not read the release's answer settings from the box: {raw!r}", file=sys.stderr)
    sys.exit(1)
bad = []
for field, key in (("thinking_budget", "m5_thinking_budget_tokens"), ("max_tokens", "m5_max_output_tokens"),
                   ("model", "m5_price_model")):
    want = facts.get(key)
    if want is not None and box.get(field) != want:
        bad.append(f"the box runs {field}={box.get(field)!r} but facts.json {key}={want!r}")
for b in bad:
    print(f"{prefix}: {b}", file=sys.stderr)
sys.exit(1 if bad else 0)
CONFIG
}

# Code: the committed tree only, never the working tree. .complete marks a finished release. Bytecode is compiled
# here: the release is read-only to the service (ProtectSystem=strict), so Python could never cache it later.
if ! ssh "$DTD_HOST" test -f "$REL/.complete"; then
  ssh "$DTD_HOST" "rm -rf '$REL' && mkdir -p '$REL'"
  git archive --format=tar HEAD | ssh "$DTD_HOST" "tar -x --no-same-owner -C '$REL'"
  ssh "$DTD_HOST" "cd '$REL' && echo $SHA > GIT_SHA && UV_PYTHON_PREFERENCE=only-system UV_COMPILE_BYTECODE=1 uv sync --frozen --no-dev && touch .complete"
fi

# The new release's own config loader, run as the service runs it (its env, its user, its directory), before
# anything live moves. A loader that fails prints nothing, and that is refused too.
NEW_CFG="$(ssh "$DTD_HOST" "cd '$REL' && { $LOAD_ENV; $AS_DTD .venv/bin/python -c 'import json; from service.config import from_env; c = from_env(); print(json.dumps(dict(thinking_budget=c.thinking_budget, max_tokens=c.max_tokens, model=c.model)))'; }" || true)"
if ! config_match "$NEW_CFG" "refusing to switch"; then
  echo "  fix: set DTD_THINKING_BUDGET, DTD_MAX_TOKENS and DTD_MODEL in /etc/dtd/env to the calibrated settings, or" \
    "rerun calibration and dtd facts; the live release is untouched" >&2
  exit 1
fi

# Bundle: only when the box lacks this exact file. Resumable, then checked against its sha256.
if ! ssh "$DTD_HOST" test -f "$BUN/live.db"; then
  ssh "$DTD_HOST" "mkdir -p '$BUN'"
  rsync -a --partial data/live/live.db "$DTD_HOST:$BUN/live.db.part"
  ssh "$DTD_HOST" "cd '$BUN' && echo '$BUNDLE_SHA  live.db.part' | sha256sum -c --quiet - && mv live.db.part live.db"
fi
rsync -a data/live/bundle.json "$DTD_HOST:$BUN/bundle.json"
ssh "$DTD_HOST" "ln -sfn '$BUN/live.db' '$REL/live.db'"

# Site: rendered from this commit's facts.json.
rsync -a --delete site/dist/ "$DTD_HOST:$REL/site/dist/"

# rsync -a keeps the sender's owner, and macOS's openrsync has no --chown, so ownership is set on the box: the
# release (code, venv, site) and the bundle belong to root, and the service user can only read them.
ssh "$DTD_HOST" "chown -R root:root '$REL' '$BUN'"

# The embedding model, downloaded once into the service's cache, as the service user.
ssh "$DTD_HOST" "cd '$REL' && { $LOAD_ENV; $AS_DTD .venv/bin/python -c 'from retrieval.models import Embedder; Embedder().embed_query(\"warm up\")'; }"

# Validate the new config before touching anything live: a bad Caddyfile or unit leaves the old release serving.
# The unit is verified with its path pointed at this release, since `current` does not move yet.
if ! ssh "$DTD_HOST" "caddy validate --adapter caddyfile --config '$REL/deploy/Caddyfile' \
  && T=\$(mktemp -d) && sed 's#/srv/dtd/current#$REL#g' '$REL/deploy/dtd.service' > \"\$T/dtd.service\" \
  && systemd-analyze verify \"\$T/dtd.service\"; r=\$?; rm -rf \"\$T\"; exit \$r"; then
  echo "refusing to switch: the new Caddyfile or dtd.service failed validation; the live release is untouched" >&2
  exit 1
fi

# Switch: atomic symlink swap, config from the release, restart. The previous release is kept for the revert.
PREV="$(ssh "$DTD_HOST" "readlink /srv/dtd/current" || true)"
install_release() {  # $1 = release directory on the box
  ssh "$DTD_HOST" "ln -sfn '$1' /srv/dtd/current.next && mv -T /srv/dtd/current.next /srv/dtd/current \
  && install -m 644 '$1/deploy/Caddyfile' /etc/caddy/Caddyfile \
  && install -m 644 '$1/deploy/dtd.service' /etc/systemd/system/dtd.service \
  && systemctl daemon-reload && systemctl enable --now caddy dtd && systemctl reload caddy && systemctl restart dtd"
}
# Leave the new release: swap back to the previous one, reinstall its config and restart, then fail the push.
revert() {  # $1 = why
  if [ -n "$PREV" ]; then
    echo "$1; reverting to the previous release ${PREV##*/}" >&2
    install_release "$PREV" || echo "the revert itself failed; fix by hand: ln -sfn $PREV /srv/dtd/current" >&2
    echo "reverted from $SHA to ${PREV##*/}; the push failed" >&2
  else
    echo "$1, and there is no previous release to revert to" >&2
  fi
  exit 1
}
# Any step after the swap can fail (config install, daemon-reload, enable, reload, restart): `current` has moved by
# then, so a failure takes the revert, not a bare exit.
if ! install_release "$REL"; then
  revert "installing release $SHA failed"
fi

# The box must now serve exactly this code, bundle and facts.
matches() {
  uv run python - "$1" "$SHA" "$BUNDLE_SHA" "$FACTS_SHA" <<'PY'
import json, sys
try:
    h = json.loads(sys.argv[1])
except ValueError:
    sys.exit(1)
sys.exit(0 if [h.get("git_sha"), h.get("bundle_sha"), h.get("facts_sha")] == sys.argv[2:] else 1)
PY
}
# Pin the host to the box's own address for the poll: the operator's DNS cache can lag new records for up to the
# zone's negative TTL (an NXDOMAIN seen before the records existed), while TLS, Caddy and the service are still
# checked through the public HTTPS path. host_port comes from deploy/hostport.sh, sourced at the top.
BOX_IP="$(ssh "$DTD_HOST" "hostname -I" | tr -s ' \t' '\n\n' | grep -m1 '\.' || true)"
PIN=()
if [ -n "$BOX_IP" ]; then
  PIN=(--resolve "$(host_port "$BASE"):$BOX_IP")
else
  echo "warning: could not find the box's IPv4 address; polling health through the operator's DNS, which may lag new records" >&2
fi
live=""
for _ in $(seq 60); do
  HEALTH="$(curl -fsS --max-time 10 ${PIN[@]+"${PIN[@]}"} "$BASE/api/health" || echo '{}')"
  if matches "$HEALTH"; then live=1; break; fi
  sleep 2
done
if [ -z "$live" ]; then
  revert "release $SHA never reported healthy"
fi

# Confirmation: the running service reports the calibrated answer settings too (checked before the swap on the new
# release's config). The release is already healthy, so a mismatch fails the push without a revert.
if ! config_match "$HEALTH" "answer settings mismatch"; then
  echo "  fix: set DTD_THINKING_BUDGET, DTD_MAX_TOKENS and DTD_MODEL in /etc/dtd/env to the calibrated settings, or" \
    "rerun calibration and dtd facts; the release is healthy and stays live" >&2
  exit 1
fi

# Warm the example answers on every push: a changed retriever, model or example list changes the prompt, and cached
# examples cost nothing. Every example must come back with an answering state.
WARM="$(ssh "$DTD_HOST" "cd /srv/dtd/current && { $LOAD_ENV; $AS_DTD .venv/bin/dtd warm --examples site/examples.json; }" | tail -n 1)"
if ! uv run python -c 'import json, sys; got = json.loads(sys.argv[1]); sys.exit(0 if got["asked"] > 0 and set(got["states"]) <= {"answered", "not_stated", "unfiled_schedule"} else 1)' "$WARM"; then
  echo "warm failed: an example did not come back answered, not_stated or unfiled_schedule: $WARM" >&2
  exit 1
fi
echo "deployed $SHA"
