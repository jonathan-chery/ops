#!/bin/bash
# Description: Fetches opencode.json, updates LiteLLM, and deploys raw JSON to Paperclip.
set -euo pipefail

# --- 1. Fleet Configuration ---
CT_ID_LITELLM="124"
CT_ID_PAPERCLIP="150"

WORKSPACE="/var/lib/pve/local/snippets/opencode-sync"
REPO_DIR="$WORKSPACE/repo"
LITELLM_YAML="$WORKSPACE/config.yaml"

echo "=========================================================================="
echo " Fleet Configurator: Git -> Raw OpenCode -> Paperclip"
echo "=========================================================================="

DEFAULT_GITEA="https://git.cloudinit.dev"
DEFAULT_REPO="git@git.cloudinit.dev:${HOSTNAME}/${HOSTNAME}.git"

read -p "Enter Gitea Server URL [$DEFAULT_GITEA]: " INPUT_GITEA
GITEA_URL="${INPUT_GITEA:-$DEFAULT_GITEA}"

read -p "Enter SSH Clone URL [$DEFAULT_REPO]: " INPUT_REPO
REPO_SSH_URL="${INPUT_REPO:-$DEFAULT_REPO}"

# --- 2. Git Pull / Setup ---
mkdir -p "$WORKSPACE"

if [ -d "$REPO_DIR/.git" ]; then
    echo "[*] Local repository found. Pulling latest updates from upstream..."
    cd "$REPO_DIR"
    git reset --hard HEAD >/dev/null
    GIT_SSH_COMMAND="ssh -o StrictHostKeyChecking=accept-new" git pull
    cd - >/dev/null
else
    echo "[*] Repository not found locally. Cloning..."
    GIT_SSH_COMMAND="ssh -o StrictHostKeyChecking=accept-new" git clone "$REPO_SSH_URL" "$REPO_DIR"
fi

SOURCE_JSON=$(find "$REPO_DIR" -name "opencode.json" | head -n 1)
if [ -z "$SOURCE_JSON" ]; then
    echo "[!] ERROR: opencode.json not found anywhere in the repository!"
    exit 1
fi
echo "[*] Discovered config at: $SOURCE_JSON"

# --- 3. Generate LiteLLM YAML (But DO NOT touch the JSON) ---
echo "[*] Generating LiteLLM Config..."
python3 -c '
import sys, json

source_json = sys.argv[1]
yaml_out = sys.argv[2]

try:
    with open(source_json, "r") as f:
        data = json.load(f)
except Exception as e:
    print(f"[!] Failed to parse source JSON: {e}")
    sys.exit(1)

# Look for providers (plural), fallback to provider (singular) just in case
providers_block = data.get("providers", data.get("provider", {}))
target_provider = providers_block.get("ollama", {})
models = target_provider.get("models", {})

# Extract upstream URL dynamically
original_base_url = target_provider.get("options", {}).get("baseURL", "http://10.0.0.10:11434/v1")
ollama_upstream = original_base_url.replace("/v1", "").rstrip("/")

yaml_lines = ["model_list:"]
for model_name, meta in models.items():
    desc = meta.get("name", "").lower()
    
    in_cost, out_cost = "0.000001", "0.000002" # Default fallback
    if "premium" in desc:
        in_cost, out_cost = "0.000005", "0.000010"
    elif "medium-high" in desc:
        in_cost, out_cost = "0.000003", "0.000006"
    elif "low" in desc:
        in_cost, out_cost = "0.0000005", "0.000001"

    yaml_lines.append(f"  - model_name: {model_name}")
    yaml_lines.append(f"    litellm_params:")
    yaml_lines.append(f"      model: ollama/{model_name}")
    yaml_lines.append(f"      api_base: \"{ollama_upstream}\"")
    yaml_lines.append(f"    model_info:")
    yaml_lines.append(f"      input_cost_per_token: {in_cost}")
    yaml_lines.append(f"      output_cost_per_token: {out_cost}")
    yaml_lines.append("")

with open(yaml_out, "w") as f:
    f.write("\n".join(yaml_lines))
' "$SOURCE_JSON" "$LITELLM_YAML"

# --- 4. Fleet Deployment ---
if pct status "$CT_ID_LITELLM" &>/dev/null; then
    echo "[*] Pushing config to LiteLLM (LXC $CT_ID_LITELLM)..."
    pct push "$CT_ID_LITELLM" "$LITELLM_YAML" /home/litellm/config.yaml
    pct exec "$CT_ID_LITELLM" -- chown litellm:litellm /home/litellm/config.yaml
    pct exec "$CT_ID_LITELLM" -- systemctl restart litellm
fi

if pct status "$CT_ID_PAPERCLIP" &>/dev/null; then
    echo "[*] Pushing RAW UNTOUCHED config to Paperclip (LXC $CT_ID_PAPERCLIP)..."
    pct exec "$CT_ID_PAPERCLIP" -- mkdir -p /home/paperclip/.config/opencode
    
    # Push the exact source file directly
    pct push "$CT_ID_PAPERCLIP" "$SOURCE_JSON" /home/paperclip/.config/opencode/opencode.json
    
    pct exec "$CT_ID_PAPERCLIP" -- chown -R 1000:1000 /home/paperclip/.config/opencode
    pct exec "$CT_ID_PAPERCLIP" -- bash -c "cd /opt/paperclip && docker compose restart paperclip"
fi

echo "=========================================================================="
echo "HEARTBEAT_OK: Deployed Raw JSON to Paperclip."
echo "=========================================================================="
