#!/bin/bash
# Description: Authoritative Proxmox LXC provisioning for Ubuntu 24.04 with Native n8n (Node.js).
# Enforces external PostgreSQL state persistence, dynamic DB credentials, and pct push deployments.

# --- Container Configuration ---
CT_ID="140"
CT_NAME="n8n-server"
STORAGE="local"
DISK_SIZE="20"
SNIPPET_DIR="/var/lib/pve/local/snippets"
IP_ADDR="10.0.0.140/24" 
GATEWAY="10.0.0.254"
TARGET_DOMAIN="https://n8n.cloudinit.dev"

mkdir -p "$SNIPPET_DIR"

# --- External State Persistence (PostgreSQL) ---
DB_HOST="10.0.0.102" # Authoritative DB Route
DB_PORT="5432"
DB_ADMIN_USER="proxmox_admin"

# Dynamically retrieve the admin password from the Proxmox host state
if [ ! -f "$SNIPPET_DIR/postgres-1_admin_pwd.txt" ]; then
    echo "Error: Postgres admin password state missing at $SNIPPET_DIR/postgres-1_admin_pwd.txt"
    exit 1
fi
DB_ADMIN_PASS=$(cat "$SNIPPET_DIR/postgres-1_admin_pwd.txt")

# Target n8n credentials to be created
DB_NAME="n8n_db"
DB_USER="n8n_user"
DB_PASS=$(openssl rand -base64 18)

# 1. State Persistence: Credentials
CT_PASSWORD=$(openssl rand -base64 15)
echo "$CT_PASSWORD" > "$SNIPPET_DIR/${CT_NAME}_pwd.txt"
echo "n8n Postgres DB Password: $DB_PASS" > "$SNIPPET_DIR/${CT_NAME}_db_pwd.txt"

SSH_KEY_FILE="$SNIPPET_DIR/${CT_NAME}_id_ed25519"
[ ! -f "$SSH_KEY_FILE" ] && ssh-keygen -t ed25519 -N "" -f "$SSH_KEY_FILE"

# 2. Template Selection
pveam update > /dev/null
TEMPLATE_ID=$(pveam available | grep "ubuntu-24.04" | head -n1 | awk '{print $2}')
[ -z "$TEMPLATE_ID" ] && { echo "Error: Template not found"; exit 1; }

if ! pveam list local | grep -q "$(basename "$TEMPLATE_ID")"; then
    pveam download local "$TEMPLATE_ID"
fi

# 3. Clean Slate Enforcement
if pct status "$CT_ID" &>/dev/null; then
    pct stop "$CT_ID" 2>/dev/null
    pct destroy "$CT_ID"
fi

# 4. Base Container Creation
pct create "$CT_ID" "local:vztmpl/$(basename "$TEMPLATE_ID")" \
  --hostname "$CT_NAME" \
  --password "$CT_PASSWORD" \
  --ssh-public-keys "${SSH_KEY_FILE}.pub" \
  --net0 "name=eth0,bridge=vmbr1,ip=$IP_ADDR,gw=$GATEWAY" \
  --storage "$STORAGE" \
  --rootfs "$STORAGE:$DISK_SIZE" \
  --unprivileged 1

# 5. Boot & Initialization
pct start "$CT_ID"
sleep 15

pct exec "$CT_ID" -- bash -c "cat << 'INNER_EOF' > /etc/ssh/sshd_config.d/99-override.conf
PermitRootLogin yes
PasswordAuthentication yes
PubkeyAuthentication yes
INNER_EOF"
pct exec "$CT_ID" -- systemctl restart ssh

# 6. Execution Loop: Bootstrap Database via pg_client
pct exec "$CT_ID" -- bash -c "
  apt-get update
  apt-get install -y openssh-server curl ca-certificates postgresql-client

  echo 'Bootstrapping remote PostgreSQL database at ${DB_HOST}...'
  export PGPASSWORD='${DB_ADMIN_PASS}'
  
  psql -h '${DB_HOST}' -U '${DB_ADMIN_USER}' -d postgres -tc \"SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'\" | grep -q 1 || \
    psql -h '${DB_HOST}' -U '${DB_ADMIN_USER}' -d postgres -c \"CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASS}';\"
    
  psql -h '${DB_HOST}' -U '${DB_ADMIN_USER}' -d postgres -tc \"SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'\" | grep -q 1 || \
    psql -h '${DB_HOST}' -U '${DB_ADMIN_USER}' -d postgres -c \"CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};\"
"

# 7. Host-Side Systemd Generation & pct push
cat << SYSTEMD_EOF > "$SNIPPET_DIR/n8n.service"
[Unit]
Description=n8n Workflow Automation
After=network.target

[Service]
User=n8n
Group=n8n
Environment=NODE_ENV=production
Environment=WEBHOOK_URL=${TARGET_DOMAIN}
Environment=DB_TYPE=postgresdb
Environment=DB_POSTGRESDB_DATABASE=${DB_NAME}
Environment=DB_POSTGRESDB_HOST=${DB_HOST}
Environment=DB_POSTGRESDB_PORT=${DB_PORT}
Environment=DB_POSTGRESDB_USER=${DB_USER}
Environment=DB_POSTGRESDB_PASSWORD=${DB_PASS}
Environment=GENERIC_TIMEZONE=UTC
ExecStart=/usr/bin/n8n
Restart=always

[Install]
WantedBy=multi-user.target
SYSTEMD_EOF

pct push "$CT_ID" "$SNIPPET_DIR/n8n.service" /etc/systemd/system/n8n.service

# 8. Execution Loop: Install Node.js, Native n8n, & Enable Service
pct exec "$CT_ID" -- bash -c "
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
  npm install -g n8n

  useradd -r -m -d /home/n8n -s /sbin/nologin n8n

  systemctl daemon-reload
  systemctl enable --now n8n
"

echo "HEARTBEAT_OK: Native LXC rebuilt. Database bootstrapped. Systemd unit pushed. n8n running on http://${IP_ADDR%/*}:5678"
