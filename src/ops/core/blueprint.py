from pathlib import Path
from typing import Optional

import yaml

from ..models.blueprint import AppBlueprint


class BlueprintManager:
    def __init__(self, user_dir: str = "~/.ops/blueprints", builtin_dir: Optional[str] = None):
        self.user_dir = Path(user_dir).expanduser()
        self.user_dir.mkdir(parents=True, exist_ok=True)

        if builtin_dir is None:
            import ops
            ops_file = ops.__file__
            if ops_file is None:
                raise RuntimeError("Unable to determine built-in blueprints directory")
            self.builtin_dir = Path(ops_file).parent / "blueprints"
        else:
            self.builtin_dir = Path(builtin_dir)

    def list(self) -> list:
        names = set()
        if self.builtin_dir.exists():
            for f in self.builtin_dir.glob("*.yaml"):
                names.add(f.stem)
        for f in self.user_dir.glob("*.yaml"):
            names.add(f.stem)
        return sorted(names)

    def load(self, name: str) -> AppBlueprint:
        user_path = self.user_dir / f"{name}.yaml"
        builtin_path = self.builtin_dir / f"{name}.yaml"

        path = user_path if user_path.exists() else builtin_path
        if not path.exists():
            raise FileNotFoundError(f"Blueprint '{name}' not found in user or built-in directories")

        with open(path, "r") as f:
            data = yaml.safe_load(f)

        bp = AppBlueprint(**data)

        # Resolve template sources to absolute paths relative to the blueprint file
        base_dir = path.parent
        for tpl in bp.templates:
            src = Path(tpl.source)
            if not src.is_absolute():
                tpl.source = str(base_dir / "templates" / src.name)

        return bp

    def show(self, name: str) -> dict:
        """Load a blueprint and return its resolved representation."""
        bp = self.load(name)
        # Resolve computed values into a clean dict
        d = bp.model_dump(mode="json", exclude_none=True)
        return d

    def save(self, blueprint: AppBlueprint):
        path = self.user_dir / f"{blueprint.name}.yaml"
        with open(path, "w") as f:
            yaml.dump(blueprint.model_dump(mode="json", exclude_none=True), f, default_flow_style=False, sort_keys=False)

    def init_from_template(self, name: str, template_name: str):
        builtin_path = self.builtin_dir / f"{template_name}.yaml"
        if not builtin_path.exists():
            raise FileNotFoundError(f"Built-in blueprint '{template_name}' not found")

        user_path = self.user_dir / f"{name}.yaml"
        if user_path.exists():
            raise FileExistsError(f"User blueprint '{name}' already exists")

        with open(builtin_path, "r") as f:
            data = yaml.safe_load(f)
        data["name"] = name
        data["container"]["hostname"] = name

        with open(user_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
