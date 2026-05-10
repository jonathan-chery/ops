#!/bin/bash
# Description: Authoritative Proxmox LXC provisioning for Ubuntu 24.04 with Native Zitadel.
# Enforces external PostgreSQL state persistence, dynamic DB credentials, and Clean Slate initialization.

CT_ID="107"
CT_NAME="zitadel-server"
STORAGE="local"
DISK_SIZE="20"
SNIPPET_DIR="/var/lib/pve/local/snippets"
IP_ADDR="10.0.0.107/24" 
GATEWAY="10.0.0.254"
DOMAIN="login.cloudinit.dev"

mkdir -p "$SNIPPET_DIR"

# --- External State Persistence (PostgreSQL) ---
DB_HOST="10.0.0.102"
DB_PORT="5432"
DB_ADMIN_USER="proxmox_admin"
DB_NAME="zitadel"
DB_USER="zitadel"

if [ ! -f "$SNIPPET_DIR/postgres-1_admin_pwd.txt" ]; then
    echo "Error: Postgres admin password state missing at $SNIPPET_DIR/postgres-1_admin_pwd.txt"
    exit 1
fi
DB_ADMIN_PASS=$(cat "$SNIPPET_DIR/postgres-1_admin_pwd.txt")

# Generate Zitadel Credentials
DB_PASS=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 24)
MASTER_KEY=$(openssl rand -base64 48 | tr -dc 'a-zA-Z0-9' | head -c 32)
CT_PASSWORD=$(openssl rand -base64 15)

# Persist state
echo "$CT_PASSWORD" > "$SNIPPET_DIR/${CT_NAME}_pwd.txt"
echo "$DB_PASS" > "$SNIPPET_DIR/${CT_NAME}_db_pwd.txt"
echo "$MASTER_KEY" > "$SNIPPET_DIR/${CT_NAME}_masterkey.txt"

SSH_KEY_FILE="$SNIPPET_DIR/${CT_NAME}_id_ed25519"
[ ! -f "$SSH_KEY_FILE" ] && ssh-keygen -t ed25519 -N "" -f "$SSH_KEY_FILE"

# 1. Template Selection & Clean Slate LXC
pveam update > /dev/null
TEMPLATE_ID=$(pveam available | grep "ubuntu-24.04" | head -n1 | awk '{print $2}')
[ -z "$TEMPLATE_ID" ] && { echo "Error: Template not found"; exit 1; }

if ! pveam list local | grep -q "$(basename "$TEMPLATE_ID")"; then
    pveam download local "$TEMPLATE_ID"
fi

if pct status "$CT_ID" &>/dev/null; then
    pct stop "$CT_ID" 2>/dev/null
    pct destroy "$CT_ID"
fi

# 2. Base Container Creation
pct create "$CT_ID" "local:vztmpl/$(basename "$TEMPLATE_ID")" \
  --hostname "$CT_NAME" \
  --password "$CT_PASSWORD" \
  --ssh-public-keys "${SSH_KEY_FILE}.pub" \
  --net0 "name=eth0,bridge=vmbr1,ip=$IP_ADDR,gw=$GATEWAY" \
  --storage "$STORAGE" \
  --rootfs "$STORAGE:$DISK_SIZE" \
  --unprivileged 1

# 3. Boot & Initialization
pct start "$CT_ID"
sleep 15

pct exec "$CT_ID" -- bash -c "cat << 'INNER_EOF' > /etc/ssh/sshd_config.d/99-override.conf
PermitRootLogin yes
PasswordAuthentication yes
PubkeyAuthentication yes
INNER_EOF"
pct exec "$CT_ID" -- systemctl restart ssh

# 4. Environment & Database Bootstrapping (Clean Slate Enforced)
pct exec "$CT_ID" -- apt-get update
pct exec "$CT_ID" -- apt-get install -y wget curl tar ca-certificates postgresql-client
pct exec "$CT_ID" -- useradd -r -m -d /home/zitadel -s /bin/bash zitadel
pct exec "$CT_ID" -- mkdir -p /etc/zitadel /tmp/zitadel-ext

pct exec "$CT_ID" -- bash -c "
  echo 'Bootstrapping remote PostgreSQL database at ${DB_HOST} with destructive clean slate...'
  export PGPASSWORD='${DB_ADMIN_PASS}'
  
  # Terminate existing connections to allow drop
  psql -h '${DB_HOST}' -U '${DB_ADMIN_USER}' -d postgres -c \"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${DB_NAME}';\" > /dev/null 2>&1
  
  # Destructive reset
  psql -h '${DB_HOST}' -U '${DB_ADMIN_USER}' -d postgres -c \"DROP DATABASE IF EXISTS ${DB_NAME};\"
  psql -h '${DB_HOST}' -U '${DB_ADMIN_USER}' -d postgres -c \"DROP USER IF EXISTS ${DB_USER};\"
  
  # Fresh provisioning
  psql -h '${DB_HOST}' -U '${DB_ADMIN_USER}' -d postgres -c \"CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASS}' CREATEDB;\"
  psql -h '${DB_HOST}' -U '${DB_ADMIN_USER}' -d postgres -c \"CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};\"
"

# 5. Native Binary Extraction
pct exec "$CT_ID" -- wget -q -O /tmp/z.tar.gz "https://github.com/zitadel/zitadel/releases/download/v4.14.0/zitadel-linux-amd64.tar.gz"
pct exec "$CT_ID" -- tar -xzf /tmp/z.tar.gz -C /tmp/zitadel-ext
pct exec "$CT_ID" -- bash -c 'find /tmp/zitadel-ext -type f -name "zitadel" -exec mv {} /usr/local/bin/zitadel \;'
pct exec "$CT_ID" -- chmod +x /usr/local/bin/zitadel

pct exec "$CT_ID" -- wget -q -O /etc/zitadel/defaults.yaml "https://raw.githubusercontent.com/zitadel/zitadel/v4.14.0/cmd/defaults.yaml"
pct exec "$CT_ID" -- wget -q -O /etc/zitadel/setup.yaml "https://raw.githubusercontent.com/zitadel/zitadel/v4.14.0/cmd/setup/steps.yaml"

# 6. Host-Side Configuration Generation & pct push
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
    User:
      Username: $DB_USER
      Password: $DB_PASS
      SSL: { Mode: disable }
    Admin:
      Username: $DB_USER
      Password: $DB_PASS
      SSL: { Mode: disable }
FirstInstance:
  Domain: $DOMAIN
  Org:
    Machine:
      Machine:
        Username: 'setupmachine'
        Name: 'Setup Machine'
    Human:
      Username: 'setup'
      Password: 'Password1!'
YAML_EOF
pct push "$CT_ID" "$SNIPPET_DIR/zitadel.yaml" /etc/zitadel/zitadel.yaml

# Push Master Key
echo -n "$MASTER_KEY" > "$SNIPPET_DIR/zitadel_machinekey"
pct push "$CT_ID" "$SNIPPET_DIR/zitadel_machinekey" /etc/zitadel/machinekey

# 7. Host-Side Systemd Generation & pct push
cat << SYSTEMD_EOF > "$SNIPPET_DIR/zitadel.service"
[Unit]
Description=Zitadel Identity Provider
After=network.target

[Service]
User=zitadel
Group=zitadel
Environment="ZITADEL_MASTERKEY=$MASTER_KEY"

ExecStartPre=/usr/local/bin/zitadel init schema --config /etc/zitadel/defaults.yaml --config /etc/zitadel/zitadel.yaml
ExecStartPre=/usr/local/bin/zitadel setup --config /etc/zitadel/defaults.yaml --config /etc/zitadel/setup.yaml --config /etc/zitadel/zitadel.yaml
ExecStart=/usr/local/bin/zitadel start --tlsMode external --config /etc/zitadel/defaults.yaml --config /etc/zitadel/zitadel.yaml

Restart=always
RestartSec=10
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
SYSTEMD_EOF
pct push "$CT_ID" "$SNIPPET_DIR/zitadel.service" /etc/systemd/system/zitadel.service

# 8. Permissions & Execution
pct exec "$CT_ID" -- chown -R zitadel:zitadel /etc/zitadel
pct exec "$CT_ID" -- chmod 600 /etc/zitadel/machinekey
pct exec "$CT_ID" -- rm -rf /tmp/zitadel-ext /tmp/z.tar.gz
pct exec "$CT_ID" -- systemctl daemon-reload
pct exec "$CT_ID" -- systemctl enable --now zitadel

# 9. Output Standardization
echo "=========================================================================="
echo "HEARTBEAT_OK: Native Zitadel LXC rebuilt and database strictly bootstrapped."
echo "DOMAIN:        https://${DOMAIN}"
echo "INTERNAL IP:   ${IP_ADDR%/*}"
echo "DB PASSWORD:   ${DB_PASS}"
echo "MASTER KEY:    ${MASTER_KEY}"
echo "=========================================================================="
