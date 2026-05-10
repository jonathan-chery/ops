global
    maxconn 4096

defaults
    mode http
    timeout connect 5s
    timeout client 30s
    timeout server 30s

frontend http_in
    bind *:80
    default_backend servers

backend servers
    balance roundrobin
    # Add your backend servers here:
    # server backend1 10.0.0.10:80 check
