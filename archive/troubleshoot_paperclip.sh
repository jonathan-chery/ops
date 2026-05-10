#!/bin/bash
# Description: Holistic diagnostic probe for the Paperclip AI stack
CT_ID="150"

echo "=========================================================================="
echo " Paperclip Diagnostics & Troubleshooting Report (LXC $CT_ID)"
echo "=========================================================================="

# 1. LXC Check
echo -e "\n[1] Checking LXC Status..."
pct status "$CT_ID"

# 2. Systemd Wrapper Check
echo -e "\n[2] Checking Systemd Wrapper (paperclip.service)..."
pct exec "$CT_ID" -- systemctl is-active paperclip || echo "STATUS: NOT ACTIVE"
pct exec "$CT_ID" -- journalctl -u paperclip -n 15 --no-pager

# 3. Docker Container Status
echo -e "\n[3] Checking Docker Container States..."
pct exec "$CT_ID" -- docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# 4. Postgres Database Logs
echo -e "\n[4] Database Logs (paperclip_db) - Last 15 lines:"
pct exec "$CT_ID" -- docker logs paperclip_db --tail 15 2>&1 || echo "Container not found"

# 5. Paperclip App Logs (The most likely culprit)
echo -e "\n[5] Paperclip App Logs (paperclip) - Last 40 lines:"
pct exec "$CT_ID" -- docker logs paperclip --tail 40 2>&1 || echo "Container not found"

# 6. Network Binding Check
echo -e "\n[6] Checking internal network port binding (3100)..."
pct exec "$CT_ID" -- ss -tulpn | grep 3100 || echo "WARNING: Nothing is listening on port 3100 inside the LXC."

echo -e "\n=========================================================================="
echo " Diagnostic complete."
echo "=========================================================================="
