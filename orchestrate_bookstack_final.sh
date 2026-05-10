#!/bin/bash
# Description: FINAL Hardened Orchestrator for BookStack (LXC 123) + MariaDB (LXC 122).
# Includes: OIDC Audience Fix, Proxy Trust, and Environment Variable fixes.
set -euo pipefail

# --- Global State & Configuration ---
CT_ID_DB="122"
CT_NAME_DB="mariadb-bookstack-prod"
CT_ID_APP="123"
CT_NAME_APP="bookstack-prod"

STORAGE="local"
DISK_SIZE_DB="10"
DISK_SIZE_APP="15"
SNIPPET_DIR="/var/lib/pve/local/snippets"

IP_ADDR_DB="10.0.0.122/24"
IP_ADDR_APP="10.0.0.123/24"
GATEWAY="10.0.0.254"

DOMAIN="docs.cloudinit.dev"
OIDC_ISSUER="https://login.cloudinit.dev"

DB_NAME="bookstack"
DB_USER="bookstack"

STATE_FILE="/root/ops/.bookstack_final_state"
get_state() { cat "$STATE_FILE" 2>/dev/null || echo "1"; }
set_state() { echo "$1" > "$STATE_FILE"; }
PHASE=$(get_state)

mkdir -p "$SNIPPET_DIR"

# --- State Persistence & Generation ---
[ ! -f "$SNIPPET_DIR/${CT_NAME_APP}_db_pwd.txt" ] && openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 20 > "$SNIPPET_DIR/${CT_NAME_APP}_db_pwd.txt"
[ ! -f "$SNIPPET_DIR/${CT_NAME_APP}_admin_pwd.txt" ] && openssl rand -base64 20 | tr -dc 'a-zA-Z0-9!@#%^&*' | head -c 16 > "$SNIPPET_DIR/${CT_NAME_APP}_admin_pwd.txt"

DB_PASS=$(cat "$SNIPPET_DIR/${CT_NAME_APP}_db_pwd.txt")
BOOKSTACK_ADMIN_PASS=$(cat "$SNIPPET_DIR/${CT_NAME_APP}_admin_pwd.txt")

CT_PASS=$(openssl rand -base64 15)
SSH_KEY_FILE="$SNIPPET_DIR/${CT_NAME_APP}_id_ed25519"
[ ! -f "$SSH_KEY_FILE" ] && ssh-keygen -t ed25519 -N "" -f "$SSH_KEY_FILE"

chmod 600 "$SNIPPET_DIR"/*.txt 2>/dev/null || true

# --- Template Fetching ---
pveam update > /dev/null
TEMPLATE_ID=$(pveam available | grep "ubuntu-24.04" | head -n1 | awk '{print $2}')
[ -z "$TEMPLATE_ID" ] && { echo "FATAL: Template not found"; exit 1; }
pveam list local | grep -q "$(basename "$TEMPLATE_ID")" || pveam download local "$TEMPLATE_ID"

# ==========================================================================
if [ "$PHASE" -le 1 ]; then
    echo "=========================================================================="
    echo "[PHASE 1]: SECURE DATABASE PROVISIONING (LXC $CT_ID_DB)"
    echo "=========================================================================="

    if pct status "$CT_ID_DB" &>/dev/null; then
        pct stop "$CT_ID_DB" 2>/dev/null || true
        pct destroy "$CT_ID_DB"
    fi

    pct create "$CT_ID_DB" "local:vztmpl/$(basename "$TEMPLATE_ID")" \
      --hostname "$CT_NAME_DB" --password "$CT_PASS" --ssh-public-keys "${SSH_KEY_FILE}.pub" \
      --net0 "name=eth0,bridge=vmbr1,ip=$IP_ADDR_DB,gw=$GATEWAY" \
      --storage "$STORAGE" --rootfs "$STORAGE:$DISK_SIZE_DB" --unprivileged 1

    pct start "$CT_ID_DB"
    echo "Waiting for DB network stack..."
    for i in {1..30}; do pct exec "$CT_ID_DB" -- ping -c1 8.8.8.8 >/dev/null 2>&1 && break; sleep 1; done

    pct exec "$CT_ID_DB" -- apt-get update
    # FIX: Using 'env' for DEBIAN_FRONTEND
    pct exec "$CT_ID_DB" -- env DEBIAN_FRONTEND=noninteractive apt-get install -y mariadb-server

    echo "[*] Configuring MariaDB Network Listener..."
    pct exec "$CT_ID_DB" -- sed -i 's/^bind-address.*/bind-address = 0.0.0.0/' /etc/mysql/mariadb.conf.d/50-server.cnf
    pct exec "$CT_ID_DB" -- systemctl restart mariadb

    echo "[*] Initializing BookStack Database & Users..."
    pct exec "$CT_ID_DB" -- mysql -e "CREATE DATABASE IF NOT EXISTS ${DB_NAME};"
    pct exec "$CT_ID_DB" -- mysql -e "CREATE USER IF NOT EXISTS '${DB_USER}'@'%' IDENTIFIED BY '${DB_PASS}';"
    pct exec "$CT_ID_DB" -- mysql -e "GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'%';"
    pct exec "$CT_ID_DB" -- mysql -e "FLUSH PRIVILEGES;"

    set_state 2
