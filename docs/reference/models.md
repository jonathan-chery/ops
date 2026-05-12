# API Models Reference

This section documents the primary Pydantic models used throughout the codebase.

## `AppBlueprint`

Root model validated on every blueprint load.

| Field | Type | Required |
|---|---|---|
| `version` | `str` | Yes |
| `name` | `str` | Yes |
| `container` | `ContainerConfig` | Yes |
| `network` | `NetworkConfig` | Yes |
| `deployment` | `DeploymentConfig` | Yes |
| `templates` | `list[TemplateConfig]` | No |
| `secrets` | `list[SecretConfig]` | No |
| `environment` | `dict[str, str]` | No |
| `dependencies` | `dict[str, bool]` | No |
| `health_check` | `HealthCheckConfig` | No |

## `ContainerConfig`

| Field | Type | Default | Description |
|---|---|---|---|
| `hostname` | `str` | `app-{random}` | Container hostname |
| `cores` | `int` | 1 | vCPU cores |
| `memory` | `int` | 512 | RAM in MB |
| `disk` | `int` | 8192 | Disk in MB |
| `template` | `str` | from `defaults.template` | LXC template volid |
| `node_constraints` | `list[str]` | `[]` | Cluster node labels |

## `NetworkConfig`

| Field | Type | Default | Description |
|---|---|---|---|
| `bridge` | `str` | from config | Network bridge |
| `mode` | `str` | `dhcp` | `dhcp` or `static` |
| `ip` | `str` | auto-allocated | Static IP (if mode=static) |

## `DeploymentConfig`

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | `str` | Yes | `docker`, `native`, `firecracker`, `wasm`, `none` |
| `docker` | `DockerDeploymentConfig` | No | If `type=docker` |
| `native` | `NativeDeploymentConfig` | No | If `type=native` |
| `firecracker` | `FirecrackerDeploymentConfig` | No | If `type=firecracker` |
| `wasm` | `WasmDeploymentConfig` | No | If `type=wasm` |

### `DockerDeploymentConfig`

| Field | Type | Required |
|---|---|---|
| `compose_file` | `str` | Yes |
| `env_file` | `str` | No |

### `NativeDeploymentConfig`

| Field | Type | Required |
|---|---|---|
| `app_user` | `str` | Yes |
| `app_dir` | `str` | Yes |
| `service_command` | `str` | Yes |
| `service_env_file` | `str` | No |

### `FirecrackerDeploymentConfig`

| Field | Type | Default | Description |
|---|---|---|---|
| `backend` | `str` | `pve-microvm` | `pve-microvm` or `lxc` |
| `image` | `str` | None | Template image name |
| `firecracker_version` | `str` | `"latest"` | Firecracker binary version (lxc only) |
| `vcpus` | `int` | from `container.cores` | VM vCPUs |
| `mem_size_mib` | `int` | from `container.memory` | VM RAM in MB |

## `DeploymentState`

Persistent encrypted state per application.

| Field | Type | Description |
|---|---|---|
| `version` | `str` | Blueprint version |
| `vmid` | `int | None` | Proxmox VMID |
| `ip` | `str | None` | Allocated IP |
| `node` | `str | None` | Target node name |
| `backend` | `str | None` | `pve-microvm` or `lxc` |
| `phase` | `str` | Current phase |
| `completed_phases` | `list[str]` | All completed phases |
| `secrets_resolved` | `dict[str, str]` | Resolved secret values |
| `blueprint_digest` | `str` | SHA256 of blueprint YAML |
