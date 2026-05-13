"""Persistent console/serial log shipping and local rotation."""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List


class LogShipper:
    """Ships console/serial logs to a local rotated file under ``~/.ops/logs``.

    Each app receives its own log file (``<app>.log``) with size-based
    rotation (10 MB, 5 backups) and ``0o600`` permissions.

    Examples:
        >>> shipper = LogShipper()
        >>> shipper.write("myapp", "hello")
        >>> shipper.read("myapp", lines=10)
        ['hello']
    """

    def __init__(
        self,
        log_dir: str = "~/.ops/logs",
        max_bytes: int = 10 * 1024 * 1024,
        backup_count: int = 5,
    ):
        self.log_dir = Path(log_dir).expanduser()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.log_dir, 0o700)
        self.max_bytes = max_bytes
        self.backup_count = backup_count

    def _log_file(self, app_name: str) -> Path:
        return self.log_dir / f"{app_name}.log"

    def _rotate(self, app_name: str) -> None:
        log_file = self._log_file(app_name)
        if not log_file.exists():
            return
        if log_file.stat().st_size < self.max_bytes:
            return
        for i in range(self.backup_count - 1, 0, -1):
            src = self.log_dir / f"{app_name}.log.{i}"
            dst = self.log_dir / f"{app_name}.log.{i + 1}"
            if src.exists():
                src.rename(dst)
                os.chmod(dst, 0o600)
        log_file.rename(self.log_dir / f"{app_name}.log.1")
        os.chmod(self.log_dir / f"{app_name}.log.1", 0o600)

    def write(self, app_name: str, data: str) -> None:
        """Append a raw string to the app's log file."""
        self._rotate(app_name)
        log_file = self._log_file(app_name)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(data)
        os.chmod(log_file, 0o600)

    def write_json(self, app_name: str, source: str, message: str) -> None:
        """Append a structured JSON log line with timestamp and source."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "message": message,
        }
        self.write(app_name, json.dumps(entry) + "\n")

    def read(self, app_name: str, lines: int = 100) -> List[str]:
        """Read the last *lines* lines from the app's log file."""
        log_file = self._log_file(app_name)
        if not log_file.exists():
            return []
        with open(log_file, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
        # Strip trailing newlines for display
        return [line.rstrip("\n") for line in all_lines[-lines:]]

    def follow(self, app_name: str, interval: float = 0.5):
        """Generator yielding new log lines as they are written.

        Yields:
            str: Raw log line (without trailing newline).
        """
        log_file = self._log_file(app_name)
        if not log_file.exists():
            return
        with open(log_file, "r", encoding="utf-8") as f:
            f.seek(0, 2)
            while True:
                line = f.readline()
                if not line:
                    time.sleep(interval)
                    continue
                yield line.rstrip("\n")
