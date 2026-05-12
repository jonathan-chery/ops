# Configuration Reference

Ops configuration is stored in `~/.ops/config.yaml` with encrypted fields.

## Config File Location

| Path | Purpose |
|---|---|
| `~/.ops/config.yaml` | Main configuration file |
| `~/.ops/.master_key` | Fallback master key (file) |
| `~/.ops/secrets/` | Per-deployment secrets directory |
| `~/.ops/state/` | Per-deployment state files (encrypted) |
| `~/.ops/audit.log` | Append-only audit log |
| `~/.ops/blueprints/` | User blueprints (override built-ins) |
| `~/.ops/backups/` | Pre-teardown backup tarballs |

## Top-Level Fields

### `proxmox`

```yaml
proxmox:
  host: pve.local
  user: root@pam
  token_name: ops-token
  token_value: ENC[...]
  verify_ssl: false
  node: pve1
```

| Field | Type | Required | Description |
|---|---|---|---|
| `host` | `str` | Yes | Proxmox host (IP or hostname) |
| `user` | `str` | Yes | API user (e.g., `root@pam`) |
| `token_name` | `str` | Yes | API token name |
| `token_value` | `str` | Yes | API token secret (auto-encrypted) |
| `verify_ssl` | `bool` | No | Verify TLS (default: `false`) |
| `node` | `str` | No | Default node name |

### `network`

```yaml
network:
  bridge: vmbr1
  gateway: 10.0.0.254
  subnet: 10.0.0.0/24
  dns:
    - 1.1.1.1
    - 8.8.8.8
```

| Field | Type | Required | Description |
|---|---|---|---|
| `bridge` | `str` | Yes | Network bridge |
| `gateway` | `str` | Yes | Default gateway IP |
| `subnet` | `str` | Yes | CIDR subnet |
| `dns` | `list[str]` | No | DNS servers |

### `storage`

```yaml
storage:
  pool: local
  disk_size: 20
```

| Field | Type | Required | Description |
|---|---|---|---|
| `pool` | `str` | Yes | Storage pool name |
| `disk_size` | `int` | No | Default disk size in GB |

### `database`

```yaml
database:
  host: 10.0.0.102
  port: 5432
  admin_user: proxmox_admin
  admin_password: ENC[...]
```

| Field | Type | Required | Description |
|---|---|---|---|
| `host` | `str` | No | PostgreSQL host |
| `port` | `int` | No | Port (default: `5432`) |
| `admin_user` | `str` | No | Admin user for DB provisioning |
| `admin_password` | `str` | No | Admin password (auto-encrypted) |

### `infisical`

```yaml
infisical:
  client_id: ENC[...]
  client_secret: ENC[...]
  url: https://app.infisical.com
```

| Field | Type | Required | Description |
|---|---|---|---|
| `client_id` | `str` | No | Infisical client ID (auto-encrypted) |
| `client_secret` | `str` | No | Infisical client secret (auto-encrypted) |
| `url` | `str` | No | Infisical API URL |

### `defaults`

```yaml
defaults:
  auto_teardown_on_failure: true
  template: ubuntu-24.04-standard_24.04-1_amd64.tar.zst
```

| Field | Type | Required | Description |
|---|---|---|---|
| `auto_teardown_on_failure` | `bool` | No | Auto-teardown on failure (default: `true`) |
| `template` | `str` | No | Default LXC template |

## Encryption

Sensitive fields marked with `ENC[...]` are encrypted at rest using:
- **Algorithm:** Fernet (AES-128-CBC + HMAC-SHA256)
- **KDF:** PBKDF2HMAC, 100,000 iterations, SHA256
- **Master key:** OS keyring (fallback: `~/.ops/.master_key`)

The `ConfigManager` handles encryption/decryption transparently. Users never see raw secrets in `config.yaml`.

## CLI Config Commands

```bash
ops config --show      # Decrypt and display
ops config --edit      # Opens $EDITOR on decrypted config
ops onboard            # Interactive prompt for host setup
```
