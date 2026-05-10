services:
  haproxy:
    image: haproxy:lts-alpine
    container_name: haproxy
    restart: unless-stopped
    network_mode: "host"
    volumes:
      - ./haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro
