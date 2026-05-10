# apps/deep-research/bootstrap.sh

# --- 1. Container Specs ---
CT_ID=180
CT_HOSTNAME="deepresearch"
CT_IP_CIDR="10.0.0.180/24"
CT_GW="10.0.0.254"
CT_MEM=4096
CT_CORES=2
APP_USER="deeprun"
APP_DIR="/opt/deep-research"

# --- 2. Deployment Hooks ---

hook_install_deps() {
    # Leveraging the shared framework methods
    fw_install_system_packages "git curl wget build-essential python3"
    fw_install_nodejs 22
    fw_install_pnpm
}

hook_fetch() {
    fw_git_clone_tag "https://github.com/AnotiaWang/deep-research-web-ui.git" "$APP_DIR" "v1.2.0"
}

hook_build() {
    # Run commands as the unprivileged app user
    fw_exec_as_user "$APP_USER" "$APP_DIR" "pnpm install --frozen-lockfile"
    
    # Inject memory constraints via framework for Next.js
    fw_exec_as_user_with_env "$APP_USER" "$APP_DIR" \
        "NODE_OPTIONS='--max-old-space-size=3072' NEXT_TELEMETRY_DISABLED=1" \
        "pnpm build"
}

hook_configure() {
    # Push the template from the app's local folder to the CT
    fw_push_template "apps/deep-research/templates/env.tpl" "$APP_DIR/.env"
}

hook_service() {
    # Create the compliant systemd daemon
    fw_create_service "deepresearch" "/usr/bin/npm run start" "$APP_DIR"
}