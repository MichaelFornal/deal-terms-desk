#!/usr/bin/env bash
# One-time, idempotent setup of the Deal Terms Desk box (Ubuntu 24.04 LTS). Run as root from the repo root:
#   ssh root@$HOST 'bash -s' < deploy/provision.sh
# Then write /etc/dtd/env (see deploy/env.example; owner root:root, mode 600) and run deploy/push.sh.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
# Ubuntu's needrestart would ask which services to restart after an upgrade; "a" restarts them without asking.
export NEEDRESTART_MODE=a
# stdin is this script under `bash -s`, so every apt command reads /dev/null and never prompts.
APT_OPTS=(-yq -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)

apt-get update -q </dev/null
apt-get upgrade "${APT_OPTS[@]}" </dev/null
apt-get install "${APT_OPTS[@]}" unattended-upgrades ufw curl ca-certificates gnupg debian-keyring \
  debian-archive-keyring apt-transport-https sqlite3 rsync </dev/null
dpkg-reconfigure -f noninteractive unattended-upgrades </dev/null

# Firewall: ssh and the web only.
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Keys only. Never lock out the only way in: refuse unless root already has an authorized key.
if [ ! -s /root/.ssh/authorized_keys ]; then
  echo "refusing to disable password login: /root/.ssh/authorized_keys is missing or empty" >&2
  exit 1
fi
install -d /etc/ssh/sshd_config.d
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n' \
  > /etc/ssh/sshd_config.d/10-dtd.conf
# Ubuntu 24.04 socket-activates sshd, so ssh.service may be inactive; try-reload-or-restart reloads when active,
# does nothing when inactive, and the socket-activated sshd reads the new drop-in on its next start.
systemctl try-reload-or-restart ssh

# Caddy from its official apt repository.
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q </dev/null
  apt-get install "${APT_OPTS[@]}" caddy </dev/null
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
