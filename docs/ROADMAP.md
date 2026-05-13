# ops — Proxmox LXC Orchestrator CLI: Roadmap

## Overview
`ops` is a Python CLI toolchain for orchestrating Linux Containers (LXC), microVMs, and WebAssembly workloads on Proxmox VE. It supports multiple deployment strategies, cluster auto-discovery, and external secrets integration.

---

## Architecture Status

| Layer | Component | Status |
|-------|-----------|--------|
| **Models** | Pydantic schemas (blueprint v1.2, config, state, cluster, container) | ✅ Complete |
| **Core** | ConfigManager, StateManager, AuditLogger, HeartbeatManager, BlueprintManager, Orchestrator | ✅ Complete |
| **Providers** | ProxmoxProvider (REST API) | ✅ Complete |
| | DatabaseProvider (PostgreSQL) | ✅ Complete |
| | InfisicalProvider (secrets) | ✅ Complete |
| | FirecrackerProvider (Unix socket) | ✅ Complete |
| | **MicroVMProvider (SSH → pve-microvm)** | ✅ Complete (v1.2) |
| **Deployers** | DockerDeployer, NativeDeployer, WasmDeployer | ✅ Complete |
| | FirecrackerDeployer (host-local) | ✅ Complete |
| | **MicroVMDeployer (pve-microvm)** | ✅ Complete (v1.2) |
| | **NestedFirecrackerDeployer (LXC + /dev/kvm passthrough)** | ✅ Complete (v1.2) |
| **CLI** | deploy, teardown, status, logs, exec, start, stop, restart, sync | ✅ Complete |
| | build (WASM), cluster-join, cluster-leave, cluster-status | ✅ Complete |
| | **microVM-aware start/stop/restart/teardown** | ✅ Complete (v1.2) |
| **Cluster** | NodeRegistry, DiscoveryService, OpsNode model | ✅ Complete |
| | **HA / migration for microVMs** | 🔜 Future |
| **Secrets** | Local Fernet encryption, SSH key gen, Infisical integration | ✅ Complete |
| **Utilities** | TemplateEngine, safe_shell, IPAllocator, SSHKeyManager | ✅ Complete |
| | RootfsBuilder, FirecrackerNetworkManager, WasmBuildToolchain | ✅ Complete |

---

## Completed Milestones

### v0.1 — Foundation
- [x] Core project scaffolding (`ops` package, providers, deployers, utils)
- [x] Proxmox REST API integration (`proxmoxer`)
- [x] LXC lifecycle: create, start, stop, restart, destroy
- [x] SSH keypair generation and hardening (`SSHKeyManager`)
- [x] Template rendering with Jinja2 sandboxing
- [x] Local Fernet-based secret storage
- [x] `deploy`, `teardown`, `status`, `logs`, `exec`, `sync` CLI commands

### v0.2 — Extended Runtimes
- [x] Docker & Podman deployers with `docker compose` support
- [x] Native deployer with systemd service generation
- [x] WebAssembly deployer (`wasmtime` runtime)
- [x] `build` CLI command for WASM artifacts
- [x] Blueprint schema v1.1 (introduced `firecracker` and `wasm` deployment types)

### v0.3 — Clustering & Discovery
- [x] Cluster auto-discovery via UDP beacons
- [x] Node registry with label constraints
- [x] Pluggable cluster transport (SSH/HTTPS)
- [x] `cluster-join`, `cluster-leave`, `cluster-status` CLI commands

### v1.2 — MicroVM & Firecracker Dual Backend (Current)
- [x] Blueprint schema v1.2 with `backend: pve-microvm | lxc`
- [x] `MicroVMProvider` (SSH wrapper for `pve-microvm-template`, `qm clone`)
- [x] `MicroVMDeployer` (immutable QEMU microVM lifecycle)
- [x] `NestedFirecrackerDeployer` (Firecracker binary inside LXC)
- [x] LXC raw config passthrough (`patch_lxc_config`) for `/dev/kvm`
- [x] Backend probing in `_phase_preflight()` with `DeploymentState.backend` caching
- [x] CLI `start`/`stop`/`restart`/`teardown` routing for `pve-microvm` backend
- [x] Built-in blueprints bumped to schema v1.2
- [x] Version validator accepts both `1.1` and `1.2` for backward compat

---

## Future Plans

## v1.3 — Observability & Day-2 Operations (Current)
- [x] Persistent console/serial log shipping for microVMs (`ops logs` now streams and persists to `~/.ops/logs/`)
- [x] Metrics exporter sidecar (Prometheus `node_exporter` inside LXC/microVM — enabled by default, opt-out via `metrics.enabled: false`)
- [x] Alerting integration (generic HTTP webhook on health-check failure with per-app cooldown)
- [x] `ops events` command to tail `audit.log`
- [x] `ops watch <app>` continuous monitoring with `--exit-on-failure`
- [x] `ops metrics <app>` to fetch Prometheus exposition
- [x] `ops alerts-test` to verify webhook configuration

### v1.4 — Cluster GA
- [ ] Multi-node placement strategy (bin-packing, anti-affinity labels)
- [ ] Cluster-wide state reconciliation (detect drift, auto-heal)
- [ ] Rolling deploys across cluster nodes
- [ ] HA relocate for `pve-microvm` deployments

### v1.5 — Security & Compliance
- [ ] Signed blueprint validation (Cosign / Sigstore)
- [ ] Network policy enforcement (nftables generation from blueprint)
- [ ] Secret rotation scheduling (cron-based `secrets-rotate --auto`)
- [ ] FIPS 140-2 compliant cryptography mode

### v2.0 — Platform Extensibility
- [ ] Plugin system for custom deployers/providers
- [ ] REST API server mode (remote orchestrator control)
- [ ] Web dashboard (read-only Proxmox view + ops-managed workloads)
- [ ] Terraform provider for declarative `ops` resource management

---

## Schema Version History

| Version | Date | Changes |
|---------|------|---------|
| `1.0` | Initial | Base container, docker, native deployments |
| `1.1` | v0.2 | Added `firecracker`, `wasm` deployment types |
| `1.2` | Current | Added `backend`, `image`, `firecracker_version` to `FirecrackerDeploymentConfig` |

---

## How to Contribute
1. Branch from `main` with `feature/<description>` or `fix/<description>` prefixes.
2. Run `ruff check src/` and `mypy src/ops` before opening an MR.
3. Update `AGENTS.md` and this `ROADMAP.md` if architecture or plans change.
4. Follow the conventional commit style defined in `AGENTS.md`.
