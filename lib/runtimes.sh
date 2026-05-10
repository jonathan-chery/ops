# Installs a specific Node LTS version securely
fw_install_nodejs() {
    local version="$1"
    pct exec "$CT_ID" -- bash -c "curl -fsSL https://deb.nodesource.com/setup_${version}.x | bash -"
    pct exec "$CT_ID" -- bash -c 'export DEBIAN_FRONTEND=noninteractive; apt-get install -y nodejs'
}

fw_install_pnpm() {
    pct exec "$CT_ID" -- corepack enable
    pct exec "$CT_ID" -- corepack prepare pnpm@latest --activate
}