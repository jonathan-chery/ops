# Templates Gallery

Templates are Jinja2 files that are rendered with the deployment context and pushed into the container.

## Available Context Variables

| Variable | Type | Description |
|---|---|---|
| `environment` | `dict[str, str]` | Static environment from blueprint |
| `secrets` | `dict[str, str]` | Resolved secret values |
| `ip` | `str` | Allocated container IP |
| `name` | `str` | Application name |
| `hostname` | `str` | Container hostname |
| `vmid` | `int` | Proxmox VMID |

## postgres.env.tpl

```jinja2
POSTGRES_DB={{ environment.POSTGRES_DB }}
POSTGRES_USER={{ secrets.POSTGRES_USER }}
POSTGRES_PASSWORD={{ secrets.POSTGRES_PASSWORD }}
```

Rendered and pushed to `/opt/postgres/postgres.env`.

## postgres-compose.yml.tpl

```jinja2
version: "3.8"
services:
  db:
    image: postgres:16
    restart: unless-stopped
    env_file: postgres.env
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5
volumes:
  pgdata:
```

## cockroachdb-compose.yml.tpl

```jinja2
version: "3.8"
services:
  cockroach:
    image: cockroachdb/cockroach:latest
    command: start-single-node --insecure
    ports:
      - "8080:8080"
      - "26257:26257"
    volumes:
      - cockroach-data:/cockroach/cockroach-data
volumes:
  cockroach-data:
```

## haproxy.cfg.tpl

```jinja2
global
    maxconn 4096

defaults
    mode http
    timeout connect 5000ms
    timeout client 50000ms
    timeout server 50000ms

frontend http_in
    bind *:80
    default_backend servers

backend servers
    balance roundrobin
    server server1 10.0.0.10:80 check
    server server2 10.0.0.11:80 check
```

## haproxy-compose.yml.tpl

```jinja2
version: "3.8"
services:
  haproxy:
    image: haproxy:2.9-alpine
    restart: unless-stopped
    ports:
      - "80:80"
    volumes:
      - ./haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro
```

## Writing Custom Templates

Place `.tpl` files next to your blueprint in `~/.ops/blueprints/` or reference them from the blueprint:

```yaml
templates:
  - source: my-custom.conf.tpl
    dest: /opt/myapp/my-custom.conf
    mode: "0644"
```

**Security:** Templates are rendered in a **Jinja2 SandboxedEnvironment** in `ops.utils.templates`. No unrestricted Python code execution is allowed.
