#!/bin/bash
# File: ops
set -euo pipefail

ACTION=${1:-}
APP_NAME=${2:-}

if [[ -z "$ACTION" || -z "$APP_NAME" ]]; then
    echo "Usage: ./ops <deploy|teardown> <app_name>"
    exit 1
fi

BOOTSTRAP_FILE="apps/${APP_NAME}/bootstrap.sh"
if [[ ! -f "$BOOTSTRAP_FILE" ]]; then
    echo "Error: Bootstrap not found at $BOOTSTRAP_FILE"
    exit 1
fi

# 1. Load shared standard libraries
for lib in lib/*.sh; do source "$lib"; done

# 2. Load the App Bootstrap (Vars + Hooks)
source "$BOOTSTRAP_FILE"

# 3. Lifecycle Orchestrator
execute_lifecycle() {
    echo "=== Starting Compliant Deployment for $APP_NAME ==="
    
    # Standard Infrastructure Phases
    fw_lxc_provision      # Creates the unprivileged CT (lib/lxc.sh)
    fw_security_harden    # Secures SSH, creates standard users (lib/security.sh)

    # App-Specific Hooks (Executed if defined in bootstrap.sh)
    if type hook_install_deps &>/dev/null; then 
        echo "--> Running hook_install_deps..." && hook_install_deps
    fi
    
    if type hook_fetch &>/dev/null; then 
        echo "--> Running hook_fetch..." && hook_fetch
    fi
    
    if type hook_build &>/dev/null; then 
        echo "--> Running hook_build..." && hook_build
    fi
    
    if type hook_configure &>/dev/null; then 
        echo "--> Running hook_configure..." && hook_configure
    fi
    
    if type hook_service &>/dev/null; then 
        echo "--> Running hook_service..." && hook_service
    fi

    # Standard Audit Phase
    fw_security_audit     # Checks open ports, running services (lib/security.sh)
    echo "=== Deployment Complete ==="
}

case "$ACTION" in
    deploy) execute_lifecycle ;;
    teardown) fw_lxc_teardown ;; # Standard destruction
    *) echo "Unknown action"; exit 1 ;;
esac