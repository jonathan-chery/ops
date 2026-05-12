# Guide: Firecracker MicroVM Workload

Deploy a lightweight microVM using the `pve-microvm` backend.

## Blueprint

```yaml
version: "1.2"
name: mymicrovm
container:
  hostname: micro-01
  cores: 2
  memory: 2048
  disk: 10240
deployment:
  type: firecracker
  firecracker:
    backend: pve-microvm
    image: ubuntu-24.04-microvm
    vcpus: 2
    mem_size_mib: 2048
network:
  bridge: vmbr1
  mode: dhcp
```

## Requirements

- Proxmox node has `pve-microvm-template` installed
- VM template `ubuntu-24.04-microvm` exists:
  ```bash
  pveam list local
  pveam download local ubuntu-24.04-microvm
  ```

## Deploy

```bash
ops deploy mymicrovm
```

Phases skipped for microVMs:
- PROVISION (microVM created via `qm clone`)
- HARDEN (immutable guest, no SSH hardening)
- INSTALL (runtime baked into image)

## Verify

```bash
ops status mymicrovm
```

Shows VMID and IP. To get a console, SSH into the Proxmox host and run:

```bash
qm terminal <vmid>
```

## Teardown

```bash
ops teardown mymicrovm
```

Uses `qm stop` + `qm destroy` (no LXC involved).
