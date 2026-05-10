#!/bin/bash
set -euo pipefail

# Create the startup script
cat > /tmp/app_start.sh <<STARTSCRIPT
#!/bin/bash
set -euo pipefail
cd ${APP_DIR}
export NODE_ENV=production
export PORT=${APP_PORT}
export NEXT_TELEMETRY_DISABLED=1
exec pnpm start
STARTSCRIPT

pct push "$CT_ID" /tmp/app_start.sh "${APP_DIR}/start.sh"
pct exec "$CT_ID" -- chmod 755 "${APP_DIR}/start.sh"
pct exec "$CT_ID" -- chown "${APP_USER}:${APP_USER}" "${APP_DIR}/start.sh"
rm -f /tmp/app_start.sh

# Create the systemd unit file
cat > /tmp/app.service <<UNITFILE
[Unit]
Description=${APP_NAME}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/start.sh
Restart=on-failure
RestartSec=10
StartLimitIntervalSec=60
StartLimitBurst=3

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=false
ProtectKernelTunables=true
ProtectControlGroups=true
ReadWritePaths=${APP_DIR}
PrivateTmp=true

# Environment
Environment=NODE_ENV=production
EnvironmentFile=${APP_DIR}/.env

[Install]
WantedBy=multi-user.target
UNITFILE

pct push "$CT_ID" /tmp/app.service "/etc/systemd/system/${APP_NAME}.service"
rm -f /tmp/app.service

pct exec "$CT_ID" -- systemctl daemon-reload
pct exec "$CT_ID" -- systemctl enable --now "${APP_NAME}.service"

echo "Waiting for service to start..."
sleep 5