#!/bin/bash
# Description: Generates a LiteLLM config.yaml from an opencode.json adapter file.

set -e

# --- 1. Graceful Path Handling ---
# Takes the LiteLLM path as arg 1. Defaults to the standard LXC path if missing.
LITELLM_PATH="/home/litellm/config.yaml"

# Takes the opencode.json path as arg 2. Defaults to the paperclip user's config directory.
OPENCODE_PATH="/root/.config/opencode/opencode.json"

# The upstream Ollama IP (Change this if Ollama is not on 10.0.0.10)
OLLAMA_UPSTREAM="http://10.0.0.10:11434"

echo "=========================================================================="
echo " LiteLLM Configuration Generator"
echo "=========================================================================="
echo "[*] Target LiteLLM file: "
echo "[*] Source OpenCode file: "

if [ ! -f "" ]; then
    echo "[!] ERROR: OpenCode configuration file not found at "
    echo "    Usage: ./sync_litellm.sh [path_to_litellm_config] [path_to_opencode_json]"
    exit 1
fi

# Ensure the target directory exists in case we are writing locally to push later
mkdir -p "."

# --- 2. Embedded Python Parser & Generator ---
# We use python3 to reliably parse JSON and spit out clean YAML without requiring  or 
python3 -c '
import sys, json

opencode_file = sys.argv[1]
litellm_file = sys.argv[2]
upstream_url = sys.argv[3]

try:
    with open(opencode_file, "r") as f:
        data = json.load(f)
except Exception as e:
    print(f"[!] Failed to parse JSON: {e}")
    sys.exit(1)

# Extract the Ollama models dictionary
models = data.get("provider", {}).get("ollama", {}).get("models", {})

if not models:
    print("[!] No models found under provider -> ollama -> models in the JSON file.")
    sys.exit(1)

yaml_lines = ["model_list:"]

for model_name, meta in models.items():
    desc = meta.get("name", "").lower()
    
    # Intelligently assign pricing tiers based on your text descriptions
    if "premium" in desc:
        in_cost, out_cost = "0.000005", "0.000010"
    elif "medium-high" in desc:
        in_cost, out_cost = "0.000003", "0.000006"
    elif "low" in desc:
        in_cost, out_cost = "0.0000005", "0.000001"
    else: # Default/Medium
        in_cost, out_cost = "0.000001", "0.000002"

    yaml_lines.append(f"  - model_name: {model_name}")
    yaml_lines.append(f"    litellm_params:")
    yaml_lines.append(f"      model: ollama/{model_name}")
    yaml_lines.append(f"      api_base: \"{upstream_url}\"")
    yaml_lines.append(f"    model_info:")
    yaml_lines.append(f"      input_cost_per_token: {in_cost}")
    yaml_lines.append(f"      output_cost_per_token: {out_cost}")
    yaml_lines.append("") # Spacer

try:
    with open(litellm_file, "w") as f:
        f.write("\n".join(yaml_lines))
    print(f"[+] Successfully mapped {len(models)} models to YAML.")
except Exception as e:
    print(f"[!] Failed to write YAML: {e}")
    sys.exit(1)
' "" "" ""

echo "=========================================================================="
echo "HEARTBEAT_OK: LiteLLM Sync Complete."
echo "If this was generated directly on the LiteLLM LXC, run:"
echo "  sudo systemctl restart litellm"
echo "=========================================================================="
