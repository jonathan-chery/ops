#!/bin/bash
# Description: Proxmox Orchestrator for Open WebUI (Connected to Ollama + LiteLLM)
set -euo pipefail

# --- 1. Configuration ---
CT_ID="170"
CT_NAME="openwebui-app"
STORAGE="local"
DISK_SIZE="15"
IP_ADDR="10.0.0.170/24"
GATEWAY="10.0.0.254"
CT_PASS=$(openssl rand -base64 15)

# Backend Connections
OLLAMA_URL="http://10.0.0.10:11434"
LITELLM_URL="http://10.0.0.124:4000/v1" # The /v1 is required for Open WebUI
LITELLM_KEY="sk-dummy-key" # Required by the UI even if LiteLLM doesn't enforce it

echo "=========================================================================="
echo " Deploying Open WebUI (Ollama + LiteLLM Unified Frontend)"
echo "=========================================================================="

# --- 2. Proxmox LXC Provisioning ---
pveam update > /dev/null
TEMPLATE_ID=$(pveam available | grep "ubuntu-24.04" | head -n1 | awk '{print $2}')
pveam list local | grep -q "$(basename "$TEMPLATE_ID")" || pveam download local "$TEMPLATE_ID"

if pct status "$CT_ID" &>/dev/null; then
    echo "[!] Cleaning up existing container..."
    pct stop "$CT_ID" 2>/dev/null || true
    pct destroy "$CT_ID"
fi

echo "[*] Creating LXC $CT_ID (4GB RAM, Auto-Boot Enabled)..."
pct create "$CT_ID" "local:vztmpl/$(basename "$TEMPLATE_ID")" \
  --hostname "$CT_NAME" --password "$CT_PASS" \
  --memory 4096 --onboot 1 \
  --net0 "name=eth0,bridge=vmbr1,ip=$IP_ADDR,gw=$GATEWAY" \
  --storage "$STORAGE" --rootfs "$STORAGE:$DISK_SIZE" \
  --features nesting=1 --unprivileged 1

pct start "$CT_ID"
echo "[*] Waiting for network..."
for i in {1..30}; do pct exec "$CT_ID" -- ping -c1 8.8.8.8 >/dev/null 2>&1 && break; sleep 1; done

# --- 3. Internal LXC Setup (Docker) ---
echo "[*] Installing Docker..."
pct exec "$CT_ID" -- apt-get update
pct exec "$CT_ID" -- env DEBIAN_FRONTEND=noninteractive apt-get install -y curl
pct exec "$CT_ID" -- bash -c "curl -fsSL https://get.docker.com | sh || true"
pct exec "$CT_ID" -- mkdir -p /opt/openwebui

# --- 4. Docker Stack Construction ---
echo "[*] Constructing Docker Compose Stack..."
cat << COMPOSE_EOF > /tmp/webui-docker-compose.yml
services:
  open-webui:
    image: ghcr.io/open-webui/open-webui:main
    container_name: open-webui
    restart: always
    network_mode: "host" # Bypasses Ubuntu 24.04 AppArmor network bugs
    environment:
      # Connects to your raw Ollama instance
      - OLLAMA_BASE_URL=${OLLAMA_URL}
      # Connects to your LiteLLM Proxy (OpenAI format)
      - OPENAI_API_BASE_URL=${LITELLM_URL}
      - OPENAI_API_KEY=${LITELLM_KEY}
      # Telemetry opt-out
      - SCARF_NO_ANALYTICS=true
      - DO_NOT_TRACK=true
    volumes:
      - open-webui_data:/app/backend/data

volumes:
  open-webui_data:
COMPOSE_EOF
pct push "$CT_ID" /tmp/webui-docker-compose.yml /opt/openwebui/docker-compose.yml
rm /tmp/webui-docker-compose.yml

# --- 5. Systemd Service Activation ---
echo "[*] Registering Systemd Wrapper Service..."
pct exec "$CT_ID" -- bash -c "cat << 'SERVICE_EOF' > /etc/systemd/system/openwebui.service
[Unit]
Description=Open WebUI Stack
After=docker.service

[Service]
Type=simple
WorkingDirectory=/opt/openwebui
ExecStart=/usr/bin/docker compose up
ExecStop=/usr/bin/docker compose down
Restart=always

[Install]
WantedBy=multi-user.target
SERVICE_EOF"

pct exec "$CT_ID" -- systemctl daemon-reload
pct exec "$CT_ID" -- systemctl enable --now openwebui

echo "=========================================================================="
echo " SUCCESS: Open WebUI is deploying!"
echo " It takes about ~60 seconds to download the image and start up."
echo " Internal UI: http://${IP_ADDR%/*}:8080"
echo " Logs: pct exec $CT_ID -- docker logs -f open-webui"
echo "=========================================================================="
