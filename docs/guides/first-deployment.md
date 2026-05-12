# Guide: First Deployment

This guide walks through deploying the built-in `simple-lxc` blueprint from scratch.

## Prerequisites

- Proxmox VE 8+ node with network bridge `vmbr1`
- API token with `VM.Allocate`, `VM.Config.Network`, `VM.Config.Disk`, `Datastore.AllocateSpace`
- `ops` installed (see [Installation](../installation.md))

## Step 1: Onboard Proxmox Host

```bash
ops onboard \
  --host pve.example.com \
  --user root@pam \
  --token-name ops-token \
  --token-secret abcdef01-2345-6789-abcd-ef0123456789
```

This creates `~/.ops/config.yaml` with encrypted credentials. The master key is stored in your OS keyring.

## Step 2: Verify Configuration

```bash
ops config --show
```

Check:
- `proxmox.host` resolves
- `network.subnet` is a valid CIDR
- `storage.pool` exists on the Proxmox node

## Step 3: Understand the Blueprint

```bash
ops blueprint-list
# simple-lxc — Bare Ubuntu 24.04 container
```

The `simple-lxc` blueprint is:

```yaml
version: "1.2"
name: simple-lxc
container:
  hostname: ubuntu-test
  cores: 1
  memory: 512
  disk: 8192
  template: ubuntu-24.04-standard_24.04-1_amd64.tar.zst
network:
  bridge: vmbr1
  mode: dhcp
deployment:
  type: none
```

It deploys a vanilla Ubuntu container with no application.

## Step 4: Deploy

```bash
ops deploy simple-lxc
```

You will see phase progress:

```
--> [PREFLIGHT] Validating blueprint...
    [OK] VMID=1201, IP=10.0.0.201
--> [PROVISION] Creating LXC container...
    [OK] Container 1201 running at 10.0.0.201
--> [HARDEN] Securing container...
    [OK] SSH keys generated
--> [INSTALL] Installing dependencies...
    [INFO] No runtime to install (type=none)
--> [DATABASE] Skipping (no database config)
--> [DEPLOY] Skipping (type=none)
--> [FINALIZE] Running health checks...
    [INFO] Health check skipped (not enabled)
    [OK] Deployment finalized
```

## Step 5: Verify

```bash
ops status simple-lxc
# VMID: 1201
# IP: 10.0.0.201
# Phase: finalize
# Status: running

ops exec simple-lxc "cat /etc/os-release | grep PRETTY"
# PRETTY_NAME="Ubuntu 24.04 LTS"
```

## Step 6: Teardown (Optional)

```bash
ops teardown simple-lxc
```

This stops the container, creates a backup tarball at `~/.ops/backups/`, and destroys the LXC.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `No Proxmox hosts configured` | Config missing | Run `ops onboard` |
| `Template not found` | Template not downloaded | `pveam download local ubuntu-24.04-standard_24.04-1_amd64.tar.zst` |
| `Permission denied` | API token lacks roles | Add `VM.Allocate`, `VM.Config.*`, `Datastore.AllocateSpace` |
| `IP allocation failed` | Subnet exhausted | Increase subnet size or manually specify IP |
