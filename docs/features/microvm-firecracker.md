# MicroVM & Firecracker

Blueprint schema `1.2` introduces `deployment.type == "firecracker"` with two backends.

## Backends

### pve-microvm (default)

Uses `MicroVMProvider` to create QEMU microVMs natively on the Proxmox node via `pve-microvm-template` and `qm clone`. This backend **skips LXC entirely** — the VM is a first-class QEMU guest.

Characteristics:
- Immutable guest image
- Fast boot (~1s)
- No container hardening needed (immutable)
- No Docker runtime install needed
- `/dev/kvm` access via QEMU directly

### lxc (fallback)

Provisions a standard LXC container, injects `/dev/kvm` passthrough via `patch_lxc_config`, then runs the Firecracker binary inside the container via `NestedFirecrackerDeployer`.

Characteristics:
- Firecracker runs inside LXC (nested virtualization)
- Useful when `pve-microvm` is unavailable
- Requires `/dev/kvm` passthrough: `lxc.cgroup2.devices.allow: c 10:232 rwm`

## Blueprint Configuration

```yaml
version: "1.2"
name: myfirecracker
container:
  hostname: fc-app-01
  cores: 2
  memory: 2048
  disk: 10240
deployment:
  type: firecracker
  firecracker:
    backend: pve-microvm          # or "lxc"
    image: ubuntu-24.04-microvm   # pve-microvm template name
    firecracker_version: "1.7.0"  # lxc mode only
    vcpus: 2
    mem_size_mib: 2048
network:
  bridge: vmbr1
  mode: dhcp
```

## Backend Detection

On first deploy, `_phase_preflight()` probes the Proxmox host for `pve-microvm` availability. The chosen backend is cached in `DeploymentState.backend` so redeploys skip the probe.

## Lifecycle Commands

MicroVMs support the same CLI commands as LXC:

```bash
ops deploy myfirecracker
ops status myfirecracker
ops logs myfirecracker
ops restart myfirecracker
ops teardown myfirecracker
```

`sync` is not supported (immutable guest) — a warning is emitted.

## Limitations

- **No shell access** for `pve-microvm` backend (microVM has no SSH by default). Use `qm terminal` on the Proxmox host instead.
- **No template sync** — templates are baked into the VM image at provision time.
- **Backup** uses `qm stop` + `qm destroy` with pre-shutdown snapshot (no filesystem tarball).
