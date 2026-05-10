services:
  cockroachdb:
    image: cockroachdb/cockroach:latest
    container_name: cockroachdb
    restart: unless-stopped
    network_mode: "host"
    command: start-single-node --insecure --advertise-addr={{ ip }}
    volumes:
      - cockroach_data:/cockroach/cockroach-data

volumes:
  cockroach_data:
