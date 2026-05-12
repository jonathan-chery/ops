# Guide: Native Systemd App

Deploy a Node.js application as a systemd service inside an LXC container.

## Blueprint

```yaml
version: "1.2"
name: mynodeapp
container:
  hostname: mynodeapp-01
  cores: 2
  memory: 2048
  disk: 10240
deployment:
  type: native
  runtime: nodejs
  runtime_version: 20
  native:
    app_user: app
    app_dir: /opt/mynodeapp
    service_command: node index.js
    service_env_file: /opt/mynodeapp/.env
templates:
  - source: index.js.tpl
    dest: /opt/mynodeapp/index.js
    mode: "0644"
  - source: .env.tpl
    dest: /opt/mynodeapp/.env
    mode: "0600"
secrets:
  - name: API_KEY
    type: generated
    length: 32
environment:
  PORT: "3000"
health_check:
  enabled: true
  port: 3000
  path: /health
  interval: 30
dependencies:
  install_podman: false
```

## Template: index.js.tpl

```javascript
const http = require('http');
const PORT = process.env.PORT || 3000;

const server = http.createServer((req, res) => {
  if (req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok', version: '{{ version }}' }));
    return;
  }
  res.writeHead(200);
  res.end('Hello from {{ name }}\n');
});

server.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});
```

## Deploy

```bash
ops deploy mynodeapp
```

## Verify

```bash
ops status mynodeapp
ops logs mynodeapp
ops exec mynodeapp "systemctl status mynodeapp"
```
