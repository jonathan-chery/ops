#!/bin/bash
# Description: Proxmox Orchestrator for LiteLLM (Chargeback/Proxy Layer for Ollama)
set -euo pipefail

# --- Global State & Configuration ---
CT_ID="124"
CT_NAME="litellm-proxy"
STORAGE="local"
DISK_SIZE="8"
IP_ADDR="10.0.0.124/24"
GATEWAY="10.0.0.254"
CT_PASS=$(openssl rand -base64 15)

echo "=========================================================================="
echo " LiteLLM + Ollama Chargeback Provisioner"
echo "=========================================================================="
while true; do
    read -p "Enter your Ollama Server IP (e.g., 10.0.0.X): " OLLAMA_IP
    if [ -n "$OLLAMA_IP" ]; then break; fi
done

# --- Template Fetching ---
pveam update > /dev/null
TEMPLATE_ID=$(pveam available | grep "ubuntu-24.04" | head -n1 | awk '{print $2}')
[ -z "$TEMPLATE_ID" ] && { echo "FATAL: Template not found"; exit 1; }
pveam list local | grep -q "$(basename "$TEMPLATE_ID")" || pveam download local "$TEMPLATE_ID"

# --- Container Creation ---
if pct status "$CT_ID" &>/dev/null; then
    echo "[!] Destroying existing container $CT_ID..."
    pct stop "$CT_ID" 2>/dev/null || true
    pct destroy "$CT_ID"
fi

echo "[*] Creating LXC $CT_ID ($CT_NAME)..."
pct create "$CT_ID" "local:vztmpl/$(basename "$TEMPLATE_ID")" \
  --hostname "$CT_NAME" --password "$CT_PASS" \
  --net0 "name=eth0,bridge=vmbr1,ip=$IP_ADDR,gw=$GATEWAY" \
  --storage "$STORAGE" --rootfs "$STORAGE:$DISK_SIZE" --unprivileged 1

pct start "$CT_ID"
echo "[*] Waiting for network stack..."
for i in {1..30}; do pct exec "$CT_ID" -- ping -c1 8.8.8.8 >/dev/null 2>&1 && break; sleep 1; done

# --- System Dependencies & User Setup ---
echo "[*] Installing Python & Dependencies..."
pct exec "$CT_ID" -- apt-get update
pct exec "$CT_ID" -- env DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-pip python3-venv curl

echo "[*] Creating isolated environment for LiteLLM..."
pct exec "$CT_ID" -- useradd -m -s /bin/bash litellm
pct exec "$CT_ID" -- sudo -u litellm python3 -m venv /home/litellm/venv
pct exec "$CT_ID" -- sudo -u litellm /home/litellm/venv/bin/pip install 'litellm[proxy]'

# --- Configuration Injection ---
echo "[*] Injecting Custom Pricing Configuration..."
pct exec "$CT_ID" -- bash -c "cat << 'YAML_EOF' > /home/litellm/config.yaml
model_list:
  - model_name: llama3-local
    litellm_params:
      model: ollama/llama3
      api_base: \"http://${OLLAMA_IP}:11434\"
    model_info:
      input_cost_per_token: 0.000001
      output_cost_per_token: 0.000002
YAML_EOF"

pct exec "$CT_ID" -- chown litellm:litellm /home/litellm/config.yaml

# --- Systemd Daemon Setup ---
echo "[*] Creating Systemd Service..."
pct exec "$CT_ID" -- bash -c "cat << 'SERVICE_EOF' > /etc/systemd/system/litellm.service
[Unit]
Description=LiteLLM Proxy Server
After=network.target

[Service]
User=litellm
Group=litellm
WorkingDirectory=/home/litellm
ExecStart=/home/litellm/venv/bin/litellm --config /home/litellm/config.yaml --port 4000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SERVICE_EOF"

pct exec "$CT_ID" -- systemctl daemon-reload
pct exec "$CT_ID" -- systemctl enable litellm
pct exec "$CT_ID" -- systemctl start litellm

echo "=========================================================================="
echo "HEARTBEAT_OK: LiteLLM Proxy is LIVE."
echo "API Endpoint:    http://10.0.0.124:4000"
echo "Model Alias:     llama3-local"
echo "Ollama Upstream: http://${OLLAMA_IP}:11434"
echo "Paperclip Setup: Point Base URL to 10.0.0.124:4000 and use any dummy API Key."
echo "=========================================================================="
