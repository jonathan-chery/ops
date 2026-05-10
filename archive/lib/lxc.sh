# File: lib/lxc.sh

# Fallbacks in case the app bootstrap doesn't define them
CT_STORAGE="${CT_STORAGE:-local}"
CT_DISK="${CT_DISK:-20}"
CT_BRIDGE="${CT_BRIDGE:-vmbr1}"
CT_DNS="${CT_DNS:-1.1.1.1 8.8.8.8}"
PHASE_FILE="/tmp/fw_ct${CT_ID}_phases"

fw_get_state() { grep -qx "$1" "$PHASE_FILE" 2>/dev/null; }
fw_set_state() { echo "$1" >> "$PHASE_FILE"; }

fw_lxc_provision() {
    echo "--> [INFRA] Provisioning LXC Container ${CT_ID}..."

    if fw_get_state "lxc_provisioned"; then
        echo "    [SKIP] Container ${CT_ID} already provisioned."
        return 0
    fi

    # Grab the latest Ubuntu 24.04 template
    local template
    template=$(pveam available 2>/dev/null | grep -i 'ubuntu-24.04' | grep 'standard' | awk '{print $NF}' | sort -V | tail -1)
    
    if ! pveam list local 2>/dev/null | grep -q "$template"; then
        echo "    Downloading template: $template..."
        pveam download local "$template" >/dev/null
    fi

    # Generate a strong root password securely
    local root_pw
    root_pw=$(fw_ensure_generated_secret "root_passwd" 32)

    echo "    Creating CT ${CT_ID} on ${CT_BRIDGE}..."
    pct create "$CT_ID" "local:vztmpl/${template}" \
        --hostname "$CT_HOSTNAME" \
        --memory "$CT_MEM" \
        --cores "$CT_CORES" \
        --storage "$CT_STORAGE" \
        --rootfs "${CT_STORAGE}:${CT_DISK}" \
        --net0 "name=eth0,bridge=${CT_BRIDGE},ip=${CT_IP_CIDR},gw=${CT_GW}" \
        --nameserver "$CT_DNS" \
        --password "$root_pw" \
        --unprivileged 1 \
        --features "nesting=1" \
        --onboot 1 \
        --startup "order=18,up=30,down=30" >/dev/null

    pct start "$CT_ID"
    
    echo "    Waiting for network..."
    for i in {1..30}; do
        if pct exec "$CT_ID" -- bash -c 'ping -c1 -W2 1.1.1.1 &>/dev/null'; then break; fi
        sleep 2
    done

    # Base sysctl tuning for Node.js apps
    pct exec "$CT_ID" -- bash -c 'echo "fs.inotify.max_user_watches=524288" >> /etc/sysctl.conf'
    pct exec "$CT_ID" -- sysctl -p /etc/sysctl.conf >/dev/null
    pct exec "$CT_ID" -- timedatectl set-timezone UTC

    fw_set_state "lxc_provisioned"
    echo "    [OK] LXC Provisioning complete."
}

fw_lxc_teardown() {
    echo "--> [INFRA] Destroying LXC Container ${CT_ID}..."
    if pct list 2>/dev/null | awk '{print $1}' | grep -qx "${CT_ID}"; then
        pct stop "$CT_ID" 2>/dev/null || true
        sleep 3
        pct destroy "$CT_ID" --purge 2>/dev/null || pct destroy "$CT_ID"
        echo "    [OK] Container destroyed."
    else
        echo "    [SKIP] Container ${CT_ID} does not exist."
    fi
    rm -f "$PHASE_FILE"
}