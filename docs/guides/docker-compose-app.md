# Guide: Docker Compose App

Deploy a real-world web application using Docker Compose inside an LXC container.

## Blueprint

```yaml
version: "1.2"
name: mywebapp
container:
  hostname: mywebapp-01
  cores: 2
  memory: 4096
  disk: 20480
deployment:
  type: docker
  docker:
    compose_file: docker-compose.yml
    env_file: .env
templates:
  - source: docker-compose.yml.tpl
    dest: /opt/mywebapp/docker-compose.yml
    mode: "0644"
  - source: .env.tpl
    dest: /opt/mywebapp/.env
    mode: "0600"
secrets:
  - name: DB_PASSWORD
    type: generated
    length: 32
  - name: API_SECRET
    type: generated
    length: 48
health_check:
  enabled: true
  port: 80
  path: /health
  interval: 30
environment:
  APP_NAME: MyWebApp
```

## Template: docker-compose.yml.tpl

```yaml
version: "3.8"
services:
  web:
    image: nginx:alpine
    ports:
      - "80:80"
    env_file: .env
    volumes:
      - ./html:/usr/share/nginx/html
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:80/health"]
      interval: 30s
      timeout: 5s
      retries: 3
```

## Template: .env.tpl

```
DB_PASSWORD={{ secrets.DB_PASSWORD }}
API_SECRET={{ secrets.API_SECRET }}
APP_NAME={{ environment.APP_NAME }}
```

## Deploy

```bash
ops deploy mywebapp
```

## Verify

```bash
ops status mywebapp
ops logs mywebapp
ops exec mywebapp "docker ps"
```

## Sync After Config Change

Edit the template, then:

```bash
ops sync mywebapp
```

This re-renders templates inside the container and restarts services.
