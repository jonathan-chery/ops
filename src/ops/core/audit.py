import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class AuditLogger:
    """Append-only audit logger with rotation. Keeps last 5 files, 10MB max each."""

    def __init__(self, log_dir: str = "~/.ops"):
        self.log_dir = Path(log_dir).expanduser()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "audit.log"
        self.max_bytes = 10 * 1024 * 1024  # 10 MB
        self.backup_count = 5

    def _rotate(self):
        """Rotate log files if current exceeds max_bytes."""
        if not self.log_file.exists():
            return
        if self.log_file.stat().st_size < self.max_bytes:
            return
        # Rotate: audit.log -> audit.log.1 -> audit.log.2 ...
        for i in range(self.backup_count - 1, 0, -1):
            src = self.log_dir / f"audit.log.{i}"
            dst = self.log_dir / f"audit.log.{i + 1}"
            if src.exists():
                src.rename(dst)
        self.log_file.rename(self.log_dir / "audit.log.1")

    def log(
        self,
        command: str,
        host: Optional[str] = None,
        vmid: Optional[int] = None,
        status: str = "started",
        details: Optional[str] = None,
    ):
        """Write a single audit entry."""
        self._rotate()
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uid": os.getuid(),
            "command": command,
            "host": host,
            "vmid": vmid,
            "status": status,
            "details": details,
        }
        with open(self.log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def log_result(
        self,
        command: str,
        host: Optional[str] = None,
        vmid: Optional[int] = None,
        success: bool = True,
        details: Optional[str] = None,
    ):
        """Convenience wrapper to log completion of a command."""
        self.log(
            command=command,
            host=host,
            vmid=vmid,
            status="ok" if success else "failed",
            details=details,
        )
