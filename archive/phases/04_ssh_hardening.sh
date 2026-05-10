#!/bin/bash
set -euo pipefail

SSH_KEY_PATH="${SNIPPET_DIR}/ct${CT_ID}_ed25519"
ensure_ed25519_key "$SSH_KEY_PATH" "ct${CT_ID}-provisioning"

pct exec "$CT_ID" -- bash -c 'mkdir -p /root/.ssh && chmod 700 /root/.ssh'
pct push "$CT_ID" "${SSH_KEY_PATH}.pub" /root/.ssh/authorized_keys
pct exec "$CT_ID" -- chmod 600 /root/.ssh/authorized_keys

cat > /tmp/sshd_hardened.conf <<'SSHD_CONFIG'
Port 22
PermitRootLogin prohibit-password
PasswordAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
UsePAM yes
X11Forwarding no
PrintMotd no
AcceptEnv LANG LC_*
Subsystem sftp /usr/lib/openssh/sftp-server
SSHD_CONFIG

pct push "$CT_ID" /tmp/sshd_hardened.conf /etc/ssh/sshd_config
rm -f /tmp/sshd_hardened.conf

pct exec "$CT_ID" -- bash -c 'ssh-keygen -A'
pct exec "$CT_ID" -- systemctl restart sshd

# Create the application user
pct exec "$CT_ID" -- useradd -r -m -d "$APP_DIR" -s /bin/bash "$APP_USER"