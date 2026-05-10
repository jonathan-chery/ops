#!/bin/bash
set -euo pipefail
mkdir -p "$SNIPPET_DIR"
pveam update
TEMPLATE=$(pveam available 2>/dev/null | grep -i 'ubuntu-24.04' | grep 'standard' | awk '{print $NF}' | sort -V | tail -1)

if [[ -z "$TEMPLATE" ]]; then echo "ERROR: Ubuntu 24.04 template not found."; exit 1; fi

if ! pveam list local 2>/dev/null | grep -q "$TEMPLATE"; then
    echo "Downloading template: $TEMPLATE"
    pveam download local "$TEMPLATE"
fi