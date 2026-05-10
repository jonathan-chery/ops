import typer
from typing import Optional
from .core.manager import BlueprintManager
from .core.orchestrator import Orchestrator
from .providers.proxmox import ProxmoxProvider
from .providers.infisical import InfisicalProvider

app = typer.Typer()
manager = BlueprintManager()

# Mock configuration - in real use these would be in a config file or env vars
PROXM_CONF = {
    "host": "pve.local",
    "user": "root",
    "token_name": "ops-token",
    "token_value": "xxxx-xxxx",
}
INFISICAL_CONF = {
    "client_id": "cid",
    "client_secret": "csecret",
    "org_id": "oid",
}

def get_orchestrator():
    proxmox = ProxmoxProvider(**PROXM_CONF)
    infisical = InfisicalProvider(**INFISICAL_CONF)
    return Orchestrator(proxmox, infisical)

@app.command()
def deploy(app_name: str):
    """Deploy an application based on its blueprint."""
    blueprint = manager.load_blueprint(app_name)
    orchestrator = get_orchestrator()
    orchestrator.deploy(blueprint)

@app.command()
def teardown(app_name: str):
    """Teardown an application instance."""
    blueprint = manager.load_blueprint(app_name)
    orchestrator = get_orchestrator()
    orchestrator.teardown(blueprint)

if __name__ == "__main__":
    app()
