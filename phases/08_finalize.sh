#!/bin/bash
set -euo pipefail

# Clean up default ubuntu packages that might be taking up ports
pct exec "$CT_ID" -- bash -c 'rm -f /etc/nginx/sites-enabled/default 2>/dev/null; true'

# Ensure heartbeat directory exists on the host
mkdir -p "${HEARTBEAT_DIR}"
HEARTBEAT_TIMESTAMP=$(date +%Y%m%d_%H%M%S)
HEARTBEAT_FILE="${HEARTBEAT_DIR}/ct${CT_ID}_${CT_HOSTNAME}_${HEARTBEAT_TIMESTAMP}.txt"
HEARTBEAT_LATEST="${HEARTBEAT_DIR}/ct${CT_ID}_${CT_HOSTNAME}_latest.txt"

# Generate Deployment Manifest/Heartbeat
cat <<HEARTBEAT | tee "$HEARTBEAT_FILE"

╔══════════════════════════════════════════════════════════════════╗
║                        HEARTBEAT_OK                            ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                ║
║  Application:  ${APP_NAME}                                     ║
║  Release Tag:  ${RELEASE_TAG}                                  ║
║  CT ID:        ${CT_ID}                                        ║
║  CT Hostname:  ${CT_HOSTNAME}                                  ║
║  Deployed:     $(date +%Y-%m-%d\ %H:%M:%S\ %Z)                 ║
║                                                                ║
║  URLs:                                                         ║
║    HTTP:       http://${CT_IP}:${APP_PORT}                     ║
║                                                                ║
║  In-Container Config:                                          ║
║    .env File:  ${APP_DIR}/.env                                 ║
║    → Edit this file to add your AI provider API keys           ║
║    → Then: pct exec ${CT_ID} -- systemctl restart ${APP_NAME}  ║
║                                                                ║
║  SSH Access:                                                   ║
║    ssh -i ${SNIPPET_DIR}/ct${CT_ID}_ed25519 root@${CT_IP}      ║
║                                                                ║
╚══════════════════════════════════════════════════════════════════╝
HEARTBEAT

ln -sf "$HEARTBEAT_FILE" "$HEARTBEAT_LATEST"
chmod 600 "$HEARTBEAT_FILE"

echo ""
echo "Deployment Complete. Heartbeat persisted to: ${HEARTBEAT_FILE}"