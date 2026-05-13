"""Tests for ops.core.audit."""

import json

from ops.core.audit import AuditLogger


class TestAuditLogger:
    def test_log_creates_file(self, tmp_ops_dir):
        logger = AuditLogger(str(tmp_ops_dir))
        logger.log("deploy", vmid=100, status="started")
        log_file = tmp_ops_dir / "audit.log"
        assert log_file.exists()

    def test_log_entry_structure(self, tmp_ops_dir):
        logger = AuditLogger(str(tmp_ops_dir))
        logger.log("deploy", host="pve-01", vmid=100, status="ok", details="test")
        raw = (tmp_ops_dir / "audit.log").read_text()
        entry = json.loads(raw.strip())
        assert entry["command"] == "deploy"
        assert entry["host"] == "pve-01"
        assert entry["vmid"] == 100
        assert entry["status"] == "ok"
        assert entry["details"] == "test"
        assert "timestamp" in entry

    def test_read_events_filter_by_app(self, tmp_ops_dir):
        logger = AuditLogger(str(tmp_ops_dir))
        logger.log("myapp", vmid=100, status="ok")
        logger.log("other", vmid=200, status="failed")
        results = logger.read_events(app="myapp")
        assert len(results) == 1
        assert results[0]["command"] == "myapp"

    def test_read_events_filter_by_status(self, tmp_ops_dir):
        logger = AuditLogger(str(tmp_ops_dir))
        logger.log("a", status="ok")
        logger.log("b", status="failed")
        results = logger.read_events(status="failed")
        assert len(results) == 1
        assert results[0]["command"] == "b"

    def test_read_events_tail(self, tmp_ops_dir):
        logger = AuditLogger(str(tmp_ops_dir))
        for i in range(5):
            logger.log(f"cmd{i}", status="ok")
        results = logger.read_events(tail=2)
        assert len(results) == 2
        assert results[0]["command"] == "cmd3"

    def test_log_result(self, tmp_ops_dir):
        logger = AuditLogger(str(tmp_ops_dir))
        logger.log_result("deploy", vmid=100, success=False, details="boom")
        entry = json.loads((tmp_ops_dir / "audit.log").read_text().strip())
        assert entry["status"] == "failed"
        assert entry["details"] == "boom"
