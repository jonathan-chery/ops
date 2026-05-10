# Generates a highly restrictive systemd service
fw_create_service() {
    local service_name="$1"
    local exec_start="$2"
    local work_dir="$3"
    
    cat > /tmp/svc.service <<EOF
[Unit]
Description=Managed Service: ${service_name}
After=network-online.target

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${work_dir}
ExecStart=${exec_start}
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${work_dir}
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
    pct push "$CT_ID" /tmp/svc.service "/etc/systemd/system/${service_name}.service"
    pct exec "$CT_ID" -- systemctl daemon-reload
    pct exec "$CT_ID" -- systemctl enable --now "${service_name}.service"
}