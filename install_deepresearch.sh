#!/bin/bash
# Scope: Provision LXC CT 180 for deep-research-web-ui on Ubuntu 24.04
# Network: Internal — vmbr1, 10.0.0.0/24, gateway 10.0.0.254, storage local
set -euo pipefail

# ============================================================
# Configuration — Internal Network
# ============================================================
CT_ID=180
RELEASE_TAG="v1.2.0"
REPO_URL="https://github.com/AnotiaWang/deep-research-web-ui.git"
APP_DIR="/opt/deep-research-web-ui"
APP_USER="deepresearch"
APP_PORT=3000
CT_HOSTNAME="deepresearch"

# --- Internal Network (vmbr1) ---
CT_IP="10.0.0.180"
CT_IP_CIDR="10.0.0.180/24"
CT_GW="10.0.0.254"
CT_DNS="1.1.1.1 8.8.8.8"
CT_BRIDGE="vmbr1"

# --- Storage ---
CT_STORAGE="local"
CT_DISK="20"

# --- Resources ---
CT_MEM=4096
CT_SWAP=2048
CT_CORES=2
NODE_MAJOR=22

# --- Paths ---
SNIPPET_DIR="${SNIPPET_DIR:-/var/lib/vz/snippets}"
HEARTBEAT_DIR="/root/heartbeats"
PHASE_FILE="/tmp/ct180_deployment_phases"
TEMPLATE=""

# ============================================================
# Idempotent Secret & Key Helpers
# ============================================================

# Generate a secret only if the file is missing; returns the value via stdout.
ensure_secret() {
    local filepath="$1"
    local desc="$2"
    if [[ -f "$filepath" ]] && [[ -s "$filepath" ]]; then
        echo "[SKIP] ${desc} already exists at ${filepath}. Reusing." >&2
        cat "$filepath"
        return 0
    fi
    local secret
    secret=$(openssl rand -base64 32 | tr -d '=/+')
    echo "$secret" > "$filepath"
    chmod 600 "$filepath"
    echo "[NEW] ${desc} generated at ${filepath}." >&2
    echo "$secret"
}

ensure_long_secret() {
    local filepath="$1"
    local desc="$2"
    if [[ -f "$filepath" ]] && [[ -s "$filepath" ]]; then
        echo "[SKIP] ${desc} already exists at ${filepath}. Reusing." >&2
        cat "$filepath"
        return 0
    fi
    local secret
    secret=$(openssl rand -base64 48 | tr -d '=/+')
    echo "$secret" > "$filepath"
    chmod 600 "$filepath"
    echo "[NEW] ${desc} generated at ${filepath}." >&2
    echo "$secret"
}

# Validate an existing Ed25519 key; only regenerate if missing or invalid.
ensure_ed25519_key() {
    local keypath="$1"
    local comment="$2"

    if [[ -f "$keypath" ]] && [[ -f "${keypath}.pub" ]]; then
        local keytype
        if keytype=$(ssh-keygen -l -f "${keypath}.pub" 2>/dev/null | awk '{print $2}') && [[ "$keytype" == "ED25519" ]]; then
            echo "[SKIP] Ed25519 key already exists and is valid at ${keypath}. Skipping generation."
            return 0
        fi
        echo "[REGEN] Key at ${keypath} is not Ed25519 (found: ${keytype:-invalid}). Regenerating..."
        rm -f "$keypath" "${keypath}.pub"
    else
        rm -f "$keypath" "${keypath}.pub"
    fi

    ssh-keygen -t ed25519 -f "$keypath" -N "" -C "$comment" -q
    echo "[NEW] Ed25519 key generated at ${keypath}."
}

