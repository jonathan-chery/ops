"""Tests for ops.utils.log_shipper."""

import json
import os

from ops.utils.log_shipper import LogShipper


class TestLogShipper:
    def test_write_and_read(self, tmp_ops_dir):
        shipper = LogShipper(log_dir=str(tmp_ops_dir / "logs"))
        shipper.write("myapp", "line one\n")
        shipper.write("myapp", "line two\n")
        lines = shipper.read("myapp", lines=10)
        assert lines == ["line one", "line two"]

    def test_write_json(self, tmp_ops_dir):
        shipper = LogShipper(log_dir=str(tmp_ops_dir / "logs"))
        shipper.write_json("myapp", "microvm", "hello")
        lines = shipper.read("myapp", lines=10)
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["source"] == "microvm"
        assert entry["message"] == "hello"
        assert "timestamp" in entry

    def test_permissions(self, tmp_ops_dir):
        shipper = LogShipper(log_dir=str(tmp_ops_dir / "logs"))
        shipper.write("myapp", "x")
        log_file = tmp_ops_dir / "logs" / "myapp.log"
        mode = os.stat(log_file).st_mode
        assert mode & 0o777 == 0o600

    def test_rotation(self, tmp_ops_dir):
        shipper = LogShipper(log_dir=str(tmp_ops_dir / "logs"), max_bytes=1)
        shipper.write("myapp", "a")
        shipper.write("myapp", "b")
        backup = tmp_ops_dir / "logs" / "myapp.log.1"
        assert backup.exists()
