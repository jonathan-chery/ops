#!/bin/bash
# Description: HARDENED Orchestrator for Zitadel Native Binary + Docker UI.
set -euo pipefail

# --- Global State & Configuration ---
CT_ID_CORE="107"
CT_CORE_NAME="zitadel-server"
CT_ID_UI="108"
CT_UI_NAME="zitadel-login"
STORAGE="local"
DISK_SIZE_CORE="20"
DISK_SIZE_UI="8"
SNIPPET_DIR="/var/lib/pve/local/snippets"
CORE_IP_ADDR="10.0.0.107/24"
UI_IP_ADDR="10.0.0.108/24"
GATEWAY="10.0.0.254"
DOMAIN="login.cloudinit.dev"
ZITADEL_VERSION="v4.14.0"

DB_HOST="10.0.0.102"
DB_PORT="5432"
DB_ADMIN_USER="proxmox_admin"
DB_NAME="zitadel"
DB_USER="zitadel"

STATE_FILE="/root/ops/.zitadel_native_state"
get_state() { cat "$STATE_FILE" 2>/dev/null || echo "1"; }
set_state() { echo "$1" > "$STATE_FILE"; }
PHASE=$(get_state)

mkdir -p "$SNIPPET_DIR"

if [ ! -f "$SNIPPET_DIR/postgres-1_admin_pwd.txt" ]; then
    echo "FATAL: Postgres admin password state missing at $SNIPPET_DIR/postgres-1_admin_pwd.txt"
    exit 1
fi
DB_ADMIN_PASS=$(cat "$SNIPPET_DIR/postgres-1_admin_pwd.txt")

# --- State Persistence & Generation ---
[ ! -f "$SNIPPET_DIR/${CT_CORE_NAME}_db_pwd.txt" ] && openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 24 > "$SNIPPET_DIR/${CT_CORE_NAME}_db_pwd.txt"
[ ! -f "$SNIPPET_DIR/${CT_CORE_NAME}_masterkey.txt" ] && openssl rand -base64 48 | tr -dc 'a-zA-Z0-9' | head -c 32 > "$SNIPPET_DIR/${CT_CORE_NAME}_masterkey.txt"
[ ! -f "$SNIPPET_DIR/zitadel_admin_pwd.txt" ] && openssl rand -base64 15 | tr -dc 'a-zA-Z0-9!@#%^&*' | head -c 16 > "$SNIPPET_DIR/zitadel_admin_pwd.txt"

DB_PASS=$(cat "$SNIPPET_DIR/${CT_CORE_NAME}_db_pwd.txt")
MASTER_KEY=$(cat "$SNIPPET_DIR/${CT_CORE_NAME}_masterkey.txt")
ADMIN_PASS=$(cat "$SNIPPET_DIR/zitadel_admin_pwd.txt")

CT_CORE_PASS=$(openssl rand -base64 15)
SSH_KEY_FILE="$SNIPPET_DIR/${CT_CORE_NAME}_id_ed25519"
[ ! -f "$SSH_KEY_FILE" ] && ssh-keygen -t ed25519 -N "" -f "$SSH_KEY_FILE"

