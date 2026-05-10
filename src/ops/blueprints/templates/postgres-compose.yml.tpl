services:
  postgres:
    image: postgres:16-alpine
    container_name: {{ name }}_db
    restart: unless-stopped
    network_mode: "host"
    environment:
      POSTGRES_USER: {{ environment.POSTGRES_USER }}
      POSTGRES_PASSWORD: {{ secrets.POSTGRES_PASSWORD }}
      POSTGRES_DB: {{ environment.POSTGRES_DB }}
      PGDATA: {{ environment.PGDATA }}
    volumes:
      - postgres_data:{{ environment.PGDATA }}

volumes:
  postgres_data:
