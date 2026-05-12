# Ops CLI

A robust, phased, idempotent CLI for deploying and managing Proxmox LXC containers, microVMs, and WebAssembly workloads.

## What is Ops?

Ops is a Python-based command-line tool that automates the entire lifecycle of workloads on Proxmox VE — from provisioning and hardening to deployment and observability. It treats infrastructure as code through **blueprints**: declarative YAML files that describe everything your application needs.

## Key Features

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } __Phased Deployments__

    ---

    Idempotent `PREFLIGHT` → `PROVISION` → `HARDEN` → `INSTALL` → `DATABASE` → `DEPLOY` → `FINALIZE` with automatic state persistence.

-   :material-file-document-check:{ .lg .middle } __Declarative Blueprints__

    ---

    Versioned YAML blueprints describe containers, networks, secrets, templates, and deployment strategies.

-   :material-shield-check:{ .lg .middle } __Security by Default__

    ---

    Encrypted secrets at rest, per-container SSH key pairs, hardened sshd configs, and optional Infisical integration.

-   :material-database:{ .lg .middle } __Database Provisioning__

    ---

    Automatically creates PostgreSQL databases and users for your applications.

-   :material-monitor-eye:{ .lg .middle } __Health Checks__

    ---

    HTTP endpoint polling with automatic heartbeat manifest generation.

-   :material-server:{ .lg .middle } __Multiple Backends__

    ---

    Standard LXC, Docker Compose, native systemd, Firecracker microVMs, and WebAssembly — all from one CLI.

</div>

## Quick Install

```bash
curl -fsSL https://raw.githubusercontent.com/jonathan-chery/ops/main/install.sh | sh
```

## Quick Start

```bash
# Show current configuration
ops config --show

# Deploy your first container
ops deploy simple-lxc

# Check status
ops status simple-lxc
```

## Architecture Overview

Ops is built from layered, composable components:

| Layer | Components |
|---|---|
| **Models** | Pydantic schemas (`config`, `blueprint`, `state`, `network`, `cluster`) |
| **Core** | Orchestrator (phased engine), ConfigManager, StateManager, AuditLogger, HeartbeatManager |
| **Providers** | Proxmox (REST API), Database (PostgreSQL), Infisical (secrets), MicroVM (SSH/QEMU) |
| **Deployers** | DockerCompose, NativeSystemd, Wasmtime, MicroVM, NestedFirecracker |
| **Utilities** | SSHKeyManager, IPAllocator, SecretManager (Fernet), TemplateEngine (Jinja2 sandboxed) |

See [Architecture](architecture.md) for a detailed breakdown.

## Deployment Types

| Type | Description | Use Case |
|---|---|---|
| `docker` | Docker Compose inside LXC | Full-stack web apps |
| `native` | Systemd service managed by `ops` | Traditional daemon workloads |
| `firecracker` | MicroVM (pve-microvm or nested LXC) | Immutable, fast boot VMs |
| `wasm` | Wasmtime runtime | Edge functions, sandboxed code |
| `none` | Vanilla LXC, no app deployment | Infra-only containers |

## License

Distributed under the MIT License. See the upstream repository for full details.
