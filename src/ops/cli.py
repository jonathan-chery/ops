import typer
import json
import yaml
from typing import Optional, List

from ops.core.config import ConfigManager
from ops.core.blueprint import BlueprintManager
from ops.core.orchestrator import Orchestrator
from ops.core.state import StateManager
from ops.utils.secrets import SecretManager
from ops.utils.ssh import SSHOnboardManager
from ops.models.config import ProxmoxHostConfig
from ops import __version__

app = typer.Typer(
    help="Proxmox LXC Orchestrator CLI",
    add_completion=False,
)


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"ops {__version__}")
        raise typer.Exit(0)


@app.callback()
def callback(
    version: bool = typer.Option(
        False, "--version", callback=version_callback, is_eager=True
    ),
) -> None:
    """Proxmox LXC Orchestrator CLI."""
    pass


def _get_orchestrator() -> Orchestrator:
    config_mgr = ConfigManager()
    config = config_mgr.load()
    return Orchestrator(config)


def _get_blueprint_manager() -> BlueprintManager:
    return BlueprintManager()


@app.command()
def deploy(
    app_names: List[str] = typer.Argument(
        ..., help="One or more application names to deploy"
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Force redeploy even if already deployed"
    ),
    no_teardown_on_failure: bool = typer.Option(
        False, "--no-teardown-on-failure", help="Do not auto-teardown on failure"
    ),
    parallel: bool = typer.Option(
        True,
        "--parallel/--sequential",
        help="Run deployments in parallel or sequentially",
    ),
    cluster: bool = typer.Option(
        False, "--cluster", help="Deploy to the cluster (auto-placement)"
    ),
    cluster_transport: Optional[str] = typer.Option(
        None, "--cluster-transport", help="Override cluster transport (ssh|https)"
    ),
):
    """Deploy one or more applications based on their blueprints."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    blueprint_mgr = _get_blueprint_manager()
    orchestrator = _get_orchestrator()

    def _deploy_one(name):
        try:
            blueprint = blueprint_mgr.load(name)
            orchestrator.deploy(
                name,
                blueprint,
                force=force,
                no_teardown=no_teardown_on_failure,
                cluster=cluster,
                cluster_transport=cluster_transport,
            )
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
    skip_backup: bool = typer.Option(
        False, "--skip-backup", help="Skip backup before teardown"
    ),
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

        # MicroVM path
        if state.backend == "pve-microvm":
            blueprint_mgr = _get_blueprint_manager()
            blueprint = blueprint_mgr.load(app_name)
            microvm = _microvm_provider_for(orchestrator, blueprint)
            vm_status = microvm.get_vm_status(state.vmid)
            vm_ip = microvm.get_vm_ip(state.vmid) or state.ip
            typer.echo(f"App:        {app_name}")
            typer.echo(f"VMID:       {state.vmid}")
            typer.echo(f"Hostname:   {blueprint.container.hostname}")
            typer.echo(f"Status:     {vm_status}")
            typer.echo(f"IP:         {vm_ip}")
            typer.echo("Backend:    pve-microvm")
            return

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
                typer.echo(
                    f"{ct.vmid:<8} {ct.hostname or ct.name or '':<20} {ct.status:<10} {ip}"
                )


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
    root: bool = typer.Option(
        False, "--root", "-r", help="Run as root instead of app user"
    ),
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
    if (
        blueprint
        and blueprint.deployment.type == "native"
        and blueprint.deployment.native
    ):
        user = "root" if root else blueprint.deployment.native.app_user

    orchestrator = _get_orchestrator()
    result = orchestrator.proxmox.exec(state.vmid, command, user=user, node=state.node)
    if result.stdout:
        typer.echo(result.stdout)
    if result.stderr:
        typer.echo(result.stderr, err=True)
    raise typer.Exit(result.exit_code)


def _microvm_provider_for(orchestrator, blueprint):
    from ops.core.config import ConfigManager
    from ops.utils.secrets import SecretManager
    from ops.utils.ssh import SSHKeyManager
    from ops.providers.microvm import MicroVMProvider

    config_mgr = ConfigManager()
    secret_mgr = SecretManager(config_mgr, blueprint.name)
    ssh_mgr = SSHKeyManager(secret_mgr.secrets_dir)
    host = orchestrator._host_config
    return MicroVMProvider(
        hostname=host.host,
        username=host.user,
        port=host.port,
        private_key_path=ssh_mgr.get_private_key("root"),
    )


@app.command()
def start(app_name: str):
    """Start a container or microVM."""
    state_mgr = StateManager()
    state = state_mgr.load(app_name)
    if not state or not state.vmid:
        typer.echo(f"[WARN] No container found for {app_name}")
        raise typer.Exit(1)
    orchestrator = _get_orchestrator()
    if state.backend == "pve-microvm":
        blueprint_mgr = _get_blueprint_manager()
        blueprint = blueprint_mgr.load(app_name)
        microvm = _microvm_provider_for(orchestrator, blueprint)
        microvm.start_vm(state.vmid)
    else:
        orchestrator.proxmox.start_lxc(state.vmid, state.node)
    typer.echo(f"[OK] {app_name} started")


@app.command()
def stop(app_name: str):
    """Stop a container or microVM."""
    state_mgr = StateManager()
    state = state_mgr.load(app_name)
    if not state or not state.vmid:
        typer.echo(f"[WARN] No container found for {app_name}")
        raise typer.Exit(1)
    orchestrator = _get_orchestrator()
    if state.backend == "pve-microvm":
        blueprint_mgr = _get_blueprint_manager()
        blueprint = blueprint_mgr.load(app_name)
        microvm = _microvm_provider_for(orchestrator, blueprint)
        microvm.stop_vm(state.vmid)
    else:
        orchestrator.proxmox.stop_lxc(state.vmid, state.node)
    typer.echo(f"[OK] {app_name} stopped")


@app.command()
def restart(app_name: str):
    """Restart the application service inside the container or microVM."""
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
    state_map = {s.vmid: s for s in states}
    for ct in containers:
        if ct.vmid in managed_vmids:
            # Fallback to state IP if live API IP is None
            fallback_ip = state_map.get(ct.vmid, None)
            ip = ct.ip or (fallback_ip.ip if fallback_ip else None) or "N/A"
            typer.echo(
                f"{ct.vmid:<8} {ct.hostname or ct.name or '':<20} {ct.status:<10} {ip}"
            )


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
    from_template: str = typer.Option(
        "simple-lxc", "--from", help="Base blueprint to copy from"
    ),
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
    length: int = typer.Option(
        32, "--length", "-l", help="Length for generated secret"
    ),
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
        state.secrets_resolved[secret_name] = secret_mgr.get_all_secrets().get(
            secret_name, ""
        )
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
    all_secrets: bool = typer.Option(
        False, "--all", help="Delete all secrets for this app"
    ),
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


@app.command()
def onboard(
    host: Optional[str] = typer.Option(
        None, "--host", "-h", help="Hostname or IP of the target endpoint"
    ),
    name: Optional[str] = typer.Option(
        None, "--name", "-n", help="Short alias for this host (auto-derived if omitted)"
    ),
    user: str = typer.Option("root", "--user", "-u", help="SSH username"),
    port: int = typer.Option(22, "--port", "-p", help="SSH port"),
    password: Optional[str] = typer.Option(
        None, "--password", help="SSH password (interactive prompt if omitted)"
    ),
    type: Optional[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Endpoint type (proxmox, ssh, docker, kubernetes) — auto-detected if omitted",
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Re-onboard even if already onboarded"
    ),
    rotate_key: bool = typer.Option(
        False, "--rotate-key", help="Rotate the ops SSH key and re-onboard all hosts"
    ),
):
    """Onboard a remote endpoint by establishing SSH key-based authentication."""
    config_mgr = ConfigManager()
    onboard_mgr = SSHOnboardManager(config_mgr.ssh_dir)

    # --- Key rotation flow ---
    if rotate_key:
        config = config_mgr.load()
        if not config.hosts:
            typer.echo("[ERROR] No hosts configured. Nothing to rotate.", err=True)
            raise typer.Exit(1)
        typer.echo("[INFO] Rotating ops SSH key...")
        success, msg = onboard_mgr.rotate_key_for_all_hosts(config.hosts)
        if success:
            for h in config.hosts:
                h.ssh_onboarded = True
            config_mgr.save(config)
            typer.echo(f"[OK] {msg}")
        else:
            typer.echo(f"[ERROR] Key rotation failed: {msg}", err=True)
            raise typer.Exit(1)
        return

    config = config_mgr.load()

    # --- Normal onboard flow ---
    if not host:
        if config.hosts:
            typer.echo("Existing hosts:")
            for h in config.hosts:
                status = "onboarded" if h.ssh_onboarded else "not onboarded"
                typer.echo(f"  - {h.name} ({h.host}) [{status}]")
        host = typer.prompt("Enter hostname or IP of the endpoint to onboard")

    # At this point host is guaranteed str
    assert host is not None  # type: ignore

    # Auto-derive name from host if not provided
    if not name:
        name = host.split(".")[0].split(":")[0]

    # Try to fetch saved password from the existing host entry if no CLI flag given
    candidate_password = password
    if candidate_password is None:
        for h in config.hosts:
            if h.name == name or h.host == host:
                if h.password:
                    candidate_password = h.password
                    typer.echo("    [INFO] Using saved password from config")
                break

    # Auto-detect type if not provided
    detected_type = type
    if not detected_type:
        typer.echo("    [INFO] Detecting endpoint type...")
        detected_type = onboard_mgr.discover_endpoint_type(host)
        if detected_type == "unknown":
            detected_type = typer.prompt(
                "Could not auto-detect endpoint type. Enter type",
                default="proxmox",
            )
        typer.echo(f"    [INFO] Detected type: {detected_type}")

    # Onboard via SSH
    typer.echo(f"--> [ONBOARD] {user}@{host} (type={detected_type})")
    if not force:
        existing = onboard_mgr._test_ssh_key(host, user, port)
        if existing:
            existing.close()
            typer.echo("    [INFO] Already onboarded (key auth works)")
            known = [h for h in config.hosts if h.name == name or h.host == host]
            if not known:
                config.hosts.append(
                    ProxmoxHostConfig(
                        name=name,
                        type=detected_type,
                        host=host,
                        port=port,
                        user=user,
                        ssh_onboarded=True,
                    )
                )
                config_mgr.save(config)
                typer.echo(f"    [OK] Added '{name}' to config")
            return

    success, msg = onboard_mgr.onboard_host(
        host, user, port, password=candidate_password, force=force
    )
    if success:
        typer.echo(f"    [OK] {msg}")
        known = [h for h in config.hosts if h.name == name or h.host == host]
        if known:
            known[0].name = name
            known[0].type = detected_type
            known[0].host = host
            known[0].port = port
            known[0].user = user
            known[0].ssh_onboarded = True
        else:
            config.hosts.append(
                ProxmoxHostConfig(
                    name=name,
                    type=detected_type,
                    host=host,
                    port=port,
                    user=user,
                    ssh_onboarded=True,
                )
            )
        # If user typed a password interactively that wasn't already saved, persist it
        # (encrypted by ConfigManager.save)
        if candidate_password and not any(
            h.password == candidate_password
            for h in config.hosts
            if (h.name == name or h.host == host)
        ):
            for h in config.hosts:
                if h.name == name or h.host == host:
                    h.password = candidate_password
                    typer.echo("    [INFO] Password saved to config (encrypted)")
                    break
        config_mgr.save(config)
        typer.echo("    [OK] Updated ~/.ops/config.yaml")
    else:
        typer.echo(f"    [ERROR] {msg}", err=True)
        raise typer.Exit(1)


@app.command()
def build(
    app_name: str,
    source_dir: Optional[str] = typer.Option(
        ".", "--source", "-s", help="Source directory containing the application code"
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="Output path for the .wasm artifact"
    ),
):
    """Compile source code into a WebAssembly artifact."""
    blueprint_mgr = _get_blueprint_manager()
    try:
        blueprint = blueprint_mgr.load(app_name)
    except FileNotFoundError:
        typer.echo(f"[ERROR] Blueprint '{app_name}' not found", err=True)
        raise typer.Exit(1)

    if blueprint.deployment.type != "wasm":
        typer.echo(
            f"[ERROR] Deployment type is '{blueprint.deployment.type}', not 'wasm'",
            err=True,
        )
        raise typer.Exit(1)

    wasm_cfg = blueprint.deployment.wasm
    if not wasm_cfg:
        typer.echo("[ERROR] Wasm deployment config missing", err=True)
        raise typer.Exit(1)

    from ops.utils.wasm_build import WasmBuildToolchain

    toolchain = WasmBuildToolchain(wasm_cfg.runtime)
    if not toolchain.is_available():
        typer.echo(
            f"[ERROR] Missing toolchain for {wasm_cfg.runtime}. "
            f"Ensure the required tools are installed and in PATH.",
            err=True,
        )
        raise typer.Exit(1)

    out_path = output or wasm_cfg.artifact
    src_dir = source_dir or "."
    typer.echo(f"[INFO] Building {app_name} ({wasm_cfg.runtime}) -> {out_path}")
    try:
        toolchain.build(src_dir, out_path, wasm_cfg)
        typer.echo(f"[OK] Build complete: {out_path}")
    except Exception as e:
        typer.echo(f"[ERROR] Build failed: {e}", err=True)
        raise typer.Exit(1)


@app.command("cluster-join")
def cluster_join(
    token: Optional[str] = typer.Option(
        None, "--token", help="Shared cluster secret (will prompt if omitted)"
    ),
    transport: Optional[str] = typer.Option(
        None, "--transport", help="Override cluster transport (ssh|https)"
    ),
):
    """Join this node to an ad-hoc cluster."""
    from ops.cluster.discovery import DiscoveryService

    config_mgr = ConfigManager()
    config = config_mgr.load()

    if not token:
        token = typer.prompt("Enter cluster shared secret", hide_input=True)

    if not config.cluster.enabled:
        config.cluster.enabled = True
        config.cluster.secret = token
        if transport:
            config.cluster.transport = transport  # type: ignore[assignment]
        config_mgr.save(config)
        typer.echo("[OK] Cluster mode enabled")

    discovery = DiscoveryService(config.cluster)
    discovery.send_beacon(advertise_port=config.cluster.api_port)
    typer.echo("[OK] Join beacon sent")


@app.command("cluster-leave")
def cluster_leave(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Gracefully leave the cluster."""

    if not yes:
        confirm = typer.confirm("Leave the cluster and clear local node registry?")
        if not confirm:
            typer.echo("Aborted.")
            raise typer.Exit(0)

    config_mgr = ConfigManager()
    config = config_mgr.load()

    # Remove this node from the cluster registry
    from ops.cluster.registry import NodeRegistry
    from ops.cluster.discovery import DiscoveryService

    discovery = DiscoveryService(config.cluster)
    node_id = discovery.node_id
    registry = NodeRegistry()
    removed = registry.remove(node_id)
    if removed:
        typer.echo(f"[INFO] Removed node {node_id} from cluster registry")

    config.cluster.enabled = False
    config.cluster.secret = None
    config_mgr.save(config)
    typer.echo("[OK] Left cluster")


