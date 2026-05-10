#!/bin/bash
# Description: Discovers the correct SSH key and connects to a Proxmox LXC.

if [ -z "$1" ]; then
    echo "Usage: ./ct_ssh.sh <CTID or Hostname>"
    echo "Example: ./ct_ssh.sh 107"
    echo "Example: ./ct_ssh.sh zitadel-server"
    exit 1
fi

TARGET="$1"
SNIPPET_DIR="/var/lib/pve/local/snippets"

# 1. Resolve Target to CTID
if [[ "$TARGET" =~ ^[0-9]+$ ]]; then
    CTID="$TARGET"
else
    CTID=$(pct list | awk -v name="$TARGET" '$3 == name {print $1}')
    if [ -z "$CTID" ]; then
        echo "Error: Could not find container with hostname '$TARGET'."
        exit 1
    fi
fi

# 2. Verify Container State
if ! pct status "$CTID" &>/dev/null; then
    echo "Error: Container $CTID does not exist."
    exit 1
fi

if [[ "$(pct status "$CTID" | awk '{print $2}')" != "running" ]]; then
    echo "Error: Container $CTID is not running."
    exit 1
fi

# 3. Extract Hostname & IP Address
CT_HOSTNAME=$(pct config "$CTID" | awk -F': ' '/^hostname/ {print $2}')
# Use lxc-info to dynamically grab the IP (handles both static and DHCP)
CT_IP=$(lxc-info -n "$CTID" -iH | grep -v ":" | head -n1)

if [ -z "$CT_IP" ]; then
    echo "Error: Could not determine IPv4 address for $CT_HOSTNAME."
    exit 1
fi

# 4. Discover SSH Key
KEY_FILE="$SNIPPET_DIR/${CT_HOSTNAME}_id_ed25519"
# Suppress strict host checking so it doesn't complain when containers are destroyed/rebuilt on the same IP
SSH_ARGS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -q"

if [ -f "$KEY_FILE" ]; then
    echo "[*] Discovered SSH Key: $KEY_FILE"
    SSH_ARGS="$SSH_ARGS -i $KEY_FILE"
else
    echo "[!] No dedicated SSH key found at $KEY_FILE. Falling back to default auth."
fi

# 5. Execute Connection
echo "[*] Connecting to root@$CT_IP ($CT_HOSTNAME)..."
exec ssh $SSH_ARGS root@"$CT_IP"