fi

# ==========================================================================
if [ "$PHASE" -le 2 ]; then
    echo ""
    echo "=========================================================================="
    echo "[PHASE 2]: BOOKSTACK ENGINE PROVISIONING (LXC $CT_ID_APP)"
    echo "=========================================================================="

    if pct status "$CT_ID_APP" &>/dev/null; then
        pct stop "$CT_ID_APP" 2>/dev/null || true
        pct destroy "$CT_ID_APP"
    fi

    pct create "$CT_ID_APP" "local:vztmpl/$(basename "$TEMPLATE_ID")" \
      --hostname "$CT_NAME_APP" --password "$CT_PASS" --ssh-public-keys "${SSH_KEY_FILE}.pub" \
      --net0 "name=eth0,bridge=vmbr1,ip=$IP_ADDR_APP,gw=$GATEWAY" \
      --storage "$STORAGE" --rootfs "$STORAGE:$DISK_SIZE_APP" --unprivileged 1

    pct start "$CT_ID_APP"
    echo "Waiting for App network stack..."
    for i in {1..30}; do pct exec "$CT_ID_APP" -- ping -c1 8.8.8.8 >/dev/null 2>&1 && break; sleep 1; done

    pct exec "$CT_ID_APP" -- bash -c "cat << 'INNER_EOF' > /etc/ssh/sshd_config.d/99-override.conf
PermitRootLogin prohibit-password
PasswordAuthentication no
PubkeyAuthentication yes
INNER_EOF"
    pct exec "$CT_ID_APP" -- systemctl restart ssh

    pct exec "$CT_ID_APP" -- apt-get update
    # FIX: Using 'env' for DEBIAN_FRONTEND
    pct exec "$CT_ID_APP" -- env DEBIAN_FRONTEND=noninteractive apt-get install -y \
        git unzip curl nginx mariadb-client \
        php-fpm php-curl php-mbstring php-ldap php-xml php-zip php-gd php-mysql

    echo "[*] Installing Composer & BookStack..."
    pct exec "$CT_ID_APP" -- bash -c "curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer"
    pct exec "$CT_ID_APP" -- git clone https://github.com/BookStackApp/BookStack.git --branch release --single-branch /var/www/bookstack
    
    # FIX: Using absolute path for composer
    pct exec "$CT_ID_APP" -- bash -c "cd /var/www/bookstack && export COMPOSER_ALLOW_SUPERUSER=1 && /usr/local/bin/composer install --no-dev --no-plugins"

    echo "[*] Injecting Configuration..."
    pct exec "$CT_ID_APP" -- cp /var/www/bookstack/.env.example /var/www/bookstack/.env
    pct exec "$CT_ID_APP" -- sed -i "s|^APP_URL=.*|APP_URL=https://${DOMAIN}|" /var/www/bookstack/.env
    pct exec "$CT_ID_APP" -- sed -i "s|^DB_HOST=.*|DB_HOST=10.0.0.122|" /var/www/bookstack/.env
    pct exec "$CT_ID_APP" -- sed -i "s|^DB_DATABASE=.*|DB_DATABASE=${DB_NAME}|" /var/www/bookstack/.env
    pct exec "$CT_ID_APP" -- sed -i "s|^DB_USERNAME=.*|DB_USERNAME=${DB_USER}|" /var/www/bookstack/.env
    pct exec "$CT_ID_APP" -- sed -i "s|^DB_PASSWORD=.*|DB_PASSWORD=${DB_PASS}|" /var/www/bookstack/.env

    echo "[*] Running Migrations..."
    pct exec "$CT_ID_APP" -- bash -c "cd /var/www/bookstack && php artisan key:generate --force"
    pct exec "$CT_ID_APP" -- bash -c "cd /var/www/bookstack && php artisan migrate --force"

    echo "[*] Injecting Secure Admin Credentials (Tinker Fix)..."
    # FIX: Using single-quoted Tinker update to avoid bash expansion errors
    pct exec "$CT_ID_APP" -- bash -c "cd /var/www/bookstack && php artisan tinker --execute='BookStack\Users\Models\User::where(\"id\", 1)->update([\"password\" => Hash::make(\"${BOOKSTACK_ADMIN_PASS}\")]);'"

    set_state 3
fi

