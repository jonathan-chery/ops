import os
from pathlib import Path
from typing import Dict, Any

from jinja2 import Environment, BaseLoader


class TemplateEngine:
    def __init__(self):
        self.env = Environment(loader=BaseLoader())

    def render_string(self, template_str: str, context: Dict[str, Any]) -> str:
        template = self.env.from_string(template_str)
        return template.render(**context)

    def render_file(self, template_path: str, context: Dict[str, Any]) -> str:
        path = Path(template_path)
        if not path.exists():
            raise FileNotFoundError(f"Template not found: {template_path}")
        content = path.read_text()
        return self.render_string(content, context)

    def render_to_file(
        self,
        template_path: str,
        output_path: str,
        context: Dict[str, Any],
        mode: str = "600",
    ):
        rendered = self.render_file(template_path, context)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered)
        os.chmod(out, int(mode, 8))
