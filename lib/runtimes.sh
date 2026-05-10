# File: lib/runtimes.sh

fw_install_system_packages() {
    local pkgs="$1"
    pct exec "$CT_ID" -- bash -c "export DEBIAN_FRONTEND=noninteractive; apt-get update -y && apt-get install -y ${pkgs}" >/dev/null
}

fw_git_clone_tag() {
    local repo_url="$1"
    local dest_dir="$2"
    local tag="$3"
    
    pct exec "$CT_ID" -- rm -rf "$dest_dir"
    pct exec "$CT_ID" -- git clone "$repo_url" "$dest_dir" >/dev/null 2>&1
    pct exec "$CT_ID" -- bash -c "cd ${dest_dir} && git checkout ${tag}" >/dev/null 2>&1
    pct exec "$CT_ID" -- chown -R "${APP_USER}:${APP_USER}" "$dest_dir"
}

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