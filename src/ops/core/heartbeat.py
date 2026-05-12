import json
import os
import time
import urllib3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict

import requests

from ..models.blueprint import AppBlueprint
from ..models.state import DeploymentState
from ..providers.proxmox import ProxmoxProvider

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class HeartbeatManager:
    def __init__(self, heartbeat_dir: str = "~/.ops/heartbeats"):
        self.heartbeat_dir = Path(heartbeat_dir).expanduser()
        self.heartbeat_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.heartbeat_dir, 0o700)

    def _heartbeat_path(self, app_name: str) -> Path:
        return self.heartbeat_dir / f"{app_name}_latest.json"

    def run_health_check(
        self,
        blueprint: AppBlueprint,
        vmid: int,
        ip: str,
        proxmox: ProxmoxProvider,
        node: Optional[str] = None,
    ) -> Dict:
        hc = blueprint.health_check
        if not hc.enabled or not hc.url:
            return {"status": "skipped", "reason": "health_check disabled"}

        # Substitute variables in URL
        url = hc.url.replace("{ip}", ip)
        for key, value in blueprint.environment.items():
            url = url.replace(f"{{{key}}}", str(value))

        for attempt in range(hc.retries):
            try:
                response = requests.request(
                    hc.method,
                    url,
                    timeout=10,
                    verify=False,
                )
                if response.status_code == hc.expected_status:
                    return {
                        "status": "ok",
                        "url": url,
                        "status_code": response.status_code,
                        "attempts": attempt + 1,
                    }
            except requests.RequestException:
                pass
            time.sleep(hc.interval)

        return {
            "status": "failed",
            "url": url,
            "attempts": hc.retries,
            "error": f"Did not reach expected status {hc.expected_status} after {hc.retries} attempts",
        }

    def generate_heartbeat(
        self,
        app_name: str,
        blueprint: AppBlueprint,
        state: DeploymentState,
        health_result: Dict,
        ssh_keys: Dict[str, str],
    ) -> Dict:
        heartbeat = {
            "app": app_name,
            "vmid": state.vmid,
            "hostname": blueprint.container.hostname,
            "ip": state.ip,
            "node": state.node,
            "status": "HEARTBEAT_OK" if health_result.get("status") == "ok" else "HEARTBEAT_FAILED",
            "deployed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "") + "Z",
            "health_check": health_result,
            "ssh_keys": ssh_keys,
            "access": {
                "http": f"http://{state.ip}:{blueprint.environment.get('PORT', '80')}",
            },
        }

        path = self._heartbeat_path(app_name)
        with open(path, "w") as f:
            json.dump(heartbeat, f, indent=2)
        os.chmod(path, 0o600)

        return heartbeat

    def load(self, app_name: str) -> Optional[Dict]:
        path = self._heartbeat_path(app_name)
        if not path.exists():
            return None
        with open(path, "r") as f:
            return json.load(f)