# ==========================================================================
if [ "$PHASE" -le 3 ]; then
    echo ""
    echo "=========================================================================="
    echo "[PHASE 3]: ZITADEL OIDC & THEME PATCHING"
    echo "=========================================================================="
    while true; do
        read -p "Enter OIDC Client ID: " OIDC_ID
        if [ -n "$OIDC_ID" ]; then break; fi
    done
    while true; do
        read -p "Enter OIDC Client Secret: " OIDC_SECRET
        if [ -n "$OIDC_SECRET" ]; then break; fi
    done

    echo "[*] Configuring OIDC, Proxies, and Auto-Initiate..."
    # FIX: Ensuring AUTH_METHOD is properly set regardless of commented status
    pct exec "$CT_ID_APP" -- sed -i "s|^#\?\s*AUTH_METHOD=.*|AUTH_METHOD=oidc|" /var/www/bookstack/.env
    
    cat << ENV_EOF >> /var/tmp/bookstack_oidc_patch
AUTH_AUTO_INITIATE=true
APP_PROXIES=*
APP_THEME=custom
OIDC_CLIENT_ID=${OIDC_ID}
OIDC_CLIENT_SECRET=${OIDC_SECRET}
OIDC_ISSUER=${OIDC_ISSUER}
OIDC_ISSUER_DISCOVER=true
OIDC_NAME_CLAIM=name
OIDC_EMAIL_CLAIM=email
OIDC_EXTERNAL_ID_CLAIM=sub
ENV_EOF
    
    pct push "$CT_ID_APP" /var/tmp/bookstack_oidc_patch /tmp/oidc.patch
    pct exec "$CT_ID_APP" -- bash -c "cat /tmp/oidc.patch >> /var/www/bookstack/.env && rm /tmp/oidc.patch"
    rm /var/tmp/bookstack_oidc_patch

    echo "[*] Applying OIDC Audience Fix (Logical Theme)..."
    pct exec "$CT_ID_APP" -- mkdir -p /var/www/bookstack/themes/custom
    pct exec "$CT_ID_APP" -- bash -c "cat << 'PHP_EOF' > /var/www/bookstack/themes/custom/functions.php
<?php
use BookStack\\Theming\\ThemeEvents;
use BookStack\\Facades\\Theme;

Theme::listen(ThemeEvents::OIDC_ID_TOKEN_PRE_VALIDATE, function (array \$idTokenData) {
    if (isset(\$idTokenData['aud']) && is_array(\$idTokenData['aud'])) {
        \$idTokenData['aud'] = \$idTokenData['aud'][0];
    }
    return \$idTokenData;
});
PHP_EOF"

    echo "[*] Finalizing Permissions & Cache..."
    pct exec "$CT_ID_APP" -- chown -R www-data:www-data /var/www/bookstack
    pct exec "$CT_ID_APP" -- chmod -R 755 /var/www/bookstack/storage /var/www/bookstack/bootstrap/cache /var/www/bookstack/public/uploads
    pct exec "$CT_ID_APP" -- bash -c "cd /var/www/bookstack && php artisan config:clear"

    set_state 4
fi

# ==========================================================================
if [ "$PHASE" -le 4 ]; then
    echo ""
    echo "=========================================================================="
    echo "[PHASE 4]: NGINX & REVERSE PROXY ROUTING"
    echo "=========================================================================="

    PHP_SOCK=$(pct exec "$CT_ID_APP" -- bash -c "ls /run/php/php*-fpm.sock | head -n1")

    cat << NGINX_EOF > "$SNIPPET_DIR/bookstack.conf"
server {
    listen 80;
    server_name $DOMAIN;
    root /var/www/bookstack/public;
    index index.php index.html;
    location / { try_files \$uri \$uri/ /index.php?\$query_string; }
    location ~ \.php\$ {
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:$PHP_SOCK;
    }
    location ~ /\.ht { deny all; }
}
NGINX_EOF

    pct push "$CT_ID_APP" "$SNIPPET_DIR/bookstack.conf" /etc/nginx/sites-available/bookstack
    pct exec "$CT_ID_APP" -- ln -sf /etc/nginx/sites-available/bookstack /etc/nginx/sites-enabled/
    pct exec "$CT_ID_APP" -- rm -f /etc/nginx/sites-enabled/default
    pct exec "$CT_ID_APP" -- systemctl restart nginx
    pct exec "$CT_ID_APP" -- systemctl enable nginx

    echo "=========================================================================="
    echo "HAProxy Requirements:"
    echo "- Server: 10.0.0.123:80"
    echo "- Headers: X-Forwarded-Proto https, X-Forwarded-Host %[req.hdr(Host)]"
    echo "=========================================================================="

    while true; do
        read -p "Type 'DONE' and press [ENTER] once HAProxy is reloaded: " PROXY_STATUS
        if [[ "${PROXY_STATUS,,}" == "done" ]]; then break; fi
    done
    
    rm -f "$STATE_FILE"
    echo "=========================================================================="
    echo "HEARTBEAT_OK: BookStack + MariaDB Final Build Complete."
    echo "URL:             https://$DOMAIN"
    echo "Admin Fallback:  https://$DOMAIN/login?normal=true"
    echo "Fallback Pass:   $BOOKSTACK_ADMIN_PASS"
    echo "=========================================================================="
fi