@app.command("cluster-status")
def cluster_status():
    """Show all discovered nodes and their health."""
    from ops.cluster.registry import NodeRegistry

    registry = NodeRegistry()
    nodes = registry.list_active()
    if not nodes:
        typer.echo("No active cluster nodes found.")
        return

    typer.echo(
        f"{'Node ID':<36} {'Name':<20} {'Host':<16} {'Status':<10} {'Transport'}"
    )
    typer.echo("-" * 90)
    for n in nodes:
        typer.echo(
            f"{n.node_id:<36} {n.name:<20} {n.host:<16} {n.status:<10} {n.transport}"
        )


@app.command("events")
def events(
    app: Optional[str] = typer.Option(None, "--app", "-a", help="Filter by app name"),
    status: Optional[str] = typer.Option(
        None, "--status", "-s", help="Filter by status"
    ),
    since: Optional[str] = typer.Option(None, "--since", help="ISO-8601 timestamp"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow new events"),
    tail: Optional[int] = typer.Option(
        None, "--tail", "-n", help="Number of events to show"
    ),
):
    """Tail or query the audit log."""
    from ops.core.audit import AuditLogger

    logger = AuditLogger()
    if follow:
        for event in logger.follow_events(app=app, status=status):
            typer.echo(json.dumps(event))
    else:
        results = logger.read_events(app=app, status=status, since=since, tail=tail)
        for event in results:
            typer.echo(json.dumps(event))


@app.command("metrics")
def metrics_cmd(
    app_name: str = typer.Argument(..., help="Application name"),
    raw: bool = typer.Option(False, "--raw", help="Show raw Prometheus exposition"),
):
    """Fetch metrics from the application's node_exporter sidecar."""
    import requests

    state_mgr = StateManager()
    state = state_mgr.load(app_name)
    if not state or not state.vmid:
        typer.echo(f"[WARN] No container found for {app_name}")
        raise typer.Exit(1)

    blueprint_mgr = _get_blueprint_manager()
    blueprint = blueprint_mgr.load(app_name)
    scrape_port = blueprint.metrics.scrape_port if blueprint.metrics else 9100
    url = f"http://{state.ip}:{scrape_port}/metrics"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        typer.echo(f"[ERROR] Could not fetch metrics: {e}", err=True)
        raise typer.Exit(1)

    if raw:
        typer.echo(response.text)
    else:
        # Simple human-readable summary
        lines = response.text.splitlines()
        for line in lines:
            if line.startswith("#"):
                continue
            if "node_" in line and "_total" not in line:
                typer.echo(line)


@app.command("watch")
def watch(
    app_name: str,
    interval: int = typer.Option(30, "--interval", "-i", help="Seconds between checks"),
    exit_on_failure: bool = typer.Option(
        False, "--exit-on-failure", help="Exit after first failure"
    ),
):
    """Continuously monitor an application and alert on health-check failure."""
    import signal
    import time

    state_mgr = StateManager()
    state = state_mgr.load(app_name)
    if not state or not state.vmid:
        typer.echo(f"[WARN] No container found for {app_name}")
        raise typer.Exit(1)

    blueprint_mgr = _get_blueprint_manager()
    blueprint = blueprint_mgr.load(app_name)
    orchestrator = _get_orchestrator()

    running = True

    def _handle_sigint(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _handle_sigint)
    signal.signal(signal.SIGTERM, _handle_sigint)

    typer.echo(f"[INFO] Watching {app_name} every {interval}s (Ctrl+C to stop)")
    while running:
        health = orchestrator.hb_mgr.run_health_check(
            blueprint, state.vmid, str(state.ip), orchestrator.proxmox, state.node
        )
        if health.get("status") == "ok":
            typer.echo(f"[OK] {app_name} healthy")
        elif health.get("status") == "skipped":
            typer.echo(f"[INFO] {app_name} health check skipped")
        else:
            typer.echo(f"[WARN] {app_name} unhealthy: {health.get('error')}")
            if exit_on_failure:
                raise typer.Exit(1)
        time.sleep(interval)

    typer.echo("[INFO] Watch stopped.")


@app.command("alerts-test")
def alerts_test():
    """Send a test alert to verify webhook configuration."""
    from ops.core.alerts import AlertManager
    from ops.core.config import ConfigManager

    config_mgr = ConfigManager()
    config = config_mgr.load()
    alert_mgr = AlertManager(
        webhook_url=config.alerting.webhook_url,
        cooldown_seconds=config.alerting.cooldown_seconds,
    )
    if alert_mgr.test_alert():
        typer.echo("[OK] Test alert sent successfully")
    else:
        typer.echo("[ERROR] Test alert failed (check webhook_url)", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
