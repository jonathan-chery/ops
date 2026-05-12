# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0]

### Added
- Initial CLI scaffolding (`ops` package, providers, deployers, utils)
- Proxmox REST API integration via `proxmoxer`
- LXC lifecycle: create, start, stop, restart, destroy
- SSH keypair generation and hardening (`SSHKeyManager`)
- Template rendering with Jinja2 sandboxing
- Local Fernet-based secret storage
- `deploy`, `teardown`, `status`, `logs`, `exec`, `sync` CLI commands
- Docker & Podman deployers with `docker compose` support
- Native deployer with systemd service generation
- WebAssembly deployer (`wasmtime` runtime)
- Cluster auto-discovery via UDP beacons
- Node registry with label constraints
- Pluggable cluster transport (SSH/HTTPS)
- Blueprint schema v1.2 with `pve-microvm` / `lxc` backends
- MicroVMProvider (SSH wrapper for pve-microvm-template, qm clone)
- MicroVMDeployer (immutable QEMU microVM lifecycle)
- NestedFirecrackerDeployer (Firecracker binary inside LXC)
- Backend probing in `_phase_preflight()` with `DeploymentState.backend` caching
- CLI `start`/`stop`/`restart`/`teardown` routing for `pve-microvm` backend
