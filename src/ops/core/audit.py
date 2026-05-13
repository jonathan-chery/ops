import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List


class AuditLogger:
    """Append-only audit logger with rotation. Keeps last 5 files, 10MB max each.

    Examples:
        >>> logger = AuditLogger(log_dir="/tmp/test_audit")
        >>> logger.log("deploy", vmid=100, status="started")
        >>> events = logger.read_events()
        >>> len(events)
        1
        >>> events[0]["command"]
        'deploy'
    """

    def __init__(self, log_dir: str = "~/.ops"):
        self.log_dir = Path(log_dir).expanduser()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.log_dir, 0o700)
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
                os.chmod(dst, 0o600)
        self.log_file.rename(self.log_dir / "audit.log.1")
        os.chmod(self.log_dir / "audit.log.1", 0o600)

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
        os.chmod(self.log_file, 0o600)

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

    def _read_all_lines(self) -> List[str]:
        """Read all audit log lines from primary and rotated files."""
        lines: List[str] = []
        # Read rotated files first (oldest)
        for i in range(self.backup_count, 0, -1):
            path = self.log_dir / f"audit.log.{i}"
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    lines.extend(f.readlines())
        if self.log_file.exists():
            with open(self.log_file, "r", encoding="utf-8") as f:
                lines.extend(f.readlines())
        return lines

    def read_events(
        self,
        app: Optional[str] = None,
        status: Optional[str] = None,
        since: Optional[str] = None,
        tail: Optional[int] = None,
    ) -> List[Dict]:
        """Read and filter audit log events.

        Args:
            app: Filter by application name (matches ``command`` or log
                entries that contain the app name in ``details``).
            status: Filter by status string (e.g. ``ok``, ``failed``).
            since: ISO-8601 timestamp string; only include events at or
                after this time.
            tail: Maximum number of most-recent events to return.

        Returns:
            List of event dictionaries sorted oldest -> newest.
        """
        events: List[Dict] = []
        cutoff = datetime.fromisoformat(since) if since else None

        for line in self._read_all_lines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            # app filter — match command or details containing app name
            if app is not None:
                if event.get("command") != app and (
                    not event.get("details") or app not in event["details"]
                ):
                    continue

            if status is not None and event.get("status") != status:
                continue

            if cutoff is not None:
                ts = event.get("timestamp")
                if ts:
                    try:
                        event_ts = datetime.fromisoformat(ts)
                        if event_ts < cutoff:
                            continue
                    except ValueError:
                        pass

            events.append(event)

        if tail is not None:
            events = events[-tail:]
        return events

    def follow_events(self, app: Optional[str] = None, status: Optional[str] = None):
        """Generator yielding new audit events as they are written.

        This reads from the current end of the log file and yields any
        newly appended lines.  It does not handle rotation mid-follow;
        callers should restart the generator if the file is rotated.

        Yields:
            dict: Parsed JSON audit event.
        """
        if not self.log_file.exists():
            return
        with open(self.log_file, "r", encoding="utf-8") as f:
            # Seek to end
            f.seek(0, 2)
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.5)
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if app is not None:
                    if event.get("command") != app and (
                        not event.get("details") or app not in event["details"]
                    ):
                        continue
                if status is not None and event.get("status") != status:
                    continue
                yield event
