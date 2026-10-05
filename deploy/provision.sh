#!/usr/bin/env bash
# One-time, idempotent setup of the Deal Terms Desk box (Ubuntu 24.04 LTS). Run as root from the repo root:
#   ssh root@$HOST 'bash -s' < deploy/provision.sh
# Then write /etc/dtd/env (see deploy/env.example; root-owned, mode 0600) and run deploy/push.sh.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update -q
apt-get upgrade -yq
apt-get install -yq unattended-upgrades ufw curl ca-certificates gnupg debian-keyring debian-archive-keyring \
  apt-transport-https sqlite3 rsync
dpkg-reconfigure -f noninteractive unattended-upgrades

# Firewall: ssh and the web only.
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Keys only.
install -d /etc/ssh/sshd_config.d
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n' \
  > /etc/ssh/sshd_config.d/10-dtd.conf
systemctl reload ssh

# Caddy from its official apt repository.
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q
  apt-get install -yq caddy
fi

# uv, using the system Python (Ubuntu 24.04 ships 3.12, which the project requires).
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi

# The service user and its directories.
id dtd >/dev/null 2>&1 || useradd --system --home-dir /var/lib/dtd --shell /usr/sbin/nologin dtd
install -d -o root -g root -m 755 /srv/dtd /srv/dtd/releases /srv/dtd/bundles
install -d -o dtd -g dtd -m 750 /var/lib/dtd /var/lib/dtd/fastembed /var/lib/dtd/huggingface
install -d -o root -g root -m 700 /etc/dtd

# Keep the journal small.
install -d /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=200M\n' > /etc/systemd/journald.conf.d/10-dtd.conf
systemctl restart systemd-journald

echo "provisioned; next: write /etc/dtd/env (mode 0600), then run deploy/push.sh"
