#!/bin/bash
# Description: Generates and injects SSH keys for out-of-band LXC containers.

if [ -z "$1" ]; then
    echo "Usage: ./onboard_ct.sh <CTID or Hostname>"
    echo "Example: ./onboard_ct.sh 105"
    echo "Example: ./onboard_ct.sh my-legacy-app"
    exit 1
fi

TARGET="$1"
SNIPPET_DIR="/var/lib/pve/local/snippets"
mkdir -p "$SNIPPET_DIR"

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
    echo "Error: Container $CTID is not running. Please start it first to allow key injection."
    exit 1
fi

# 3. Extract Hostname
CT_HOSTNAME=$(pct config "$CTID" | awk -F': ' '/^hostname/ {print $2}')

# 4. Manage SSH Key Generation
KEY_FILE="$SNIPPET_DIR/${CT_HOSTNAME}_id_ed25519"

if [ -f "$KEY_FILE" ]; then
    echo "[*] Key pair already exists at $KEY_FILE. Proceeding with injection..."
else
    echo "[+] Generating new Ed25519 key pair for $CT_HOSTNAME..."
    ssh-keygen -t ed25519 -N "" -f "$KEY_FILE"
    chmod 600 "$KEY_FILE"
fi

PUB_KEY=$(cat "${KEY_FILE}.pub")

# 5. Inject Key into Container
echo "[*] Injecting public key into LXC $CTID ($CT_HOSTNAME)..."

# Ensure SSH directory structure exists with strict permissions
pct exec "$CTID" -- mkdir -p /root/.ssh
pct exec "$CTID" -- chmod 700 /root/.ssh

# Append key (checking first to avoid duplicate entries if run multiple times)
pct exec "$CTID" -- bash -c "grep -qF '$PUB_KEY' /root/.ssh/authorized_keys 2>/dev/null || echo '$PUB_KEY' >> /root/.ssh/authorized_keys"

# Enforce secure file permissions
pct exec "$CTID" -- chmod 600 /root/.ssh/authorized_keys

echo "=========================================================================="
echo "SUCCESS: Container $CT_HOSTNAME has been onboarded."
echo "You can now connect instantly using:"
echo "/root/ops/ct_ssh.sh $CTID"
echo "  -- or --"
echo "/root/ops/ct_ssh.sh $CT_HOSTNAME"
echo "=========================================================================="
