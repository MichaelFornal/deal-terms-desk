#!/usr/bin/env bash
# Ship HEAD to the Deal Terms Desk box. Safe to rerun: a release, bundle or site already on the box is kept, and an
# interrupted run resumes. Needs DTD_HOST, the ssh target (for example root@deals.forn.al).
set -euo pipefail
: "${DTD_HOST:?set DTD_HOST to the ssh target, for example root@deals.forn.al}"
BASE="${DTD_BASE:-https://deals.forn.al}"
cd "$(git rev-parse --show-toplevel)"

dirty() { [ -n "$(git status --porcelain)" ]; }
if dirty; then
  echo "refusing to deploy: the working tree is dirty; commit or stash first" >&2
  exit 1
fi

# Release gates: CI's checks plus the ones that need data/.
uv run pytest -q
uv run dtd facts --check
uv run dtd bundle
uv run dtd site
if dirty; then
  echo "refusing to deploy: the release gates changed tracked files; review and commit them first" >&2
  exit 1
fi

SHA="$(git rev-parse HEAD)"
BUNDLE_SHA="$(uv run python -c 'import json; print(json.load(open("data/live/bundle.json"))["sha256"])')"
FACTS_SHA="$(uv run python -c 'import hashlib; print(hashlib.sha256(open("facts.json", "rb").read()).hexdigest())')"
TEMPLATE_SHA="$(uv run python -c 'from answer.prompt import TEMPLATE_SHA; print(TEMPLATE_SHA)')"
REL="/srv/dtd/releases/$SHA"
BUN="/srv/dtd/bundles/$BUNDLE_SHA"
BEFORE="$(curl -fsS "$BASE/api/health" || echo '{}')"
AS_DTD="set -a; . /etc/dtd/env; set +a; sudo -E -u dtd env HOME=/var/lib/dtd"

# Code: the committed tree only, never the working tree. .complete marks a finished release.
if ! ssh "$DTD_HOST" test -f "$REL/.complete"; then
  ssh "$DTD_HOST" "rm -rf $REL && mkdir -p $REL"
  git archive --format=tar HEAD | ssh "$DTD_HOST" "tar -x -C $REL"
  ssh "$DTD_HOST" "cd $REL && echo $SHA > GIT_SHA && UV_PYTHON_PREFERENCE=only-system uv sync --frozen --no-dev && touch .complete"
fi

# Bundle: only when the box lacks this exact file. Resumable, then checked against its sha256.
if ! ssh "$DTD_HOST" test -f "$BUN/live.db"; then
  ssh "$DTD_HOST" "mkdir -p $BUN"
  rsync -a --partial data/live/live.db "$DTD_HOST:$BUN/live.db.part"
  ssh "$DTD_HOST" "cd $BUN && echo '$BUNDLE_SHA  live.db.part' | sha256sum -c --quiet - && mv live.db.part live.db"
fi
rsync -a data/live/bundle.json "$DTD_HOST:$BUN/bundle.json"
ssh "$DTD_HOST" "ln -sfn $BUN/live.db $REL/live.db"

# Site: rendered from this commit's facts.json.
rsync -a --delete site/dist/ "$DTD_HOST:$REL/site/dist/"

# The embedding model, downloaded once into the service's cache, as the service user.
ssh "$DTD_HOST" "cd $REL && $AS_DTD .venv/bin/python -c 'from retrieval.models import Embedder; Embedder().embed_query(\"warm up\")'"

# Switch: atomic symlink swap, config from the release, restart.
ssh "$DTD_HOST" "ln -sfn $REL /srv/dtd/current.next && mv -T /srv/dtd/current.next /srv/dtd/current \
  && install -m 644 $REL/deploy/Caddyfile /etc/caddy/Caddyfile \
  && install -m 644 $REL/deploy/dtd.service /etc/systemd/system/dtd.service \
  && systemctl daemon-reload && systemctl enable --now caddy dtd && systemctl reload caddy && systemctl restart dtd"

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
live=""
for _ in $(seq 60); do
  if matches "$(curl -fsS "$BASE/api/health" || echo '{}')"; then live=1; break; fi
  sleep 2
done
if [ -z "$live" ]; then
  echo "the box never reported this release. Earlier releases are in /srv/dtd/releases: roll back with" >&2
  echo "  ssh $DTD_HOST 'ln -sfn /srv/dtd/releases/<sha> /srv/dtd/current && systemctl restart dtd'" >&2
  exit 1
fi

# Re-warm the example answers whenever the prompt could have changed (new bundle or new template).
OLD="$(uv run python -c 'import json, sys; h = json.loads(sys.argv[1]); print(h.get("bundle_sha", ""), h.get("template_sha", ""))' "$BEFORE")"
if [ "$OLD" != "$BUNDLE_SHA $TEMPLATE_SHA" ]; then
  ssh "$DTD_HOST" "cd /srv/dtd/current && $AS_DTD .venv/bin/dtd warm --examples site/examples.json"
fi
echo "deployed $SHA"
