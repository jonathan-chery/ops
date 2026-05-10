import typer
import yaml
from typing import Optional, List

from .core.config import ConfigManager
from .core.blueprint import BlueprintManager
from .core.orchestrator import Orchestrator
from .core.state import StateManager
from .utils.secrets import SecretManager

app = typer.Typer(help="Proxmox LXC Orchestrator CLI")


def _get_orchestrator() -> Orchestrator:
    config_mgr = ConfigManager()
    config = config_mgr.load()
    return Orchestrator(config)


def _get_blueprint_manager() -> BlueprintManager:
    return BlueprintManager()


@app.command()
def deploy(
    app_names: List[str] = typer.Argument(..., help="One or more application names to deploy"),
    force: bool = typer.Option(False, "--force", "-f", help="Force redeploy even if already deployed"),
    no_teardown_on_failure: bool = typer.Option(False, "--no-teardown-on-failure", help="Do not auto-teardown on failure"),
    parallel: bool = typer.Option(True, "--parallel/--sequential", help="Run deployments in parallel or sequentially"),
):
    """Deploy one or more applications based on their blueprints."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    blueprint_mgr = _get_blueprint_manager()
    orchestrator = _get_orchestrator()

    def _deploy_one(name):
        try:
            blueprint = blueprint_mgr.load(name)
            orchestrator.deploy(name, blueprint, force=force, no_teardown=no_teardown_on_failure)
            return (name, "success", None)
        except Exception as e:
            return (name, "failed", str(e))

    if len(app_names) == 1:
        result = _deploy_one(app_names[0])
        if result[1] == "failed":
            typer.echo(f"[ERROR] Deploying {result[0]}: {result[2]}", err=True)
            raise typer.Exit(1)
    elif not parallel:
        for name in app_names:
            result = _deploy_one(name)
            if result[1] == "failed":
                typer.echo(f"[ERROR] Deploying {result[0]}: {result[2]}", err=True)
                raise typer.Exit(1)
    else:
        typer.echo(f"Deploying {len(app_names)} apps in parallel...")
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(_deploy_one, name): name for name in app_names}
            failed = []
            for future in as_completed(futures):
                name, status, error = future.result()
                if status == "success":
                    typer.echo(f"[OK] {name} deployed successfully")
                else:
                    typer.echo(f"[ERROR] {name}: {error}", err=True)
                    failed.append(name)
            if failed:
                typer.echo(f"[WARN] Failed deployments: {', '.join(failed)}", err=True)
                raise typer.Exit(1)


@app.command()
def teardown(
    app_name: str,
    skip_backup: bool = typer.Option(False, "--skip-backup", help="Skip backup before teardown"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Teardown an application instance."""
    if not yes:
        confirm = typer.confirm(f"Are you sure you want to destroy '{app_name}'?")
        if not confirm:
            typer.echo("Aborted.")
            raise typer.Exit(0)

    blueprint_mgr = _get_blueprint_manager()
    blueprint = None
    try:
        blueprint = blueprint_mgr.load(app_name)
    except FileNotFoundError:
        pass
    orchestrator = _get_orchestrator()
    orchestrator.teardown(app_name, blueprint, skip_backup=skip_backup)


@app.command()
def status(app_name: Optional[str] = typer.Argument(None)):
    """Show container status. If no app is specified, show all managed containers."""
    state_mgr = StateManager()
    orchestrator = _get_orchestrator()

    if app_name:
        state = state_mgr.load(app_name)
        if not state or not state.vmid:
            typer.echo(f"[WARN] No container found for {app_name}")
            raise typer.Exit(1)
        container = orchestrator.proxmox.get_container(state.vmid, state.node)
        if container:
            typer.echo(f"App:        {app_name}")
            typer.echo(f"VMID:       {container.vmid}")
            typer.echo(f"Hostname:   {container.hostname}")
            typer.echo(f"Status:     {container.status}")
            typer.echo(f"IP:         {container.ip or state.ip}")
            typer.echo(f"Uptime:     {container.uptime or 'N/A'}")
        else:
            typer.echo(f"[WARN] Container {state.vmid} not found on Proxmox")
    else:
        # Only show managed containers (those with state files)
        states = state_mgr.list()
        if not states:
            typer.echo("No managed containers found.")
            return

        managed_vmids = {s.vmid for s in states}
        containers = orchestrator.proxmox.list_containers()
        if not containers:
            typer.echo("No containers found.")
            return

        typer.echo(f"{'VMID':<8} {'Name':<20} {'Status':<10} {'IP'}")
        typer.echo("-" * 60)
        for ct in containers:
            if ct.vmid in managed_vmids:
                ip = ct.ip or "N/A"
                typer.echo(f"{ct.vmid:<8} {ct.hostname or ct.name or '':<20} {ct.status:<10} {ip}")


