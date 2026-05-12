# Getting Started

This guide walks you through your first deployment: onboarding a Proxmox host and deploying a simple LXC container.

## Prerequisites

- A Proxmox VE 8+ node reachable via HTTPS
- API token name + secret (or root credentials)
- One network bridge (`vmbr0`, `vmbr1`, etc.)
- `ops` installed:
  ```bash
  curl -fsSL https://raw.githubusercontent.com/jonathan-chery/ops/main/install.sh | sh
  ```

## Step 1: Onboard Your Host

```bash
ops onboard --host pve.example.com --user root --token-name ops-token --token-secret abcdef...
```

This generates `~/.ops/config.yaml` with encrypted credentials.

## Step 2: Check Configuration

```bash
ops config --show
```

Verify `proxmox.host`, `network.subnet`, and `storage.pool` are correct.

## Step 3: Deploy Your First App

```bash
ops deploy simple-lxc
```

Ops will run through all phases automatically:

=== "PREFLIGHT"
    Validates the blueprint, resolves VMID, node, and IP

=== "PROVISION"
    Creates the LXC container with the chosen template

=== "HARDEN"
    Generates SSH keys, locks down sshd

=== "INSTALL"
    Installs Docker (if blueprint specifies)

=== "DEPLOY"
    Copies templates and starts the workload

=== "FINALIZE"
    Runs health checks and generates the heartbeat manifest

## Step 4: Verify

```bash
ops status simple-lxc
ops logs simple-lxc
ops exec simple-lxc "uptime"
```

## Next Steps

- Explore [built-in blueprints](blueprints-gallery.md)
- Write your own blueprint with `ops blueprint-init myapp --from simple-lxc`
- Read the [First Deployment](guides/first-deployment.md) guide for a deep dive
