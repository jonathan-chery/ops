# File: lib/secrets.sh

# Ensure the app-specific secret directory exists with strict permissions
fw_init_secrets() {
    export APP_SECRETS_DIR=".ops/secrets/${APP_NAME}"
    mkdir -p "$APP_SECRETS_DIR"
    
    # Enforce strict host-side permissions
    chmod 700 .ops .ops/secrets "$APP_SECRETS_DIR" 2>/dev/null || true
}

# Auto-generates a cryptographic secret if it doesn't exist
fw_ensure_generated_secret() {
    local secret_name="$1"
    local length="${2:-32}"
    local secret_file="${APP_SECRETS_DIR}/${secret_name}.secret"

    if [[ ! -s "$secret_file" ]]; then
        echo "[SECRETS] Generating new secret: ${secret_name}" >&2
        openssl rand -base64 "$length" | tr -d '=/+' > "$secret_file"
        chmod 600 "$secret_file"
    fi
    
    cat "$secret_file"
}

# Fetches a manually provided secret (e.g., API keys). 
# Fails the deployment if the key is missing.
fw_require_secret() {
    local secret_name="$1"
    local secret_file="${APP_SECRETS_DIR}/${secret_name}.key"

    if [[ ! -s "$secret_file" ]]; then
        echo "============================================================" >&2
        echo "ERROR: Missing required secret '${secret_name}' for ${APP_NAME}." >&2
        echo "Please create it by running:" >&2
        echo "  echo 'your-api-key' > ${secret_file}" >&2
        echo "============================================================" >&2
        exit 1
    fi
    
    cat "$secret_file"
}

# Optional secret: Returns the value if it exists, otherwise empty.
fw_get_optional_secret() {
    local secret_name="$1"
    local secret_file="${APP_SECRETS_DIR}/${secret_name}.key"

    if [[ -s "$secret_file" ]]; then
        cat "$secret_file"
    fi
}