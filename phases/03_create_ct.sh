#!/bin/bash
set -euo pipefail

# Ensure state scripts and secrets functions are available
source lib/secrets.sh
source lib/proxmox.sh

validate_storage "$CT_STORAGE"
TEMPLATE=$(get_ubuntu_template)
ROOT_PASSWD=$(ensure_secret "${SNIPPET_DIR}/${APP_NAME}_root_passwd.txt" "Root password" 32)

pct create "$CT_ID" "local:vztmpl/${TEMPLATE}" \
    --hostname "$CT_HOSTNAME" --memory "$CT_MEM" --swap "$CT_SWAP" --cores "$CT_CORES" \
    --storage "$CT_STORAGE" --rootfs "${CT_STORAGE}:${CT_DISK}" \
    --net0 "name=eth0,bridge=${CT_BRIDGE},ip=${CT_IP_CIDR},gw=${CT_GW}" \
    --nameserver "$CT_DNS" --password "$ROOT_PASSWD" \
    --unprivileged 1 --features "nesting=1" --onboot 1

pct start "$CT_ID"
sleep 10
pct exec "$CT_ID" -- timedatectl set-timezone UTC