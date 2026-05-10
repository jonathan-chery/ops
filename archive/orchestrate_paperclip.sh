#!/bin/bash
# Description: Final Paperclip AI Orchestrator (App + Postgres + OpenCode CLI + Config)
set -euo pipefail

# --- 1. Configuration ---
CT_ID="150"
CT_NAME="paperclip-app"
STORAGE="local"
DISK_SIZE="25"
IP_ADDR="10.0.0.150/24"
GATEWAY="10.0.0.254"
CT_PASS=$(openssl rand -base64 15)

# --- 2. Credentials & Secrets ---
DB_PASS=$(openssl rand -hex 16)
AUTH_SECRET=$(openssl rand -base64 32)
# Using 127.0.0.1 because of host networking mode
DB_URL="postgres://paperclip:${DB_PASS}@127.0.0.1:5432/paperclip"

echo "=========================================================================="
echo " Paperclip AI Final Deployment (OpenCode Integrated)"
echo "=========================================================================="
read -p "Enter Public URL (e.g., https://paperclip.cloudinit.dev) [Leave blank for default]: " INPUT_URL
AUTH_URL="${INPUT_URL:-https://paperclip.cloudinit.dev}"

# --- 3. Proxmox LXC Provisioning ---
pveam update > /dev/null
TEMPLATE_ID=$(pveam available | grep "ubuntu-24.04" | head -n1 | awk '{print $2}')
pveam list local | grep -q "$(basename "$TEMPLATE_ID")" || pveam download local "$TEMPLATE_ID"

if pct status "$CT_ID" &>/dev/null; then
    echo "[!] Cleaning up existing container..."
    pct stop "$CT_ID" 2>/dev/null || true
    pct destroy "$CT_ID"
fi

echo "[*] Creating LXC $CT_ID..."
pct create "$CT_ID" "local:vztmpl/$(basename "$TEMPLATE_ID")" \
  --hostname "$CT_NAME" --password "$CT_PASS" \
  --memory 8192 --onboot 1 \
  --net0 "name=eth0,bridge=vmbr1,ip=$IP_ADDR,gw=$GATEWAY" \
  --storage "$STORAGE" --rootfs "$STORAGE:$DISK_SIZE" \
  --features nesting=1 --unprivileged 1

pct start "$CT_ID"
echo "[*] Waiting for network..."
for i in {1..30}; do pct exec "$CT_ID" -- ping -c1 8.8.8.8 >/dev/null 2>&1 && break; sleep 1; done

# --- 4. Persistent Secrets Storage ---
echo "[*] Archiving credentials to /var/lib/pve/local/snippets/paperclip/..."
mkdir -p /var/lib/pve/local/snippets/paperclip
cat << CREDS_EOF > /var/lib/pve/local/snippets/paperclip/db_credentials.txt
# Paperclip Stack Credentials - $(date)
DATABASE_URL=$DB_URL
DB_USER=paperclip
DB_PASS=$DB_PASS
BETTER_AUTH_SECRET=$AUTH_SECRET
AUTH_URL=$AUTH_URL
CREDS_EOF
chmod 600 /var/lib/pve/local/snippets/paperclip/db_credentials.txt

# --- 5. Internal LXC Setup (Docker & User) ---
echo "[*] Installing Docker and Base Tools..."
pct exec "$CT_ID" -- apt-get update
pct exec "$CT_ID" -- env DEBIAN_FRONTEND=noninteractive apt-get install -y curl jq
pct exec "$CT_ID" -- bash -c "curl -fsSL https://get.docker.com | sh || true"
pct exec "$CT_ID" -- bash -c "id -u node &>/dev/null || useradd -m -u 1000 -s /bin/bash node"

# Create persistent folders
pct exec "$CT_ID" -- mkdir -p /opt/paperclip /home/node/.config/opencode /home/node/sync
pct exec "$CT_ID" -- chown -R 1000:1000 /home/node

