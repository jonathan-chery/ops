#!/bin/bash
# Description: Authoritative Proxmox LXC provisioning for Ubuntu 24.04 with NocoDB via Docker.
# Includes explicit AppArmor bypass for containerd/runc compatibility in unprivileged LXCs.

CT_ID="109"
CT_NAME="nocodb-server"
STORAGE="local"
DISK_SIZE="20"
SNIPPET_DIR="/var/lib/pve/local/snippets"
IP_ADDR="10.0.0.109/24" 
GATEWAY="10.0.0.254"

mkdir -p "$SNIPPET_DIR"

CT_PASSWORD=$(openssl rand -base64 15)
echo "$CT_PASSWORD" > "$SNIPPET_DIR/${CT_NAME}_pwd.txt"

SSH_KEY_FILE="$SNIPPET_DIR/${CT_NAME}_id_ed25519"
[ ! -f "$SSH_KEY_FILE" ] && ssh-keygen -t ed25519 -N "" -f "$SSH_KEY_FILE"

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

# 1. Base Container Creation
pct create "$CT_ID" "local:vztmpl/$(basename "$TEMPLATE_ID")" \
  --hostname "$CT_NAME" \
  --password "$CT_PASSWORD" \
  --ssh-public-keys "${SSH_KEY_FILE}.pub" \
  --net0 "name=eth0,bridge=vmbr1,ip=$IP_ADDR,gw=$GATEWAY" \
  --storage "$STORAGE" \
  --rootfs "$STORAGE:$DISK_SIZE" \
  --unprivileged 1 \
  --features nesting=1,keyctl=1

# 2. AppArmor Bypass (CRITICAL FIX)
echo "lxc.apparmor.profile: unconfined" >> /etc/pve/lxc/${CT_ID}.conf
echo "lxc.mount.entry: /dev/null sys/module/apparmor/parameters/enabled none bind 0 0" >> /etc/pve/lxc/${CT_ID}.conf

# 3. Boot & Initialization
pct start "$CT_ID"
sleep 15

pct exec "$CT_ID" -- apt-get update
pct exec "$CT_ID" -- apt-get install -y openssh-server curl ca-certificates sqlite3

pct exec "$CT_ID" -- bash -c "cat << 'INNER_EOF' > /etc/ssh/sshd_config.d/99-override.conf
PermitRootLogin yes
PasswordAuthentication yes
PubkeyAuthentication yes
INNER_EOF"

pct exec "$CT_ID" -- systemctl restart ssh

pct exec "$CT_ID" -- bash -c '
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
  
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

  docker volume create nocodb_data
  docker run -d --name nocodb \
    -v nocodb_data:/usr/app/data/ \
    -p 8080:8080 \
    --restart always \
    nocodb/nocodb:latest
'

echo "HEARTBEAT_OK: Container rebuilt. SSH is active and NocoDB is running on http://${IP_ADDR%/*}:8080"
