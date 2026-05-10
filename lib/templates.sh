# File: lib/templates.sh

# Substitutes variables in a template and securely pushes it to the CT
fw_push_template() {
    local tpl_source="$1"
    local ct_dest="$2"
    local dest_perms="${3:-600}" # Default to restricted permissions

    if [[ ! -f "$tpl_source" ]]; then
        echo "ERROR: Template $tpl_source not found."
        exit 1
    fi

    # Create a secure temporary file on the host
    local tmp_file=$(mktemp)
    chmod 600 "$tmp_file"

    # Use envsubst to replace environment variables in the template
    envsubst < "$tpl_source" > "$tmp_file"

    # Push to container and clean up host
    pct push "$CT_ID" "$tmp_file" "$ct_dest"
    rm -f "$tmp_file"

    # Apply permissions and ownership inside the container
    pct exec "$CT_ID" -- chown "${APP_USER}:${APP_USER}" "$ct_dest"
    pct exec "$CT_ID" -- chmod "$dest_perms" "$ct_dest"
    
    echo "[TEMPLATE] Pushed $tpl_source to $ct_dest"
}