# ============================================================
# Storage Validation
# ============================================================
validate_storage() {
    local storage="$1"
    if ! pvesm status 2>/dev/null | awk '{print $1}' | grep -qx "$storage"; then
        echo "ERROR: Storage '$storage' not found in Proxmox."
        echo "Available storage:"
        pvesm status
        return 1
    fi

    local content_line
    content_line=$(awk -v stor="$storage" '
        /^[^ \t]/ {
            split($0, arr, ":")
            gsub(/[[:space:]]/, "", arr[2])
            current=arr[2]
        }
        current == stor && /content/ { print; found=1; exit }
    ' /etc/pve/storage.cfg 2>/dev/null || true)

    if echo "$content_line" | grep -q "rootdir" 2>/dev/null; then
        echo "[OK] Storage '$storage' supports rootdir."
        return 0
    fi

    if pvesm list "$storage" --content rootdir &>/dev/null; then
        echo "[OK] Storage '$storage' supports rootdir (via pvesm)."
        return 0
    fi

    echo "WARNING: Storage '$storage' may not support rootdir."
    echo "  If creation fails, add rootdir to the storage content types:"
    echo "    pvesm set ${storage} --content vztmpl,iso,rootdir"
    return 0
}

echo "[INFO] Validating storage: ${CT_STORAGE}"
validate_storage "$CT_STORAGE"

# ============================================================
# Phase Tracking Functions
# ============================================================
get_state() {
    local phase="$1"
    [[ -f "$PHASE_FILE" ]] && grep -qx "$phase" "$PHASE_FILE" 2>/dev/null
}

set_state() {
    local phase="$1"
    echo "$phase" >> "$PHASE_FILE"
}

reset_phases() {
    rm -f "$PHASE_FILE"
}

# ============================================================
# Phase 1: Pre-flight — Template Discovery & Download
# ============================================================
if ! get_state "phase1_template_ready"; then
    echo "=== Phase 1: Pre-flight ==="

    mkdir -p "$SNIPPET_DIR"

    pveam update

    TEMPLATE=$(pveam available 2>/dev/null | grep -i 'ubuntu-24.04' | grep 'standard' | awk '{print $NF}' | sort -V | tail -1)

    if [[ -z "$TEMPLATE" ]]; then
        echo "ERROR: Ubuntu 24.04 template not found in available templates."
        echo "Listing all available Ubuntu templates:"
        pveam available 2>/dev/null | grep -i 'ubuntu' || echo "  (none found)"
        echo ""
        echo "All system templates:"
        pveam available --section system 2>/dev/null || true
        exit 1
    fi

    echo "Selected template: $TEMPLATE"

    if pveam list local 2>/dev/null | grep -q "$TEMPLATE"; then
        echo "Template already cached: $TEMPLATE"
    else
        echo "Downloading template: $TEMPLATE"
        pveam download local "$TEMPLATE"
    fi

    set_state "phase1_template_ready"
    echo "Phase 1 complete."
else
    TEMPLATE=$(pveam list local 2>/dev/null | grep -i 'ubuntu-24.04' | grep 'standard' | awk '{print $NF}' | sort -V | tail -1)
    if [[ -z "$TEMPLATE" ]]; then
        TEMPLATE=$(pveam available 2>/dev/null | grep -i 'ubuntu-24.04' | grep 'standard' | awk '{print $NF}' | sort -V | tail -1)
    fi
    echo "Phase 1 already complete. Using cached template: $TEMPLATE"
fi

if [[ -z "$TEMPLATE" ]]; then
    echo "ERROR: Could not determine template name. Remove ${PHASE_FILE} and re-run."
    exit 1
fi

# ============================================================
# Phase 2: Destroy Existing CT (Clean-Slate Teardown)
# ============================================================
if ! get_state "phase2_ct_destroyed"; then
    echo "=== Phase 2: Destroy Existing CT ==="

    if pct list 2>/dev/null | awk '{print $1}' | grep -qx "${CT_ID}"; then
        echo "Stopping CT ${CT_ID}..."
        if pct status "$CT_ID" 2>/dev/null | grep -q "running"; then
            pct stop "$CT_ID"
            sleep 5
        fi
        echo "Destroying CT ${CT_ID}..."
        pct destroy "$CT_ID" --purge 2>/dev/null || pct destroy "$CT_ID"
        echo "CT ${CT_ID} destroyed."
    else
        echo "CT ${CT_ID} does not exist. Nothing to destroy."
    fi

    # Full clean-slate reset — preserve only template phase
    reset_phases
    set_state "phase1_template_ready"
    set_state "phase2_ct_destroyed"
    echo "Phase 2 complete."
else
    echo "Phase 2 already complete. Skipping."
fi

# ============================================================
# Phase 3: Create CT & Configure Static Networking
# ============================================================
if ! get_state "phase3_ct_created"; then
    echo "=== Phase 3: Create CT ==="

    # Idempotent: reuse existing secrets if they already exist
    ROOT_PASSWD=$(ensure_secret "${SNIPPET_DIR}/deepresearch_root_passwd.txt" "Root password")
    NEXTAUTH_SECRET=$(ensure_long_secret "${SNIPPET_DIR}/deepresearch_nextauth_secret.txt" "NEXTAUTH secret")

    echo "Creating CT ${CT_ID} on storage ${CT_STORAGE}, bridge ${CT_BRIDGE}..."
    pct create "$CT_ID" "local:vztmpl/${TEMPLATE}" \
        --hostname "$CT_HOSTNAME" \
        --memory "$CT_MEM" \
        --swap "$CT_SWAP" \
        --cores "$CT_CORES" \
        --storage "$CT_STORAGE" \
        --rootfs "${CT_STORAGE}:${CT_DISK}" \
        --net0 "name=eth0,bridge=${CT_BRIDGE},ip=${CT_IP_CIDR},gw=${CT_GW}" \
        --nameserver "$CT_DNS" \
        --password "$ROOT_PASSWD" \
        --unprivileged 1 \
        --features "nesting=1" \
        --onboot 1 \
        --startup "order=18,up=30,down=30"

    pct start "$CT_ID"
    echo "Waiting for CT ${CT_ID} to boot..."
    sleep 10

    for i in $(seq 1 30); do
        if pct exec "$CT_ID" -- bash -c 'ping -c1 -W2 1.1.1.1 &>/dev/null'; then
            echo "Network is ready."
            break
        fi
        if [[ "$i" -eq 30 ]]; then
            echo "ERROR: Network did not become ready within 150 seconds."
            echo "  Verify vmbr1 is configured and gateway ${CT_GW} is reachable."
            echo "  Diagnostics:"
            pct exec "$CT_ID" -- ip addr show eth0 2>/dev/null || true
            pct exec "$CT_ID" -- ip route show 2>/dev/null || true
            exit 1
        fi
        echo "Waiting for network... ($i/30)"
        sleep 5
    done

    pct exec "$CT_ID" -- bash -c 'echo "fs.inotify.max_user_watches=524288" >> /etc/sysctl.conf'
    pct exec "$CT_ID" -- sysctl -p /etc/sysctl.conf

    pct exec "$CT_ID" -- timedatectl set-timezone UTC

    set_state "phase3_ct_created"
    echo "Phase 3 complete."
else
    echo "Phase 3 already complete. Skipping."
fi

# ============================================================
# Phase 4: SSH Hardening & Ed25519 Key Generation
# ============================================================
if ! get_state "phase4_ssh_hardened"; then
    echo "=== Phase 4: SSH Hardening & Ed25519 Keys ==="

    # Idempotent: reuse existing key if valid
    SSH_KEY_PATH="${SNIPPET_DIR}/ct${CT_ID}_ed25519"
    ensure_ed25519_key "$SSH_KEY_PATH" "ct${CT_ID}-provisioning"

    # Always push the public key into the CT (required for new/recreated CTs)
    pct exec "$CT_ID" -- bash -c 'mkdir -p /root/.ssh && chmod 700 /root/.ssh'
    pct push "$CT_ID" "${SSH_KEY_PATH}.pub" /root/.ssh/authorized_keys
    pct exec "$CT_ID" -- chmod 600 /root/.ssh/authorized_keys

    # Render hardened SSH config on host side, then push
    cat > /tmp/sshd_hardened.conf <<'SSHD_CONFIG'
# Hardened SSH configuration — Ed25519 key-only access
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

    pct exec "$CT_ID" -- useradd -r -m -d /opt/deep-research-web-ui -s /bin/bash deepresearch

    set_state "phase4_ssh_hardened"
    echo "Phase 4 complete."
else
    echo "Phase 4 already complete. Skipping."
fi

# ============================================================
# Phase 5: Install Dependencies (Node.js 22, pnpm, build tools)
# ============================================================
if ! get_state "phase5_deps_installed"; then
    echo "=== Phase 5: Install Dependencies ==="

    pct exec "$CT_ID" -- bash <<'INNER_APT'
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y
apt-get install -y curl wget git build-essential python3 ca-certificates gnupg
INNER_APT

    # Purge any prior NodeSource config, then install Node.js 22 LTS
    pct exec "$CT_ID" -- bash -c 'rm -f /etc/apt/sources.list.d/nodesource.list /etc/apt/keyrings/nodesource.gpg'
    pct exec "$CT_ID" -- bash -c "curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR}.x | bash -"
    pct exec "$CT_ID" -- bash <<'INNER_NODE'
export DEBIAN_FRONTEND=noninteractive
apt-get install -y nodejs
INNER_NODE

    echo "Node.js version:"
    pct exec "$CT_ID" -- node --version
    echo "npm version:"
    pct exec "$CT_ID" -- npm --version

    # Flush any stale corepack cache, then activate pnpm fresh
    pct exec "$CT_ID" -- bash -c 'rm -rf /root/.cache/node/corepack'
    pct exec "$CT_ID" -- corepack enable
    pct exec "$CT_ID" -- corepack prepare pnpm@latest --activate

    echo "pnpm version:"
    pct exec "$CT_ID" -- pnpm --version

    set_state "phase5_deps_installed"
    echo "Phase 5 complete."
else
    echo "Phase 5 already complete. Skipping."
fi

# ============================================================
# Phase 6: Clone, Build & Configure Application
# ============================================================
if ! get_state "phase6_app_deployed"; then
    echo "=== Phase 6: Deploy Application ==="

    # Preserve user .env if it exists (API keys, secrets)
    pct exec "$CT_ID" -- bash -c "if [ -f ${APP_DIR}/.env ]; then cp ${APP_DIR}/.env /tmp/deepresearch_env_backup; echo '[BACKUP] Preserved existing .env with user API keys.'; else echo '[SKIP] No existing .env to preserve.'; fi"

    # Idempotent: remove stale checkout before cloning
    pct exec "$CT_ID" -- bash -c "rm -rf ${APP_DIR}"

    echo "Cloning repository at tag ${RELEASE_TAG}..."
    pct exec "$CT_ID" -- git clone --branch "$RELEASE_TAG" --depth 1 "$REPO_URL" "$APP_DIR"

    pct exec "$CT_ID" -- chown -R "${APP_USER}:${APP_USER}" "$APP_DIR"

    echo "Installing dependencies..."
    pct exec "$CT_ID" -- su - "$APP_USER" -s /bin/bash <<INNER_INSTALL
cd ${APP_DIR}
pnpm install --frozen-lockfile 2>/dev/null || pnpm install
INNER_INSTALL

    echo "Building application (this may take several minutes)..."
    pct exec "$CT_ID" -- su - "$APP_USER" -s /bin/bash <<INNER_BUILD
cd ${APP_DIR}
pnpm build
INNER_BUILD

    # Restore user .env if it was backed up, otherwise push template
    if pct exec "$CT_ID" -- test -f /tmp/deepresearch_env_backup; then
        echo "[RESTORE] Restoring preserved .env with user API keys."
        pct exec "$CT_ID" -- bash -c "cp /tmp/deepresearch_env_backup ${APP_DIR}/.env && rm -f /tmp/deepresearch_env_backup"
        pct exec "$CT_ID" -- chown "${APP_USER}:${APP_USER}" "${APP_DIR}/.env"
        pct exec "$CT_ID" -- chmod 600 "${APP_DIR}/.env"
    else
        NEXTAUTH_SECRET_VAL=$(cat "${SNIPPET_DIR}/${CT_HOSTNAME}_nextauth_secret.txt")
        cat > /tmp/deepresearch_env <<INNER_ENV
NEXTAUTH_SECRET="${NEXTAUTH_SECRET_VAL}"
NEXTAUTH_URL="http://${CT_IP}:${APP_PORT}"
# OPENAI_API_KEY=
# GOOGLE_API_KEY=
# GOOGLE_SEARCH_API_KEY=
# DEEPSEEK_API_KEY=
# OPENROUTER_API_KEY=
PORT=${APP_PORT}
NODE_ENV=production
INNER_ENV
        pct push "$CT_ID" /tmp/deepresearch_env "${APP_DIR}/.env"
        rm -f /tmp/deepresearch_env
        pct exec "$CT_ID" -- chown "${APP_USER}:${APP_USER}" "${APP_DIR}/.env"
        pct exec "$CT_ID" -- chmod 600 "${APP_DIR}/.env"
        echo "[NEW] Template .env pushed."
    fi

    set_state "phase6_app_deployed"
    echo "Phase 6 complete."
else
    echo "Phase 6 already complete. Skipping."
fi

# ============================================================
# Phase 7: Systemd Service Orchestration
# ============================================================
if ! get_state "phase7_service_configured"; then
    echo "=== Phase 7: Systemd Service ==="

    cat > /tmp/deepresearch_start.sh <<'STARTSCRIPT'
#!/bin/bash
set -euo pipefail
cd /opt/deep-research-web-ui
export NODE_ENV=production
export PORT=3000
exec pnpm start
STARTSCRIPT

    pct push "$CT_ID" /tmp/deepresearch_start.sh "${APP_DIR}/start.sh"
    pct exec "$CT_ID" -- chmod 755 "${APP_DIR}/start.sh"
    pct exec "$CT_ID" -- chown "${APP_USER}:${APP_USER}" "${APP_DIR}/start.sh"
    rm -f /tmp/deepresearch_start.sh

    cat > /tmp/deepresearch.service <<'UNITFILE'
[Unit]
Description=Deep Research Web UI — Next.js Application
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=deepresearch
Group=deepresearch
WorkingDirectory=/opt/deep-research-web-ui
ExecStart=/opt/deep-research-web-ui/start.sh
Restart=on-failure
RestartSec=10
StartLimitIntervalSec=60
StartLimitBurst=3

# Security hardening
NoNewPrivileges=false
ProtectSystem=strict
ProtectHome=false
ReadWritePaths=/opt/deep-research-web-ui
PrivateTmp=true

# Environment
Environment=NODE_ENV=production
EnvironmentFile=/opt/deep-research-web-ui/.env

[Install]
WantedBy=multi-user.target
UNITFILE

    pct push "$CT_ID" /tmp/deepresearch.service /etc/systemd/system/deepresearch.service
    rm -f /tmp/deepresearch.service

    pct exec "$CT_ID" -- bash -c 'systemd-analyze verify /etc/systemd/system/deepresearch.service'

    pct exec "$CT_ID" -- systemctl daemon-reload
    pct exec "$CT_ID" -- systemctl enable deepresearch.service
    pct exec "$CT_ID" -- systemctl start deepresearch.service

    echo "Waiting for deepresearch service to become active..."
    for i in $(seq 1 20); do
        if pct exec "$CT_ID" -- systemctl is-active deepresearch.service &>/dev/null; then
            echo "Service is active."
            break
        fi
        if [[ "$i" -eq 20 ]]; then
            echo "ERROR: Service failed to start. Diagnostics:"
            pct exec "$CT_ID" -- journalctl -u deepresearch.service --no-pager -n 50
            exit 1
        fi
        echo "Waiting for service... ($i/20)"
        sleep 3
    done

    for i in $(seq 1 15); do
        if pct exec "$CT_ID" -- bash -c "ss -tlnp 2>/dev/null | grep -q ':${APP_PORT}'"; then
            echo "Application is listening on port ${APP_PORT}."
            break
        fi
        if [[ "$i" -eq 15 ]]; then
            echo "ERROR: Application not listening on port ${APP_PORT}."
            pct exec "$CT_ID" -- journalctl -u deepresearch.service --no-pager -n 50
            exit 1
        fi
        echo "Waiting for port ${APP_PORT}... ($i/15)"
        sleep 2
    done

    set_state "phase7_service_configured"
    echo "Phase 7 complete."
else
    echo "Phase 7 already complete. Skipping."
fi

# ============================================================
# Phase 8: Final Validation & Cleanup
# ============================================================
if ! get_state "phase8_finalized"; then
    echo "=== Phase 8: Final Validation ==="

    HTTP_CODE=$(pct exec "$CT_ID" -- bash -c "curl -s -o /dev/null -w '%{http_code}' http://localhost:${APP_PORT}/ 2>/dev/null" || echo "000")

    if [[ "$HTTP_CODE" == "200" || "$HTTP_CODE" == "302" || "$HTTP_CODE" == "307" ]]; then
        echo "Application is responding (HTTP $HTTP_CODE)."
    else
        echo "NOTE: Application returned HTTP $HTTP_CODE. This may be expected until API keys are configured."
        echo "      Edit ${APP_DIR}/.env inside CT ${CT_ID}, then restart:"
        echo "      pct exec ${CT_ID} -- systemctl restart deepresearch"
    fi

    pct exec "$CT_ID" -- bash -c 'rm -f /etc/nginx/sites-enabled/default 2>/dev/null; true'
    pct exec "$CT_ID" -- bash -c 'rm -f /etc/mysql/conf.d/default.cnf 2>/dev/null; true'
    pct exec "$CT_ID" -- bash -c 'rm -f /tmp/setup_*.sh 2>/dev/null; true'

    # Manifest is always overwritten — it's a summary, not a secret
    SSH_PRIV_KEY="${SNIPPET_DIR}/ct${CT_ID}_ed25519"
    SSH_PUB_KEY="${SNIPPET_DIR}/ct${CT_ID}_ed25519.pub"

    cat > "${SNIPPET_DIR}/deepresearch_manifest.txt" <<MANIFEST
CT_ID=${CT_ID}
CT_HOSTNAME=${CT_HOSTNAME}
CT_IP=${CT_IP}
CT_IP_CIDR=${CT_IP_CIDR}
CT_GW=${CT_GW}
CT_BRIDGE=${CT_BRIDGE}
APP_PORT=${APP_PORT}
APP_DIR=${APP_DIR}
RELEASE_TAG=${RELEASE_TAG}
TEMPLATE=${TEMPLATE}
CT_STORAGE=${CT_STORAGE}
NODE_MAJOR=${NODE_MAJOR}
SSH_PRIV_KEY=${SSH_PRIV_KEY}
SSH_PUB_KEY=${SSH_PUB_KEY}
ROOT_PASSWD_FILE=${SNIPPET_DIR}/deepresearch_root_passwd.txt
NEXTAUTH_SECRET_FILE=${SNIPPET_DIR}/deepresearch_nextauth_secret.txt
ENV_FILE=${APP_DIR}/.env
SYSTEMD_UNIT=deepresearch.service
MANIFEST

    chmod 600 "${SNIPPET_DIR}/deepresearch_manifest.txt"

    set_state "phase8_finalized"
    echo "Phase 8 complete."
else
    echo "Phase 8 already complete. Skipping."
fi

# ============================================================
# HEARTBEAT_OK — Console + Persistent File
# ============================================================
mkdir -p "${HEARTBEAT_DIR}"

HEARTBEAT_TIMESTAMP=$(date +%Y%m%d_%H%M%S)
HEARTBEAT_FILE="${HEARTBEAT_DIR}/ct${CT_ID}_${CT_HOSTNAME}_${HEARTBEAT_TIMESTAMP}.txt"
HEARTBEAT_LATEST="${HEARTBEAT_DIR}/ct${CT_ID}_${CT_HOSTNAME}_latest.txt"

cat <<HEARTBEAT | tee "$HEARTBEAT_FILE"

╔══════════════════════════════════════════════════════════════════╗
║                        HEARTBEAT_OK                            ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                ║
║  Application:  deep-research-web-ui                           ║
║  Release Tag:  ${RELEASE_TAG}                                 ║
║  Repository:   ${REPO_URL}       ║
║  Template:     ${TEMPLATE}    ║
║  Storage:      ${CT_STORAGE}                                   ║
║  Bridge:       ${CT_BRIDGE} (internal)                        ║
║  Node.js:      v${NODE_MAJOR} LTS                               ║
║  Deployed:     $(date +%Y-%m-%d\ %H:%M:%S\ %Z)                      ║
║                                                                ║
║  URLs:                                                         ║
║    HTTP:       http://${CT_IP}:${APP_PORT}                         ║
║                                                                ║
║  Internal IPs:                                                ║
║    eth0:       ${CT_IP_CIDR} (vmbr1)                          ║
║    Gateway:    ${CT_GW}                                      ║
║    DNS:        ${CT_DNS}                    ║
║                                                                ║
║  Secret Paths (host-side):                                    ║
║    Root PW:    ${SNIPPET_DIR}/deepresearch_root_passwd.txt         ║
║    Auth Secret: ${SNIPPET_DIR}/deepresearch_nextauth_secret.txt   ║
║    SSH PrivKey: ${SNIPPET_DIR}/ct${CT_ID}_ed25519                  ║
║    SSH PubKey:  ${SNIPPET_DIR}/ct${CT_ID}_ed25519.pub              ║
║    Manifest:   ${SNIPPET_DIR}/deepresearch_manifest.txt           ║
║                                                                ║
║  In-Container Config:                                         ║
║    .env File:  ${APP_DIR}/.env                                 ║
║    → Edit this file to add your AI provider API keys           ║
║    → Then: pct exec ${CT_ID} -- systemctl restart deepresearch  ║
║                                                                ║
║  Service:      deepresearch.service (systemd)                 ║
║  App User:     ${APP_USER}                                      ║
║  CT ID:        ${CT_ID}                                           ║
║  CT Hostname:  ${CT_HOSTNAME}                                    ║
║                                                                ║
║  SSH Access:                                                  ║
║    ssh -i ${SNIPPET_DIR}/ct${CT_ID}_ed25519 root@${CT_IP}         ║
║                                                                ║
╚══════════════════════════════════════════════════════════════════╝

Deployment complete. Edit ${APP_DIR}/.env inside CT ${CT_ID} to
add your AI provider API keys, then restart the service.

HEARTBEAT

ln -sf "$HEARTBEAT_FILE" "$HEARTBEAT_LATEST"
chmod 600 "$HEARTBEAT_FILE"

echo ""
echo "Heartbeat persisted to: ${HEARTBEAT_FILE}"
echo "Latest symlink:          ${HEARTBEAT_LATEST}"
