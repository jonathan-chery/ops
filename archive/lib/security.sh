# File: lib/security.sh

fw_security_harden() {
    echo "--> [SEC] Hardening Container OS..."

    if fw_get_state "security_hardened"; then
        echo "    [SKIP] OS already hardened."
        return 0
    fi

    # 1. SSH Hardening
    local ssh_key="${APP_SECRETS_DIR}/ssh_ed25519"
    if [[ ! -f "$ssh_key" ]]; then
        ssh-keygen -t ed25519 -f "$ssh_key" -N "" -C "${APP_NAME}-provisioning" -q
    fi

    pct exec "$CT_ID" -- bash -c 'mkdir -p /root/.ssh && chmod 700 /root/.ssh'
    pct push "$CT_ID" "${ssh_key}.pub" /root/.ssh/authorized_keys
    pct exec "$CT_ID" -- chmod 600 /root/.ssh/authorized_keys

    cat > /tmp/sshd_hardened.conf <<'SSHD_CONFIG'
Port 22
PermitRootLogin prohibit-password
PasswordAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
KbdInteractiveAuthentication no
UsePAM yes
X11Forwarding no
PrintMotd no
AcceptEnv LANG LC_*
Subsystem sftp /usr/lib/openssh/sftp-server
SSHD_CONFIG

    pct push "$CT_ID" /tmp/sshd_hardened.conf /etc/ssh/sshd_config
    rm -f /tmp/sshd_hardened.conf

    pct exec "$CT_ID" -- bash -c 'ssh-keygen -A' >/dev/null 2>&1
    pct exec "$CT_ID" -- systemctl restart sshd

    # 2. Application User Creation
    if ! pct exec "$CT_ID" -- id "$APP_USER" &>/dev/null; then
        pct exec "$CT_ID" -- useradd -r -m -d "$APP_DIR" -s /bin/bash "$APP_USER"
    fi

    fw_set_state "security_hardened"
    echo "    [OK] SSH secured and user '${APP_USER}' created."
}

fw_security_audit() {
    echo "--> [SEC] Running Post-Deployment Audit..."
    echo "    Listening Ports inside CT:"
    pct exec "$CT_ID" -- ss -tlnp | sed 's/^/      /'
    echo "    [OK] Audit complete."
}

# Helper to run a command safely as the unprivileged user
fw_exec_as_user() {
    local run_user="$1"
    local run_dir="$2"
    local cmd="$3"
    pct exec "$CT_ID" -- su - "$run_user" -s /bin/bash -c "cd ${run_dir} && ${cmd}"
}

# Helper to run a command as user with specific environment variables
fw_exec_as_user_with_env() {
    local run_user="$1"
    local run_dir="$2"
    local env_vars="$3"
    local cmd="$4"
    pct exec "$CT_ID" -- su - "$run_user" -s /bin/bash -c "cd ${run_dir} && export ${env_vars} && ${cmd}"
}