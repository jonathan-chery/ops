"""Alert manager for generic HTTP webhook notifications."""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Any

import requests


class AlertManager:
    """Sends generic HTTP webhook alerts with deduplication/cooldown.

    Configuration is read from the global ``OpsConfig.alerting`` block and
    can be overridden per-application via blueprint ``alerting`` settings.

    Examples:
        >>> mgr = AlertManager()
        >>> mgr.send_alert("myapp", 100, "pve-01", "health check failed")
        False
    """

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        cooldown_seconds: int = 900,
        state_dir: str = "~/.ops",
    ):
        self.webhook_url = webhook_url
        self.cooldown_seconds = cooldown_seconds
        self.state_dir = Path(state_dir).expanduser()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.state_dir, 0o700)
        self._cooldown_file = self.state_dir / "alert_cooldowns.json"

    def _load_cooldowns(self) -> Dict[str, float]:
        if not self._cooldown_file.exists():
            return {}
        try:
            with open(self._cooldown_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_cooldowns(self, cooldowns: Dict[str, float]) -> None:
        with open(self._cooldown_file, "w", encoding="utf-8") as f:
            json.dump(cooldowns, f)
        os.chmod(self._cooldown_file, 0o600)

    def _is_on_cooldown(self, app_name: str) -> bool:
        cooldowns = self._load_cooldowns()
        last_fired = cooldowns.get(app_name)
        if last_fired is None:
            return False
        return (time.time() - last_fired) < self.cooldown_seconds

    def _record_fired(self, app_name: str) -> None:
        cooldowns = self._load_cooldowns()
        cooldowns[app_name] = time.time()
        self._save_cooldowns(cooldowns)

    def send_alert(
        self,
        app_name: str,
        vmid: Optional[int],
        node: Optional[str],
        error: str,
        status: str = "critical",
        details: Optional[Dict] = None,
    ) -> bool:
        """Send a webhook alert if configured and not on cooldown.

        Returns True if an alert was dispatched (or would have been if a
        webhook URL is configured).  Returns False when on cooldown.
        """
        if not self.webhook_url:
            return False
        if self._is_on_cooldown(app_name):
            return False

        payload = {
            "app": app_name,
            "vmid": vmid,
            "node": node,
            "status": status,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "details": details or {},
        }

        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=10,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            self._record_fired(app_name)
            return True
        except requests.RequestException:
            # Silently fail on transport errors; ops is infrastructure, not
            # a critical alerting path.
            return False

    def test_alert(self) -> bool:
        """Send a test alert payload to verify the webhook configuration.

        Returns True if the webhook responded with a 2xx status.
        """
        if not self.webhook_url:
            return False
        payload: Dict[str, Any] = {
            "app": "ops-test",
            "vmid": None,
            "node": None,
            "status": "test",
            "error": "This is a test alert from ops",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "details": {},
        }
        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=10,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            return True
        except requests.RequestException:
            return False
