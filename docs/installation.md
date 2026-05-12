# Installation

## Option 1: One-line Installer (Recommended)

Install the latest release binary for Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/jonathan-chery/ops/main/install.sh | sh
```

### Installer Options

| Flag | Default | Description |
|---|---|---|
| `--version TAG` | `latest` | Pin to a specific release |
| `--prefix DIR` | `/usr/local/bin` | Install directory |
| `--os OS` | auto-detect | Override OS |
| `--arch ARCH` | auto-detect | Override architecture |
| `--verify` | on | SHA256 checksum verification |
| `--no-verify` | off | Skip checksum verification |
| `--no-sudo` | off | Fail if sudo is needed instead of prompting |
| `--dry-run` | off | Print actions, do not execute |

### Examples

```bash
# Install specific version to user-local bin
curl -fsSL https://raw.githubusercontent.com/jonathan-chery/ops/main/install.sh | sh -s -- --version v1.2.0 --prefix ~/.local/bin

# Skip checksum verification
curl -fsSL ... | sh -s -- --no-verify
```

### Supported Platforms

| OS | Architecture | Status |
|---|---|---|
| Linux | amd64 | Available |
| Linux | arm64 | Available |
| macOS | amd64 | Coming soon |
| Windows | amd64 | Coming soon |

## Option 2: pip/pipx

If you already have Python 3.12+:

```bash
# Using pipx (recommended for isolated install)
pip install pipx
pipx install git+https://github.com/jonathan-chery/ops.git

# Or in a virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install git+https://github.com/jonathan-chery/ops.git
```

## Option 3: Build from Source

```bash
git clone https://github.com/jonathan-chery/ops.git
cd ops
pip install -e ".[dev]"
```

## Verify Installation

```bash
ops --version
ops --help
```
