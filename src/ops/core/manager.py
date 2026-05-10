import yaml
from pathlib import Path
from typing import Dict, Any
from .blueprint import AppBlueprint

class BlueprintManager:
    def __init__(self, blueprints_dir: str = "src/ops/templates"):
        self.blueprints_dir = Path(blueprints_dir)

    def load_blueprint(self, app_name: str) -> AppBlueprint:
        blueprint_path = self.blueprints_dir / f"{app_name}.yaml"
        if not blueprint_path.exists():
            raise FileNotFoundError(f"Blueprint for {app_name} not found at {blueprint_path}")
        
        with open(blueprint_path, 'r') as f:
            data = yaml.safe_load(f)
            
        return AppBlueprint(**data)

    def save_blueprint(self, blueprint: AppBlueprint):
        blueprint_path = self.blueprints_dir / f"{blueprint.name}.yaml"
        with open(blueprint_path, 'w') as f:
            yaml.dump(blueprint.model_dump(), f)
