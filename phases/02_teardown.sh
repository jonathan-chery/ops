#!/bin/bash
set -euo pipefail
if pct list 2>/dev/null | awk '{print $1}' | grep -qx "${CT_ID}"; then
    echo "Destroying CT ${CT_ID}..."
    pct stop "$CT_ID" 2>/dev/null || true
    sleep 3
    pct destroy "$CT_ID" --purge 2>/dev/null || pct destroy "$CT_ID"
else
    echo "CT ${CT_ID} does not exist. Nothing to destroy."
fi