"""Metrics sidecar installer for Prometheus node_exporter.

Provides lightweight helpers to download and start ``node_exporter`` inside
LXC containers and microVMs.  The binary is pulled from the official GitHub
release page and run as a background process (or systemd service if
available).
"""

import time

import paramiko

from ops.providers.proxmox import ProxmoxProvider
from ops.utils.safe_shell import quote


NODE_EXPORTER_VERSION = "1.8.2"
NODE_EXPORTER_URL = (
    f"https://github.com/prometheus/node_exporter/releases/download/v{NODE_EXPORTER_VERSION}/"
    f"node_exporter-{NODE_EXPORTER_VERSION}.linux-amd64.tar.gz"
)


def _node_exporter_install_script(port: int) -> str:
    quoted_url = quote(NODE_EXPORTER_URL)
    return f"""\
set -e
arch_url={quoted_url}
bin_dir=/usr/local/bin
systemd_dir=/etc/systemd/system
tmp_tgz=/tmp/node_exporter.tgz

if [ -x "$bin_dir/node_exporter" ]; then
    echo "node_exporter already installed"
else
    curl -fsSL "$arch_url" -o "$tmp_tgz"
    tar -xzf "$tmp_tgz" -C /tmp
    cp "/tmp/node_exporter-{NODE_EXPORTER_VERSION}.linux-amd64/node_exporter" "$bin_dir/node_exporter"
    chmod +x "$bin_dir/node_exporter"
    rm -rf "$tmp_tgz" "/tmp/node_exporter-{NODE_EXPORTER_VERSION}.linux-amd64"
fi

# Start via systemd if available, otherwise background nohup
if command -v systemctl >/dev/null 2>&1; then
    cat > "$systemd_dir/node_exporter.service" <<EOF
[Unit]
Description=Node Exporter

[Service]
ExecStart=$bin_dir/node_exporter --web.listen-address=:{port}
Restart=always

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable node_exporter
    systemctl restart node_exporter
    echo "node_exporter started via systemd"
else
    nohup "$bin_dir/node_exporter" --web.listen-address=:{port} >/dev/null 2>&1 &
echo "node_exporter started (background)"
"""


def install_node_exporter_lxc(
    proxmox: ProxmoxProvider,
    vmid: int,
    node: str,
    port: int = 9100,
) -> None:
    """Install and start node_exporter inside an LXC container.

    Args:
        proxmox: Active Proxmox provider.
        vmid: Container VMID.
        node: Proxmox node name.
        port: TCP port for the metrics endpoint.
    """
    script = _node_exporter_install_script(port)
    proxmox.exec(vmid, f"bash -c {quote(script)}", node=node)


def install_node_exporter_microvm(
    ip: str,
    ssh_key_path: str,
    port: int = 9100,
    timeout: int = 120,
) -> None:
    """Install and start node_exporter inside a microVM via SSH.

    Args:
        ip: Guest IP address.
        ssh_key_path: Path to the private SSH key for root authentication.
        port: TCP port for the metrics endpoint.
        timeout: Max seconds to wait for SSH connectivity.
    """
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # Wait for SSH
    deadline = time.time() + timeout
    connected = False
    while time.time() < deadline:
        try:
            client.connect(ip, username="root", key_filename=ssh_key_path, timeout=5)
            connected = True
            break
        except Exception:
            time.sleep(2)

    if not connected:
        raise RuntimeError(f"Could not SSH into microVM {ip} to install node_exporter")

    try:
        script = _node_exporter_install_script(port)
        stdin, stdout, stderr = client.exec_command(f"bash -c {quote(script)}")
        rc = stdout.channel.recv_exit_status()
        if rc != 0:
            err = stderr.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"node_exporter installation failed in microVM: {err}")
    finally:
        client.close()
