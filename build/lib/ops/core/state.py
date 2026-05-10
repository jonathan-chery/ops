import json
from pathlib import Path
from typing import Optional

from ..models.state import DeploymentState, DeploymentPhase


class StateManager:
    def __init__(self, state_dir: str = "~/.ops/state"):
        self.state_dir = Path(state_dir).expanduser()
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _state_path(self, app_name: str) -> Path:
        return self.state_dir / f"{app_name}.json"

    def load(self, app_name: str) -> Optional[DeploymentState]:
        path = self._state_path(app_name)
        if not path.exists():
            return None
        with open(path, "r") as f:
            data = json.load(f)
        # Convert string phases back to enum
        data["phases_completed"] = set(data.get("phases_completed", []))
        data["current_phase"] = DeploymentPhase(data.get("current_phase", "preflight"))
        return DeploymentState(**data)

    def save(self, state: DeploymentState):
        path = self._state_path(state.app_name)
        data = state.model_dump(mode="json")
        data["phases_completed"] = list(data["phases_completed"])
        data["current_phase"] = state.current_phase.value
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def delete(self, app_name: str):
        path = self._state_path(app_name)
        if path.exists():
            path.unlink()

    def list(self) -> list:
        states = []
        for f in self.state_dir.glob("*.json"):
            app_name = f.stem
            state = self.load(app_name)
            if state:
                states.append(state)
        return states