@app.command()
def logs(
    app_name: str,
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
    lines: int = typer.Option(100, "--lines", "-n", help="Number of lines to show"),
):
    """Show application logs."""
    blueprint_mgr = _get_blueprint_manager()
    blueprint = blueprint_mgr.load(app_name)
    orchestrator = _get_orchestrator()
    output = orchestrator.get_logs(app_name, blueprint, follow=follow, lines=lines)
    typer.echo(output)


@app.command()
def exec_cmd(
    app_name: str,
    command: str,
    root: bool = typer.Option(False, "--root", "-r", help="Run as root instead of app user"),
):
    """Execute a command inside the container."""
    state_mgr = StateManager()
    state = state_mgr.load(app_name)
    if not state or not state.vmid:
        typer.echo(f"[WARN] No container found for {app_name}")
        raise typer.Exit(1)

    blueprint_mgr = _get_blueprint_manager()
    try:
        blueprint = blueprint_mgr.load(app_name)
    except FileNotFoundError:
        blueprint = None

    user = "root" if root else "appuser"
    if blueprint and blueprint.deployment.type == "native" and blueprint.deployment.native:
        user = "root" if root else blueprint.deployment.native.app_user

    orchestrator = _get_orchestrator()
    result = orchestrator.proxmox.exec(state.vmid, command, user=user, node=state.node)
    if result.stdout:
        typer.echo(result.stdout)
    if result.stderr:
        typer.echo(result.stderr, err=True)
    raise typer.Exit(result.exit_code)


@app.command()
def start(app_name: str):
    """Start a container."""
    state_mgr = StateManager()
    state = state_mgr.load(app_name)
    if not state or not state.vmid:
        typer.echo(f"[WARN] No container found for {app_name}")
        raise typer.Exit(1)
    orchestrator = _get_orchestrator()
    orchestrator.proxmox.start_lxc(state.vmid, state.node)
    typer.echo(f"[OK] Container {app_name} started")


@app.command()
def stop(app_name: str):
    """Stop a container."""
    state_mgr = StateManager()
    state = state_mgr.load(app_name)
    if not state or not state.vmid:
        typer.echo(f"[WARN] No container found for {app_name}")
        raise typer.Exit(1)
    orchestrator = _get_orchestrator()
    orchestrator.proxmox.stop_lxc(state.vmid, state.node)
    typer.echo(f"[OK] Container {app_name} stopped")


@app.command()
def restart(app_name: str):
    """Restart the application service inside the container."""
    blueprint_mgr = _get_blueprint_manager()
    blueprint = blueprint_mgr.load(app_name)
    orchestrator = _get_orchestrator()
    orchestrator.restart_service(app_name, blueprint)
    typer.echo(f"[OK] Service {app_name} restarted")


@app.command("list")
def list_containers():
    """List all managed containers."""
    state_mgr = StateManager()
    states = state_mgr.list()
    if not states:
        typer.echo("No managed containers found.")
        return

    managed_vmids = {s.vmid for s in states}
    orchestrator = _get_orchestrator()
    containers = orchestrator.proxmox.list_containers()
    if not containers:
        typer.echo("No containers found.")
        return

    typer.echo(f"{'VMID':<8} {'Name':<20} {'Status':<10} {'IP'}")
    typer.echo("-" * 60)
    for ct in containers:
        if ct.vmid in managed_vmids:
            ip = ct.ip or "N/A"
            typer.echo(f"{ct.vmid:<8} {ct.hostname or ct.name or '':<20} {ct.status:<10} {ip}")


@app.command()
def sync(app_name: str):
    """Sync templates and environment files without full rebuild."""
    blueprint_mgr = _get_blueprint_manager()
    blueprint = blueprint_mgr.load(app_name)
    orchestrator = _get_orchestrator()
    orchestrator.sync(app_name, blueprint)
    typer.echo(f"[OK] {app_name} synced")


