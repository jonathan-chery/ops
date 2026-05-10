from typing import List, Optional
from pydantic import BaseModel

class ResourceConfig(BaseModel):
    cores: int = 1
    memory: int = 512
    disk: int = 8

class AppBlueprint(BaseModel):
    name: str
    template: str
    resources: ResourceConfig
    env_vars: List[str] = []
    install_steps: List[str] = []
    services: List[str] = []
