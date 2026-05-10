from typing import Optional
from pydantic import BaseModel


class SecretSource(BaseModel):
    name: str
    type: str  # generated, infisical, prompt, file
    value: Optional[str] = None
    encrypted: bool = False


class SecretValue(BaseModel):
    name: str
    value: str
    source: str
    encrypted_at_rest: bool = True