# --- 6. OpenCode Config Bootstrap ---
echo "[*] Bootstrapping OpenCode Configuration..."
# Attempt to fetch from repo source of truth (using /raw/ path to get direct file instead of UI)
if ! curl -fsSL "https://git.cloudinit.dev/ns558010/ns558010/raw/branch/main/.config/opencode/opencode.json" -o /tmp/opencode.json; then
    echo "[!] Could not fetch from repo, using fallback configuration..."
    cat << 'JSON_EOF' > /tmp/opencode.json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "ollama": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Ollama",
      "options": {
        "baseURL": "http://10.0.0.10:11434/v1"
      },
      "models": {
        "minimax-m2.7:cloud": {
          "name": "MiniMax M2.7 (Cloud) - Tasks: Enterprise automation, multi-agent orchestration, and professional document drafting. Cost Profile: Medium."
        },
        "gemma4:31b-cloud": {
          "name": "Gemma 4 (31B Cloud) - Tasks: Low-latency queries, basic conversational routing, and rapid translation. Cost Profile: Low."
        },
        "kimi-k2.5:cloud": {
          "name": "Kimi K2.5 (Cloud) - Tasks: Massive long-context analysis, financial report summarization, and large codebase ingestion. Cost Profile: Medium-High."
        },
        "kimi-k2.6:cloud": {
          "name": "Kimi K2.6 (Cloud) - Tasks: Massive long-context analysis, financial report summarization, and large codebase ingestion. Cost Profile: Medium>"
        },
        "glm-5:cloud": {
          "name": "GLM-5.0 (Cloud) - Tasks: Multi-step logical reasoning, autonomous scientific research, and complex system design. Cost Profile: Premium."
        },
        "glm-5.1:cloud": {
          "name": "GLM-5.1 (Cloud) - Tasks: Multi-step logical reasoning, autonomous scientific research, and complex system design. Cost Profile: Premium."
        }
      }
    }
  }
}
JSON_EOF
fi

pct push "$CT_ID" /tmp/opencode.json /paperclip/.config/opencode/opencode.json
rm /tmp/opencode.json
pct exec "$CT_ID" -- chown 1000:1000 /paperclip/.config/opencode/opencode.json

# --- 7. Docker Stack Construction ---
echo "[*] Building Custom Paperclip Image (with OpenCode CLI)..."
cat << 'DOCKERFILE_EOF' > /tmp/paperclip.Dockerfile
FROM ghcr.io/paperclipai/paperclip:latest
USER root
RUN npm install -g opencode-ai@latest
# Pre-create all known cache/log directories and grant 'node' absolute ownership
RUN mkdir -p /paperclip/.cache \
             /paperclip/instances/default/data/run-logs \
             /paperclip/instances/default \
	     /home/node \ && \
    chown -R node:node /paperclip
DOCKERFILE_EOF
pct push "$CT_ID" /tmp/paperclip.Dockerfile /opt/paperclip/Dockerfile
rm /tmp/paperclip.Dockerfile

echo "[*] Constructing Docker Compose Stack..."
cat << COMPOSE_EOF > /tmp/paperclip-docker-compose.yml
services:
  postgres:
    image: postgres:16-alpine
    container_name: paperclip_db
    restart: unless-stopped
    network_mode: "host"
    environment:
      POSTGRES_USER: paperclip
      POSTGRES_PASSWORD: ${DB_PASS}
      POSTGRES_DB: paperclip
    volumes:
      - postgres_data:/var/lib/postgresql/data

  paperclip:
    build: .
    container_name: paperclip
    restart: unless-stopped
    network_mode: "host"
    depends_on:
      - postgres
    volumes:
      - /home/node:/home/node
    environment:
      - DATABASE_URL=${DB_URL}
      - BETTER_AUTH_BASE_URL=${AUTH_URL}
      - BETTER_AUTH_SECRET=${AUTH_SECRET}
      # Point the CLI to the bootstrapped configuration
      - OPENCODE_CONFIG_PATH=/home/node/.config/opencode/opencode.json

volumes:
  postgres_data:
COMPOSE_EOF
pct push "$CT_ID" /tmp/paperclip-docker-compose.yml /opt/paperclip/docker-compose.yml
rm /tmp/paperclip-docker-compose.yml

# --- 8. Final Service Activation ---
echo "[*] Registering Systemd Wrapper Service..."
pct exec "$CT_ID" -- bash -c "cat << 'SERVICE_EOF' > /etc/systemd/system/paperclip.service
[Unit]
Description=Paperclip AI Full Stack
After=docker.service

[Service]
Type=simple
WorkingDirectory=/opt/paperclip
ExecStart=/usr/bin/docker compose up --build
ExecStop=/usr/bin/docker compose down
Restart=always

[Install]
WantedBy=multi-user.target
SERVICE_EOF"

pct exec "$CT_ID" -- systemctl daemon-reload
pct exec "$CT_ID" -- systemctl enable --now paperclip

echo "=========================================================================="
echo " SUCCESS: Paperclip Full Stack is deployed and compiling."
echo " Note: The first boot takes ~60 seconds to compile the custom Docker image."
echo "--------------------------------------------------------------------------"
echo " 1. WATCH LOGS: pct exec $CT_ID -- journalctl -u paperclip -f"
echo " 2. ONBOARD:    pct exec $CT_ID -- docker exec -it paperclip pnpm paperclipai onboard"
echo " 3. MODELS:     pct exec $CT_ID -- docker exec -it -u node paperclip opencode models"
echo "=========================================================================="
