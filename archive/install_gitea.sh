#!/bin/bash
# Description: Authoritative Proxmox LXC provisioning for Ubuntu 24.04 with Gitea, strict SSH overrides, and Failover IP routing.

# --- Configuration & State Management ---
CT_ID="105"
CT_NAME="gitea-server"
STORAGE="local"
DISK_SIZE="40" # Adjusted for git repository storage
SNIPPET_DIR="/var/lib/pve/local/snippets"

# --- Failover Network Configuration ---
# Update these to match your specific network routing needs
IP_ADDR="10.0.0.105/24" 
GATEWAY="10.0.0.254"

mkdir -p "$SNIPPET_DIR"

# 1. State Persistence: Credentials
CT_PASSWORD=$(openssl rand -base64 15)
echo "$CT_PASSWORD" > "$SNIPPET_DIR/${CT_NAME}_pwd.txt"

SSH_KEY_FILE="$SNIPPET_DIR/${CT_NAME}_id_ed25519"
[ ! -f "$SSH_KEY_FILE" ] && ssh-keygen -t ed25519 -N "" -f "$SSH_KEY_FILE"

# 2. Template Selection
echo "Updating Proxmox templates..."
pveam update > /dev/null
TEMPLATE_ID=$(pveam available | grep "ubuntu-24.04" | head -n1 | awk '{print $2}')
[ -z "$TEMPLATE_ID" ] && { echo "Error: Template not found"; exit 1; }

if ! pveam list local | grep -q "$(basename "$TEMPLATE_ID")"; then
    echo "Downloading template..."
    pveam download local "$TEMPLATE_ID"
fi

# 3. Clean Slate Enforcement
if pct status "$CT_ID" &>/dev/null; then
    echo "Destroying existing container $CT_ID for clean architecture build..."
    pct stop "$CT_ID" 2>/dev/null
    pct destroy "$CT_ID"
fi

# 4. Provisioning (Native Key Injection & Network Routing)
pct create "$CT_ID" "local:vztmpl/$(basename "$TEMPLATE_ID")" \
  --hostname "$CT_NAME" \
  --password "$CT_PASSWORD" \
  --ssh-public-keys "${SSH_KEY_FILE}.pub" \
  --net0 "name=eth0,bridge=vmbr1,ip=$IP_ADDR,gw=$GATEWAY" \
  --storage "$STORAGE" \
  --rootfs "$STORAGE:$DISK_SIZE" \
  --unprivileged 1 \
  --features nesting=1

pct start "$CT_ID"

# Allow network stack and container initialization
echo "Waiting for container initialization..."
sleep 10

# 5. Execution Loop: Base Packages & Strict SSH Override
pct exec "$CT_ID" -- apt-get update
pct exec "$CT_ID" -- apt-get install -y openssh-server wget curl git sqlite3

pct exec "$CT_ID" -- bash -c "cat <<EOF > /etc/ssh/sshd_config.d/99-override.conf
PermitRootLogin yes
PasswordAuthentication yes
PubkeyAuthentication yes
EOF"

pct exec "$CT_ID" -- systemctl restart ssh

# 6. Execution Loop: Gitea Service Architecture
pct exec "$CT_ID" -- bash -c '
  # Create the git user non-interactively
  useradd -r -m -d /home/git -s /bin/bash -c "Git Version Control" git

  # Prepare environment and permissions
  mkdir -p /var/lib/gitea/{custom,data,log}
  chown -R git:git /var/lib/gitea/
  chmod -R 750 /var/lib/gitea/
  
  mkdir /etc/gitea
  chown root:git /etc/gitea
  chmod 770 /etc/gitea

  # Dynamically fetch the latest stable release version from GitHub API
  VERSION=$(curl -s https://api.github.com/repos/go-gitea/gitea/releases/latest | grep "\"tag_name\":" | cut -d"\"" -f4 | sed "s/v//")
  echo "Downloading Gitea version ${VERSION}..."
  
  # Download and install binary
  wget -q -O /usr/local/bin/gitea "https://dl.gitea.com/gitea/${VERSION}/gitea-${VERSION}-linux-amd64"
  chmod +x /usr/local/bin/gitea

  # Fetch the official systemd service file
  wget -q -O /etc/systemd/system/gitea.service https://raw.githubusercontent.com/go-gitea/gitea/main/contrib/systemd/gitea.service

  # Enable and start Gitea
  systemctl daemon-reload
  systemctl enable --now gitea
'

echo "HEARTBEAT_OK: Container rebuilt. SSH is active and Gitea is running on http://${IP_ADDR%/*}:3000"
echo "Note: Complete the web configuration at the URL above, then run 'pct exec $CT_ID -- chmod 640 /etc/gitea/app.ini' to secure the config file."