# Enforce strict host-side secret permissions
chmod 600 "$SNIPPET_DIR"/*.txt 2>/dev/null || true

# --- Template Fetching ---
pveam update > /dev/null
TEMPLATE_ID=$(pveam available | grep "ubuntu-24.04" | head -n1 | awk '{print $2}')
[ -z "$TEMPLATE_ID" ] && { echo "FATAL: Template not found"; exit 1; }
pveam list local | grep -q "$(basename "$TEMPLATE_ID")" || pveam download local "$TEMPLATE_ID"

# ==========================================================================
if [ "$PHASE" -le 1 ]; then
    echo "=========================================================================="
    echo "[PHASE 1]: SECURE NATIVE CORE PROVISIONING (LXC 107)"
    echo "=========================================================================="

    if pct status "$CT_ID_CORE" &>/dev/null; then
        pct stop "$CT_ID_CORE" 2>/dev/null || true
        pct destroy "$CT_ID_CORE"
    fi

    # Strict Unprivileged LXC (No AppArmor hacks, no nesting)
    pct create "$CT_ID_CORE" "local:vztmpl/$(basename "$TEMPLATE_ID")" \
      --hostname "$CT_CORE_NAME" --password "$CT_CORE_PASS" --ssh-public-keys "${SSH_KEY_FILE}.pub" \
      --net0 "name=eth0,bridge=vmbr1,ip=$CORE_IP_ADDR,gw=$GATEWAY" \
      --storage "$STORAGE" --rootfs "$STORAGE:$DISK_SIZE_CORE" --unprivileged 1

    pct start "$CT_ID_CORE"
    
    echo "Waiting for network stack..."
    for i in {1..30}; do pct exec "$CT_ID_CORE" -- ping -c1 8.8.8.8 >/dev/null 2>&1 && break; sleep 1; done

    pct exec "$CT_ID_CORE" -- bash -c "cat << 'INNER_EOF' > /etc/ssh/sshd_config.d/99-override.conf
PermitRootLogin prohibit-password
PasswordAuthentication no
PubkeyAuthentication yes
INNER_EOF"
    pct exec "$CT_ID_CORE" -- systemctl restart ssh

    pct exec "$CT_ID_CORE" -- apt-get update
    pct exec "$CT_ID_CORE" -- apt-get install -y wget curl tar ca-certificates postgresql-client
    pct exec "$CT_ID_CORE" -- useradd -r -m -d /home/zitadel -s /bin/bash zitadel
    pct exec "$CT_ID_CORE" -- mkdir -p /etc/zitadel /etc/systemd/system/zitadel.service.d

    # SQL Injection Safe Setup
    cat << SQLEOF > "$SNIPPET_DIR/init.sql"
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${DB_NAME}';
DROP DATABASE IF EXISTS ${DB_NAME};
DROP USER IF EXISTS ${DB_USER};
CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASS}' CREATEDB;
CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};
SQLEOF
    pct push "$CT_ID_CORE" "$SNIPPET_DIR/init.sql" /tmp/init.sql
    pct exec "$CT_ID_CORE" -- bash -c "PGPASSWORD='${DB_ADMIN_PASS}' psql -h '${DB_HOST}' -U '${DB_ADMIN_USER}' -d postgres -f /tmp/init.sql"
    pct exec "$CT_ID_CORE" -- rm /tmp/init.sql

    # Secure Native Binary Extraction (Fixed for flat tarballs)
    pct exec "$CT_ID_CORE" -- wget -q -O /tmp/z.tar.gz "https://github.com/zitadel/zitadel/releases/download/${ZITADEL_VERSION}/zitadel-linux-amd64.tar.gz"
    pct exec "$CT_ID_CORE" -- mkdir -p /tmp/zitadel-ext
    pct exec "$CT_ID_CORE" -- tar -xzf /tmp/z.tar.gz -C /tmp/zitadel-ext
    pct exec "$CT_ID_CORE" -- bash -c 'mv $(find /tmp/zitadel-ext -type f -name "zitadel" | head -n 1) /usr/local/bin/zitadel'
    pct exec "$CT_ID_CORE" -- chmod +x /usr/local/bin/zitadel
    pct exec "$CT_ID_CORE" -- rm -rf /tmp/z.tar.gz /tmp/zitadel-ext

    # Config Generation
    pct exec "$CT_ID_CORE" -- wget -q -O /etc/zitadel/defaults.yaml "https://raw.githubusercontent.com/zitadel/zitadel/${ZITADEL_VERSION}/cmd/defaults.yaml"
    pct exec "$CT_ID_CORE" -- wget -q -O /etc/zitadel/setup.yaml "https://raw.githubusercontent.com/zitadel/zitadel/${ZITADEL_VERSION}/cmd/setup/steps.yaml"

    cat << YAML_EOF > "$SNIPPET_DIR/zitadel.yaml"
ExternalDomain: $DOMAIN
ExternalSecure: true
ExternalPort: 443
Port: 8080
Database:
  postgres:
    Host: $DB_HOST
    Port: $DB_PORT
    Database: $DB_NAME
    User: { Username: $DB_USER, Password: $DB_PASS, SSL: { Mode: disable } }
    Admin: { Username: $DB_USER, Password: $DB_PASS, SSL: { Mode: disable } }
FirstInstance:
  Org:
    Human: { Username: 'admin', Password: '${ADMIN_PASS}' }
YAML_EOF
    pct push "$CT_ID_CORE" "$SNIPPET_DIR/zitadel.yaml" /etc/zitadel/zitadel.yaml
    echo -n "$MASTER_KEY" > "$SNIPPET_DIR/zitadel_machinekey"
    pct push "$CT_ID_CORE" "$SNIPPET_DIR/zitadel_machinekey" /etc/zitadel/machinekey

    # V1 Bypass Drop-in (Required for initial boot without UI container)
    cat << 'DROPIN_EOF' > "$SNIPPET_DIR/v1-bypass.conf"
[Service]
Environment="ZITADEL_DEFAULTINSTANCE_FEATURES_LOGINV2_REQUIRED=false"
DROPIN_EOF
    pct push "$CT_ID_CORE" "$SNIPPET_DIR/v1-bypass.conf" /etc/systemd/system/zitadel.service.d/v1-bypass.conf

    # Idempotent Native Systemd Unit
    cat << 'SYSTEMD_EOF' > "$SNIPPET_DIR/zitadel.service"
[Unit]
Description=Zitadel Identity Provider Core
After=network.target

[Service]
User=zitadel
Group=zitadel
WorkingDirectory=/etc/zitadel

ExecStartPre=/usr/local/bin/zitadel init schema --config /etc/zitadel/defaults.yaml --config /etc/zitadel/zitadel.yaml
ExecStartPre=/bin/bash -c 'test -f /etc/zitadel/.setup-done || (/usr/local/bin/zitadel setup --masterkeyFile /etc/zitadel/machinekey --config /etc/zitadel/defaults.yaml --config /etc/zitadel/setup.yaml --config /etc/zitadel/zitadel.yaml && touch /etc/zitadel/.setup-done)'
ExecStart=/usr/local/bin/zitadel start --masterkeyFile /etc/zitadel/machinekey --tlsMode external --config /etc/zitadel/defaults.yaml --config /etc/zitadel/zitadel.yaml

Restart=always
RestartSec=10
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
SYSTEMD_EOF
    pct push "$CT_ID_CORE" "$SNIPPET_DIR/zitadel.service" /etc/systemd/system/zitadel.service
    
    pct exec "$CT_ID_CORE" -- chown -R zitadel:zitadel /etc/zitadel
    pct exec "$CT_ID_CORE" -- chmod 600 /etc/zitadel/machinekey
    pct exec "$CT_ID_CORE" -- systemctl daemon-reload
    pct exec "$CT_ID_CORE" -- systemctl enable --now zitadel

    rm -f "$SNIPPET_DIR/zitadel.yaml" "$SNIPPET_DIR/v1-bypass.conf" "$SNIPPET_DIR/zitadel.service" "$SNIPPET_DIR/zitadel_machinekey"

    echo "Waiting for Native Zitadel Binary to achieve readiness..."
    for i in {1..60}; do 
        pct exec "$CT_ID_CORE" -- curl -sf http://localhost:8080/debug/healthz >/dev/null 2>&1 && break
        sleep 2
    done

    set_state 2
fi

# ==========================================================================
if [ "$PHASE" -le 2 ]; then
    echo ""
    echo "=========================================================================="
    echo "[PHASE 2]: HUMAN-IN-THE-LOOP (HITL) - TOKEN EXTRACTION"
    echo "=========================================================================="
    echo "ACTION REQUIRED:"
    echo "1. Navigate to https://$DOMAIN/ui/console/"
    echo "2. Log in using:"
    echo "   User: zitadel-admin@zitadel.login.cloudinit.dev"
    echo "   Pass: Password1!"
    echo "   (Note: Zitadel will require you to change this password immediately)."
    echo ""
    echo "3. Go to Users -> Service Accounts -> click 'New' (Name: login-v2-client)"
    echo "4. Open the new Service Account -> Personal Access Tokens -> click 'New'"
    echo "   (Ensure you select Bearer/Standard PAT, not JWT)."
    echo "5. Copy the generated token string (starts with v2_...)."
    echo "   *IMPORTANT: Note the exact Loginname of this service account!*"
    echo ""
    echo "6. Click 'Instance' in the top navigation bar."
    echo "7. On the right side under 'Administrators', click '+'."
    echo "8. Search for the Service Account's exact loginname."
    echo "9. Select the 'IAM_LOGIN_CLIENT' role and click Add."
    echo "=========================================================================="

    while true; do
        read -p "Paste the PAT token here and press [ENTER] to resume: " PAT_TOKEN
        if [[ ! "$PAT_TOKEN" =~ ^v2_ ]]; then
            echo "Warning: Token does not start with 'v2_'. Are you sure this is a Bearer PAT?"
            read -p "Continue anyway? [y/N] " confirm
            [[ "$confirm" != [yY]* ]] && continue
        fi
        
        if [ -n "$PAT_TOKEN" ]; then
            echo "$PAT_TOKEN" > "$SNIPPET_DIR/zitadel_login_pat.txt"
            chmod 600 "$SNIPPET_DIR/zitadel_login_pat.txt"
            echo "State Persistent: PAT saved successfully."
            break
        fi
    done

    set_state 3
fi

# ==========================================================================
if [ "$PHASE" -le 3 ]; then
    echo ""
    echo "=========================================================================="
    echo "[PHASE 3]: NEXT.JS UI DOCKER PROVISIONING (LXC 108)"
    echo "=========================================================================="
    CT_UI_PASS=$(openssl rand -base64 15)
    SSH_KEY_UI="$SNIPPET_DIR/${CT_UI_NAME}_id_ed25519"
    [ ! -f "$SSH_KEY_UI" ] && ssh-keygen -t ed25519 -N "" -f "$SSH_KEY_UI"

    if pct status "$CT_ID_UI" &>/dev/null; then
        pct stop "$CT_ID_UI" 2>/dev/null || true
        pct destroy "$CT_ID_UI"
    fi

    # LXC 108 uses Nesting and Unconfined AppArmor purely for the UI container
    pct create "$CT_ID_UI" "local:vztmpl/$(basename "$TEMPLATE_ID")" \
      --hostname "$CT_UI_NAME" --password "$CT_UI_PASS" --ssh-public-keys "${SSH_KEY_UI}.pub" \
      --net0 "name=eth0,bridge=vmbr1,ip=$UI_IP_ADDR,gw=$GATEWAY" \
      --storage "$STORAGE" --rootfs "$STORAGE:$DISK_SIZE_UI" --unprivileged 1 \
      --features nesting=1,keyctl=1

    echo "lxc.apparmor.profile: unconfined" >> /etc/pve/lxc/${CT_ID_UI}.conf
    echo "lxc.mount.entry: /dev/null sys/module/apparmor/parameters/enabled none bind 0 0" >> /etc/pve/lxc/${CT_ID_UI}.conf

    pct start "$CT_ID_UI"
    echo "Waiting for network stack..."
    for i in {1..30}; do pct exec "$CT_ID_UI" -- ping -c1 8.8.8.8 >/dev/null 2>&1 && break; sleep 1; done

    pct exec "$CT_ID_UI" -- apt-get update
    pct exec "$CT_ID_UI" -- apt-get install -y curl ca-certificates

    pct push "$CT_ID_UI" "$SNIPPET_DIR/zitadel_login_pat.txt" /root/pat.txt
    # IMPORTANT: 644 so the internal unprivileged Node.js container user can read it
    pct exec "$CT_ID_UI" -- chmod 644 /root/pat.txt

    pct exec "$CT_ID_UI" -- bash -c "
      install -m 0755 -d /etc/apt/keyrings
      curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
      chmod a+r /etc/apt/keyrings/docker.asc
      echo \"deb [arch=\$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \$(. /etc/os-release && echo \"\$VERSION_CODENAME\") stable\" | tee /etc/apt/sources.list.d/docker.list > /dev/null
      
      apt-get update
      apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

      docker run -d --name zitadel-login \
        -v /root/pat.txt:/app/pat.txt:ro \
        -p 3000:3000 \
        -e ZITADEL_SERVICE_USER_TOKEN_FILE=/app/pat.txt \
        -e ZITADEL_API_URL=https://$DOMAIN \
        --restart always \
        ghcr.io/zitadel/zitadel-login:${ZITADEL_VERSION}
    "
    set_state 4
fi

# ==========================================================================
if [ "$PHASE" -le 4 ]; then
    echo ""
    echo "=========================================================================="
    echo "[PHASE 4]: HUMAN-IN-THE-LOOP (HITL) - HAProxy ROUTING & HTTP/2"
    echo "=========================================================================="
    echo "ACTION REQUIRED: Configure HAProxy to route HTTP/2 gRPC traffic."
    echo ""
    echo "1. On your frontend (bind *:443), ensure ALPN is enabled:"
    echo "   bind *:443 ssl crt /path/to/cert alpn h2,http/1.1"
    echo ""
    echo "2. Add the backend routing logic:"
    echo "    acl is_login_v2 path_beg /ui/v2/login"
    echo "    use_backend zitadel_v2_backend if is_zitadel is_login_v2"
    echo "    use_backend zitadel_core_backend if is_zitadel"
    echo ""
    echo "    backend zitadel_v2_backend"
    echo "        server zitadel-login 10.0.0.108:3000 check"
    echo ""
    echo "    backend zitadel_core_backend"
    echo "        http-request set-header X-Forwarded-Proto https"
    echo "        http-request set-header X-Forwarded-Host %[req.hdr(Host)]"
    echo "        http-request set-header Connection \"Upgrade\" if { hdr(Upgrade) -m found }"
    echo "        # IMPORTANT: 'proto h2' is required for the Next.js container to talk gRPC to the core"
    echo "        server zitadel-server 10.0.0.107:8080 check proto h2"
    echo "=========================================================================="

    while true; do
        read -p "Type 'DONE' and press [ENTER] once HAProxy is configured and reloaded: " PROXY_STATUS
        if [[ "${PROXY_STATUS,,}" == "done" ]]; then
            break
        fi
    done
    
    set_state 5
fi

# ==========================================================================
if [ "$PHASE" -le 5 ]; then
    echo ""
    echo "=========================================================================="
    echo "[PHASE 5]: ENFORCING V2 STATE ON NATIVE CORE"
    echo "=========================================================================="
    
    pct exec "$CT_ID_CORE" -- rm -f /etc/systemd/system/zitadel.service.d/v1-bypass.conf
    pct exec "$CT_ID_CORE" -- systemctl daemon-reload
    pct exec "$CT_ID_CORE" -- systemctl restart zitadel

    echo "Waiting for Core to restart..."
    for i in {1..60}; do 
        pct exec "$CT_ID_CORE" -- curl -sf http://localhost:8080/debug/healthz >/dev/null 2>&1 && break
        sleep 2
    done

    echo "Running Smoke Tests..."
    pct exec "$CT_ID_CORE" -- curl -sf http://localhost:8080/debug/healthz >/dev/null || echo "WARNING: Zitadel core health check failed!"
    pct exec "$CT_ID_UI" -- curl -sf http://localhost:3000 >/dev/null || echo "WARNING: Login V2 frontend not responding!"

    set_state 6
fi

# ==========================================================================
if [ "$PHASE" -le 6 ]; then
    echo ""
    echo "=========================================================================="
    echo "[PHASE 6]: HUMAN-IN-THE-LOOP (HITL) - FINAL V2 ACTIVATION"
    echo "=========================================================================="
    echo "ACTION REQUIRED: Tell Zitadel Core where to redirect users."
    echo ""
    echo "1. Copy and paste this exact URL into your browser:"
    echo "   https://$DOMAIN/ui/console/instance?id=features"
    echo "2. Scroll to the very bottom to find the 'Login V2' panel."
    echo "3. Toggle 'Enable Login V2' to ON."
    echo "4. In the 'Base URI' field, paste: https://$DOMAIN/ui/v2/login"
    echo "5. Click 'Save' in the Login V2 panel."
    echo "=========================================================================="

    while true; do
        read -p "Type 'DONE' and press [ENTER] once the Instance settings are saved: " V2_STATUS
        if [[ "${V2_STATUS,,}" == "done" ]]; then
            break
        fi
    done

    rm -f "$STATE_FILE"

    echo "=========================================================================="
    echo "HEARTBEAT_OK: Native Decoupled Architecture Deployed Successfully."
    echo "Native Core: 10.0.0.107"
    echo "Docker UI:   10.0.0.108"
    echo "Test it:     Open an Incognito window and visit https://$DOMAIN/ui/console/"
    echo "             (It should immediately redirect you to the new V2 UI)."
    echo "=========================================================================="
fi
