# Blueprints Gallery

Copy-paste any of these built-in blueprints into your own deployment or customize them in `~/.ops/blueprints/`.

## simple-lxc

Bare Ubuntu 24.04 container. No application.

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

## postgres

PostgreSQL 16 via Docker Compose.

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

## cockroachdb

CockroachDB single-node cluster.

```yaml
version: "1.2"
name: cockroachdb
container:
  hostname: cockroachdb-01
  cores: 4
  memory: 8192
  disk: 40960
  template: ubuntu-24.04-standard_24.04-1_amd64.tar.zst
network:
  bridge: vmbr1
  mode: dhcp
deployment:
  type: docker
  docker:
    compose_file: cockroachdb-compose.yml
    env_file: cockroachdb.env
templates:
  - source: cockroachdb-compose.yml.tpl
    dest: /opt/cockroachdb/cockroachdb-compose.yml
    mode: "0644"
secrets:
  - name: COCKROACH_PASSWORD
    type: generated
    length: 32
dependencies:
  install_docker: true
health_check:
  enabled: true
  port: 8080
  path: /health
  interval: 30
```

## haproxy

HAProxy load balancer.

```yaml
version: "1.2"
name: haproxy
container:
  hostname: haproxy-01
  cores: 2
  memory: 2048
  disk: 10240
  template: ubuntu-24.04-standard_24.04-1_amd64.tar.zst
network:
  bridge: vmbr1
  mode: dhcp
deployment:
  type: docker
  docker:
    compose_file: haproxy-compose.yml
templates:
  - source: haproxy-compose.yml.tpl
    dest: /opt/haproxy/haproxy-compose.yml
    mode: "0644"
  - source: haproxy.cfg.tpl
    dest: /opt/haproxy/haproxy.cfg
    mode: "0644"
dependencies:
  install_docker: true
health_check:
  enabled: true
  port: 80
  path: /
  interval: 30
```

## lxc-docker

Pre-installed Docker CE host.

```yaml
version: "1.2"
name: lxc-docker
container:
  hostname: docker-host
  cores: 2
  memory: 4096
  disk: 20480
  template: ubuntu-24.04-standard_24.04-1_amd64.tar.zst
network:
  bridge: vmbr1
  mode: dhcp
deployment:
  type: none
dependencies:
  install_docker: true
```

## lxc-podman

Pre-installed Podman host.

```yaml
version: "1.2"
name: lxc-podman
container:
  hostname: podman-host
  cores: 2
  memory: 4096
  disk: 20480
  template: ubuntu-24.04-standard_24.04-1_amd64.tar.zst
network:
  bridge: vmbr1
  mode: dhcp
deployment:
  type: none
dependencies:
  install_podman: true
```

## Customizing

```bash
cd ~/.ops/blueprints
ops blueprint-init myapp --from postgres
# Edit myapp.yaml
ops deploy myapp
```
