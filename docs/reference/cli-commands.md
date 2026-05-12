# CLI Commands Reference

All commands are exposed through the `ops` executable.

## Global Options

| Option | Description |
|---|---|
| `--help` | Show help and exit |
| `--version` | Show version |

## Application Lifecycle

### `deploy`

Deploy one or more applications based on blueprints.

```bash
ops deploy [APPS...] [OPTIONS]
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--force` / `-f` | flag | False | Redeploy even if already complete |
| `--no-teardown-on-failure` | flag | False | Do not auto-teardown on failure |
| `--parallel` / `--sequential` | flag | True | Run in parallel or sequentially |
| `--cluster` | flag | False | Auto-place across cluster nodes |
| `--cluster-transport` | str | None | Override transport (`ssh`, `https`) |

**Examples:**
```bash
ops deploy simple-lxc
ops deploy -f simple-lxc
ops deploy --cluster myapp
ops deploy app1 app2 app3
```

### `teardown`

Stop, backup, and destroy a deployment.

```bash
ops teardown APP [OPTIONS]
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--skip-backup` | flag | False | Skip pre-teardown backup |

### `start` / `stop` / `restart`

```bash
ops start APP
ops stop APP
ops restart APP
```

### `sync`

Re-render templates and restart services (no rebuild).

```bash
ops sync APP
```

### `status`

Show deployment status.

```bash
ops status [APP]  # Omit APP for all
```

### `logs`

```bash
ops logs APP [-f] [-n LINES]
```

| Option | Type | Default | Description |
|---|---|---|---|
| `-f` / `--follow` | flag | False | Follow log tail |
| `-n` / `--lines` | int | 100 | Number of lines |

### `exec`

Run a command inside the container.

```bash
ops exec APP COMMAND [-r]
```

| Option | Type | Default | Description |
|---|---|---|---|
| `-r` | flag | False | Run as root (default: app user) |

**Example:**
```bash
ops exec simple-lxc "uptime"
ops exec -r simple-lxc "apt-get update"
```

## Configuration

### `config`

```bash
ops config --show      # Display current config
ops config --edit      # Open in $EDITOR
```

### `onboard`

Add a Proxmox host to configuration.

```bash
ops onboard --host HOST [--user USER] [--token-name NAME] [--token-secret SECRET] [--node NODE]
```

## Blueprints

### `blueprint-list`

```bash
ops blueprint-list
```

Shows built-in and user blueprints with schema versions.

### `blueprint-init`

```bash
ops blueprint-init NAME --from BUILTIN
```

Copies a built-in blueprint to `~/.ops/blueprints/` for customization.

## Clustering

### `cluster-join`

```bash
ops cluster-join [--transport ssh|https] [--label LABEL] [--host HOST]
```

### `cluster-leave`

```bash
ops cluster-leave
```

### `cluster-status`

```bash
ops cluster-status
```

## Secret Rotation

### `rotate-secrets`

```bash
ops rotate-secrets APP
```

Regenerates all `type: generated` secrets, updates the container, and restarts.

### `rotate-ssh`

```bash
ops rotate-ssh APP
```

Replaces SSH keypairs and updates authorized_keys.
