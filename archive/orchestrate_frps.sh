#!/bin/bash
# Description: Proxmox Orchestrator for FRP Server (frps)
set -euo pipefail

# --- Global State & Configuration ---
CT_ID="160"
CT_NAME="frps-server"
STORAGE="local"
DISK_SIZE="4" # FRP is tiny, 4GB is plenty
IP_ADDR="10.0.0.160/24"
GATEWAY="10.0.0.254"
CT_PASS=$(openssl rand -base64 15)

FRP_DOMAIN="frp.cloudinit.dev"
FRP_TOKEN=$(openssl rand -hex 16)
DASHBOARD_USER="admin"

echo "=========================================================================="
echo " FRP Server Provisioner (frps)"
echo "=========================================================================="

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

# --- System Prep & Installation ---
echo "[*] Installing dependencies..."
pct exec "$CT_ID" -- apt-get update
pct exec "$CT_ID" -- env DEBIAN_FRONTEND=noninteractive apt-get install -y curl wget tar jq

echo "[*] Fetching latest FRP release from GitHub..."
pct exec "$CT_ID" -- bash -c '
    LATEST_TAG=$(curl -s https://api.github.com/repos/fatedier/frp/releases/latest | jq -r .tag_name)
    VERSION=${LATEST_TAG#v}
    echo "Downloading FRP version v${VERSION}..."
    cd /tmp
    wget -q "https://github.com/fatedier/frp/releases/download/v${VERSION}/frp_${VERSION}_linux_amd64.tar.gz"
    tar -xzf "frp_${VERSION}_linux_amd64.tar.gz"
    mv "frp_${VERSION}_linux_amd64/frps" /usr/local/bin/
    mkdir -p /etc/frp
    rm -rf /tmp/frp_*
'

# --- Configuration Generation ---
echo "[*] Generating frps.toml..."
cat << TOML_EOF > /tmp/frps.toml
bindPort = 7000
vhostHTTPPort = 8080
vhostHTTPSPort = 4433

auth.method = "token"
auth.token = "${FRP_TOKEN}"

# Enable the built-in dashboard
webServer.addr = "0.0.0.0"
webServer.port = 7500
webServer.user = "${DASHBOARD_USER}"
webServer.password = "${FRP_TOKEN}"
TOML_EOF

pct push "$CT_ID" /tmp/frps.toml /etc/frp/frps.toml
rm /tmp/frps.toml

# --- Systemd Service ---
echo "[*] Creating Systemd Service Wrapper..."
cat << 'SERVICE_EOF' > /tmp/frps.service
[Unit]
Description=FRP Server Proxy
After=network.target

[Service]
Type=simple
Restart=on-failure
RestartSec=5s
ExecStart=/usr/local/bin/frps -c /etc/frp/frps.toml
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
SERVICE_EOF

pct push "$CT_ID" /tmp/frps.service /etc/systemd/system/frps.service
rm /tmp/frps.service

pct exec "$CT_ID" -- systemctl daemon-reload
pct exec "$CT_ID" -- systemctl enable --now frps

# --- Generate Client Template Snippet ---
echo "[*] Generating Client Template in Proxmox Snippets..."
mkdir -p /var/lib/pve/local/snippets/frp
cat << CLIENT_EOF > /var/lib/pve/local/snippets/frp/client_template.toml
# Client config (frpc.toml) for connecting to LXC $CT_ID
serverAddr = "${FRP_DOMAIN}"
serverPort = 7000

auth.method = "token"
auth.token = "${FRP_TOKEN}"

# Example Web Proxy
[[proxies]]
name = "example-web"
type = "http"
localPort = 80
customDomains = ["myapp.${FRP_DOMAIN}"]
CLIENT_EOF

echo "=========================================================================="
echo "HEARTBEAT_OK: FRP Server is LIVE."
echo "Dashboard:       http://${IP_ADDR%/*}:7500 (User: $DASHBOARD_USER | Pass: $FRP_TOKEN)"
echo "Client Snippet:  /var/lib/pve/local/snippets/frp/client_template.toml"
echo "=========================================================================="
