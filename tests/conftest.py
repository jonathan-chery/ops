"""Test fixtures and shared utilities for the ops test suite."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def tmp_ops_dir():
    """Provide a temporary ``~/.ops``-like directory."""
    with tempfile.TemporaryDirectory() as td:
        old_home = os.environ.get("HOME")
        os.environ["HOME"] = td
        yield Path(td)
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home


@pytest.fixture
def mock_proxmox_provider():
    """Return a mocked ProxmoxProvider with stubbed methods."""
    mock = MagicMock()
    mock.create_lxc.return_value = None
    mock.start_lxc.return_value = None
    mock.stop_lxc.return_value = None
    mock.destroy_lxc.return_value = None
    mock.get_container.return_value = MagicMock(
        vmid=100,
        hostname="test-host",
        name="test-app",
        status="running",
        ip="10.0.0.10",
        uptime="1d",
    )
    mock.list_containers.return_value = [
        MagicMock(
            vmid=100,
            hostname="test-host",
            name="test-app",
            status="running",
            ip="10.0.0.10",
            uptime="1d",
        )
    ]
    mock.resolve_template_volid.return_value = "local:vztmpl/test.tar.gz"
    mock.get_used_vmids.return_value = set()
    mock.get_used_ips.return_value = set()
    mock.wait_for_boot.return_value = True
    mock.wait_for_network.return_value = True
    mock.exec.return_value = MagicMock(stdout="", stderr="", exit_code=0)
    return mock


@pytest.fixture
def sample_blueprint():
    """Return a minimal valid AppBlueprint dictionary."""
    return {
        "version": "1.2",
        "name": "test-app",
        "description": "Test application blueprint",
        "container": {
            "hostname": "test-host",
            "cores": 1,
            "memory": 512,
            "disk": 8,
        },
        "network": {},
        "deployment": {"type": "docker"},
        "health_check": {
            "enabled": True,
            "url": "http://{ip}:80/health",
            "method": "GET",
            "expected_status": 200,
            "retries": 3,
            "interval": 1,
        },
        "metrics": {"enabled": True},
        "alerting": {"enabled": False},
    }
