# Blueprints

Blueprints are declarative YAML files that describe an entire application stack — from the LXC container spec to deployment type, secrets, and templates.

## Schema Version

Current version: `1.2`

Blueprints must declare their schema version. Ops validates backwards compatibility:

| Blueprint version | Supported by Ops |
|---|---|
| `1.1` | Yes (firecracker + wasm added) |
| `1.2` | Yes (microVM backend added) |

## Anatomy of a Blueprint

```yaml
version: "1.2"
name: postgres
container:
  hostname: postgres-01
  cores: 2
  memory: 4096
  disk: 20480
  template: ubuntu-24.04-standard_24.04-1_amd64.tar.zst
network:
  bridge: vmbr1
  mode: dhcp
deployment:
  type: docker
  docker:
    compose_file: postgres-compose.yml
    env_file: postgres.env
templates:
  - source: postgres-compose.yml.tpl
    dest: /opt/postgres/postgres-compose.yml
    mode: "0644"
  - source: postgres.env.tpl
    dest: /opt/postgres/postgres.env
    mode: "0600"
secrets:
  - name: POSTGRES_PASSWORD
    type: generated
    length: 48
  - name: POSTGRES_USER
    type: prompt
environment:
  POSTGRES_DB: myapp
dependencies:
  install_docker: true
health_check:
  enabled: true
  port: 5432
  path: /
  interval: 30
```

## Top-Level Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `version` | `str` | Yes | Schema version (`"1.2"`) |
| `name` | `str` | Yes | Application name (must be unique) |
| `container` | `ContainerConfig` | Yes | LXC container specs |
| `network` | `NetworkConfig` | Yes | Network config (can be empty) |
| `deployment` | `DeploymentConfig` | Yes | Deployment type + type-specific config |
| `templates` | `list[TemplateConfig]` | No | Files to render and push into container |
| `secrets` | `list[SecretConfig]` | No | Secrets to resolve |
| `environment` | `dict[str, str]` | No | Static env vars |
| `dependencies` | `dict[str, bool]` | No | Runtime dependencies to install |
| `health_check` | `HealthCheckConfig` | No | HTTP/TCP health check spec |

## Built-In Blueprints

See [Blueprints Gallery](../blueprints-gallery.md) for copy-paste ready built-in blueprints.

## Custom Blueprints

```bash
# Initialize from a built-in
cd ~/.ops/blueprints
ops blueprint-init myapp --from simple-lxc
# Now edit myapp.yaml
ops deploy myapp
```

User blueprints live in `~/.ops/blueprints/` and take precedence over built-ins.
