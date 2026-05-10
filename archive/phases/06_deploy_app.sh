#!/bin/bash
set -euo pipefail

# Backup existing .env if present
pct exec "$CT_ID" -- bash -c "if [ -f ${APP_DIR}/.env ]; then cp ${APP_DIR}/.env /tmp/app_env_backup; fi"
pct exec "$CT_ID" -- bash -c "rm -rf ${APP_DIR}"

# Clone and checkout specific tag
echo "Cloning and checking out tag ${RELEASE_TAG}..."
pct exec "$CT_ID" -- git clone "$REPO_URL" "$APP_DIR"
pct exec "$CT_ID" -- bash -c "cd ${APP_DIR} && git checkout ${RELEASE_TAG}"
pct exec "$CT_ID" -- chown -R "${APP_USER}:${APP_USER}" "$APP_DIR"

# Install Node dependencies
pct exec "$CT_ID" -- su - "$APP_USER" -s /bin/bash <<INNER_INSTALL
cd ${APP_DIR}
pnpm install --frozen-lockfile 2>/dev/null || pnpm install
INNER_INSTALL

# Build Next.js application (with memory limits and telemetry disabled)
echo "Building application (allocating more RAM to Node)..."
pct exec "$CT_ID" -- su - "$APP_USER" -s /bin/bash <<INNER_BUILD
cd ${APP_DIR}
export NEXT_TELEMETRY_DISABLED=1
export NODE_OPTIONS="--max-old-space-size=3072"
pnpm build
INNER_BUILD

# Restore or Create .env
if pct exec "$CT_ID" -- test -f /tmp/app_env_backup; then
    pct exec "$CT_ID" -- bash -c "cp /tmp/app_env_backup ${APP_DIR}/.env && rm -f /tmp/app_env_backup"
else
    NEXTAUTH_SECRET_VAL=$(ensure_secret "${SNIPPET_DIR}/${APP_NAME}_nextauth_secret.txt" "NEXTAUTH secret" 48)
    cat > /tmp/app_env <<INNER_ENV
NEXTAUTH_SECRET="${NEXTAUTH_SECRET_VAL}"
NEXTAUTH_URL="http://${CT_IP}:${APP_PORT}"
PORT=${APP_PORT}
NODE_ENV=production
NEXT_TELEMETRY_DISABLED=1

# === AI Providers ===
# OPENAI_API_KEY=
# DEEPSEEK_API_KEY=
# OLLAMA_API_BASE=http://your-ollama-ip:11434
# SILICONFLOW_API_KEY=

# === Search Providers ===
# GOOGLE_API_KEY=
# GOOGLE_SEARCH_API_KEY=
# TAVILY_API_KEY=
# SEARXNG_API_BASE=
INNER_ENV
    pct push "$CT_ID" /tmp/app_env "${APP_DIR}/.env"
    rm -f /tmp/app_env
fi

pct exec "$CT_ID" -- chown "${APP_USER}:${APP_USER}" "${APP_DIR}/.env"
pct exec "$CT_ID" -- chmod 600 "${APP_DIR}/.env"