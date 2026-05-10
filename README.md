# Ops CLI

A robust, phased, idempotent CLI for deploying and managing Proxmox LXC containers.

## Features

- **Phased Deployments**: Idempotent PREFLIGHT → PROVISION → HARDEN → INSTALL → DATABASE → DEPLOY → FINALIZE with state persistence
- **Docker & Native**: Docker Compose as primary deployment strategy, native systemd as fallback
- **Auto-allocation**: VMID and IP auto-discovered from Proxmox API (IP last octet = VMID)
- **Secret Management**: Local encrypted secrets + optional Infisical integration, all at rest via `cryptography` + OS keyring
- **SSH Hardening**: Auto-generated per-container SSH key pairs (root + app user)
- **Database Provisioning**: PostgreSQL database/user creation for apps
- **Health Checks**: HTTP endpoint polling with heartbeat manifest generation
- **Backup Before Teardown**: Automatic tarball backup before container destruction
- **Blueprint Versioning**: Schema version enforcement with auto-migration warnings
- **Parallel Deployments**: Deploy multiple apps concurrently

## Installation

```bash
# Using pipx
pip install pipx
pipx install .

# Or in a virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configuration

On first run, a config file is auto-generated at `~/.ops/config.yaml`:

```bash
ops config --show
ops config --edit
```

### Config Parameters

```yaml
proxmox:
  host: pve.local
  user: root
  token_name: ops-token
  token_value: ENC[...]  # Auto-encrypted at rest
  verify_ssl: false

network:
  bridge: vmbr1
  gateway: 10.0.0.254
  subnet: 10.0.0.0/24
  dns: [1.1.1.1, 8.8.8.8]

storage:
  pool: local
  disk_size: 20

database:
  host: 10.0.0.102
  port: 5432
  admin_user: proxmox_admin
  admin_password: ENC[...]

defaults:
  auto_teardown_on_failure: true
```

## Usage

### Deploy an application
```bash
ops deploy simple-lxc
ops deploy postgres
ops deploy --force simple-lxc        # Redeploy even if already deployed
ops deploy --no-teardown-on-failure simple-lxc
```

### Lifecycle management
```bash
ops start simple-lxc
ops stop simple-lxc
ops restart simple-lxc
ops exec simple-lxc "uptime"
ops exec -r simple-lxc "apt-get update"    # Run as root
```

### Logs & status
```bash
ops status simple-lxc
ops status                          # All containers
ops logs simple-lxc
ops logs -f simple-lxc             # Follow logs
ops list
```

### Sync templates without rebuild
```bash
ops sync simple-lxc
```

### Teardown
```bash
ops teardown simple-lxc
ops teardown --skip-backup simple-lxc
```

### Blueprints
```bash
ops blueprint-list
ops blueprint-init myapp --from simple-lxc
```

## Blueprints

Built-in blueprints are read-only in `src/ops/blueprints/`:
- `simple-lxc` — Bare Ubuntu 24.04 container
- `postgres` — PostgreSQL 16 server via Docker
- `cockroachdb` — CockroachDB single-node cluster
- `haproxy` — HAProxy load balancer
- `lxc-docker` — Ubuntu + Docker CE (no app)
- `lxc-podman` — Ubuntu + Podman (no app)

User blueprints live in `~/.ops/blueprints/` and override built-ins.

## Secret Management

Secrets are encrypted at rest using `cryptography.Fernet` with a master key stored in your OS keyring (or fallback to `~/.ops/.master_key`).

### Secret Types
- `generated` — Auto-generated crypto secret
- `prompt` — Interactive prompt (hidden input)
- `file` — Read from local file
- `infisical` — Fetch from Infisical (optional)

Example in blueprint:
```yaml
secrets:
  - name: DATABASE_PASSWORD
    type: generated
    length: 48
  - name: API_KEY
    type: infisical
    path: /production/api-keys
    key: openai_api_key
    required: true
```

## Project Structure

```
ops/
├── pyproject.toml
├── src/ops/
│   ├── cli.py
│   ├── blueprints/          # Static built-in blueprints
│   ├── commands/            # CLI command implementations
│   ├── core/                # Orchestration engine
│   │   ├── config.py        # Config loader (encrypted)
│   │   ├── orchestrator.py  # Phased deploy/teardown
│   │   ├── state.py         # Deployment state persistence
│   │   ├── heartbeat.py     # Health checks & manifests
│   │   └── blueprint.py     # Blueprint manager
│   ├── deployers/           # Docker & Native strategies
│   ├── models/              # Pydantic data models
│   ├── providers/           # Proxmox, Database, Infisical
│   └── utils/               # Network, Secrets, SSH, Templates
```
