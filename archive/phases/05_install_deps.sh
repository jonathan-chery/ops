#!/bin/bash
set -euo pipefail

pct exec "$CT_ID" -- bash -c 'export DEBIAN_FRONTEND=noninteractive; apt-get update -y && apt-get install -y curl wget git build-essential python3 ca-certificates gnupg'

# Install Node.js
pct exec "$CT_ID" -- bash -c "curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR}.x | bash -"
pct exec "$CT_ID" -- bash -c 'export DEBIAN_FRONTEND=noninteractive; apt-get install -y nodejs'

# Enable pnpm
pct exec "$CT_ID" -- corepack enable
pct exec "$CT_ID" -- corepack prepare pnpm@latest --activate