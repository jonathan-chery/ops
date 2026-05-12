# Phased Deployments

Ops uses a fixed 7-phase deployment pipeline. Each phase is idempotent: if it was already completed for an app, it is skipped on re-run.

## Phase Overview

| Phase | What happens | Idempotent check |
|---|---|---|
| **PREFLIGHT** | Validate blueprint, resolve VMID, IP, node, secrets | Blueprint digest match |
| **PROVISION** | Create LXC or microVM | Container exists |
| **HARDEN** | Generate SSH keys, lock down sshd | Keys exist on disk |
| **INSTALL** | Install Docker, runtimes, dependencies | Runtime binary responds |
| **DATABASE** | Create database and user | DB + user exist |
| **DEPLOY** | Push templates, start workload | Service running |
| **FINALIZE** | Health check, heartbeat manifest | Manifest exists |

## State Persistence

Deployment state is persisted at `~/.ops/state/{app_name}.enc` as Fernet-encrypted JSON:

```json
{
  "version": "1.2",
  "vmid": 1201,
  "ip": "10.0.0.201",
  "node": "pve1",
  "backend": "lxc",
  "phase": "finalize",
  "completed_phases": ["preflight", "provision", ..., "finalize"],
  "secrets_resolved": {"DB_PASSWORD": "..."}
}
```

## Re-running a Phase

Use `--force` to re-deploy even if fully complete:

```bash
ops deploy myapp --force
```

Or target a specific phase resume point via the orchestrator API (see `ops.core.orchestrator`).

## Phase Skipping

Some deployment types naturally skip phases:

- **MicroVM** (`pve-microvm` backend): skips PROVISION, HARDEN, INSTALL (OS is immutable guest image)
- **Vanilla** (`none` type): skips INSTALL, DATABASE, DEPLOY
- **No database** (blueprint omits `database`): skips DATABASE

## Failure Behavior

By default, if any phase fails, the orchestrator auto-teardowns the container to prevent a half-configured state:

```bash
ops deploy myapp --no-teardown-on-failure  # Keep it for debugging
```