@app.command("config")
def config_cmd(
    edit: bool = typer.Option(False, "--edit", "-e", help="Open config in editor"),
    show: bool = typer.Option(False, "--show", "-s", help="Show current config"),
):
    """Manage CLI configuration."""
    import os
    config_mgr = ConfigManager()
    if show:
        config = config_mgr.load()
        typer.echo(config.model_dump_json(indent=2))
    elif edit:
        import subprocess
        editor = os.environ.get("EDITOR", "nano")
        subprocess.call([editor, str(config_mgr.config_path)])
    else:
        typer.echo("Use --show to display config or --edit to edit it.")


@app.command("blueprint-list")
def blueprint_list():
    """List available blueprints."""
    mgr = _get_blueprint_manager()
    names = mgr.list()
    typer.echo("Available blueprints:")
    for name in names:
        typer.echo(f"  - {name}")


@app.command("blueprint-init")
def blueprint_init(
    name: str,
    from_template: str = typer.Option("simple-lxc", "--from", help="Base blueprint to copy from"),
):
    """Create a new user blueprint from a built-in template."""
    mgr = _get_blueprint_manager()
    mgr.init_from_template(name, from_template)
    typer.echo(f"[OK] Created blueprint '{name}' from '{from_template}'")
    typer.echo(f"Edit it at: ~/.ops/blueprints/{name}.yaml")


@app.command("blueprint-show")
def blueprint_show(name: str):
    """Show a blueprint with all defaults resolved."""
    mgr = _get_blueprint_manager()
    data = mgr.show(name)
    typer.echo(yaml.dump(data, default_flow_style=False, sort_keys=False))


@app.command("secrets-list")
def secrets_list(app_name: str):
    """List resolved secrets for an app (masked for security)."""
    config_mgr = ConfigManager()
    secret_mgr = SecretManager(config_mgr, app_name)
    secrets = secret_mgr.get_all_secrets()
    if not secrets:
        typer.echo("No secrets found for this app.")
        return
    typer.echo(f"Secrets for {app_name}:")
    for key, value in secrets.items():
        masked = value[:4] + "****" if len(value) > 4 else "****"
        typer.echo(f"  {key}: {masked}")


@app.command("secrets-rotate")
def secrets_rotate(
    app_name: str,
    secret_name: str,
    length: int = typer.Option(32, "--length", "-l", help="Length for generated secret"),
):
    """Regenerate a generated secret and restart the app service."""
    config_mgr = ConfigManager()
    secret_mgr = SecretManager(config_mgr, app_name)
    typer.echo(f"Rotating secret '{secret_name}' for {app_name}...")
    secret_mgr.rotate_secret(secret_name, length)

    # Update state file with new secret
    state_mgr = StateManager()
    state = state_mgr.load(app_name)
    if state:
        state.secrets_resolved[secret_name] = secret_mgr.get_all_secrets().get(secret_name, "")
        state_mgr.save(state)
        typer.echo(f"[OK] Secret '{secret_name}' rotated and state updated")
    else:
        typer.echo(f"[OK] Secret '{secret_name}' rotated")

    # Restart service to pick up new secret
    if state and state.vmid:
        try:
            blueprint_mgr = _get_blueprint_manager()
            blueprint = blueprint_mgr.load(app_name)
            orchestrator = _get_orchestrator()
            orchestrator.restart_service(app_name, blueprint)
            typer.echo(f"[OK] Service {app_name} restarted")
        except Exception as e:
            typer.echo(f"[WARN] Could not restart service: {e}", err=True)


@app.command("secrets-delete")
def secrets_delete(
    app_name: str,
    secret_name: Optional[str] = typer.Argument(None),
    all_secrets: bool = typer.Option(False, "--all", help="Delete all secrets for this app"),
):
    """Delete a secret or all secrets for an app."""
    config_mgr = ConfigManager()
    secret_mgr = SecretManager(config_mgr, app_name)

    if all_secrets:
        confirm = typer.confirm(f"Delete ALL secrets for '{app_name}'?")
        if not confirm:
            raise typer.Exit(0)
        secret_mgr.cleanup()
        typer.echo(f"[OK] All secrets for {app_name} deleted")
    elif secret_name:
        path = secret_mgr._secret_file(secret_name)
        if path.exists():
            path.unlink()
            typer.echo(f"[OK] Secret '{secret_name}' deleted")
        else:
            typer.echo(f"[WARN] Secret '{secret_name}' not found")
    else:
        typer.echo("Please provide a secret name or use --all")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
