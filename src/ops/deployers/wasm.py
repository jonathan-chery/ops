"""WebAssembly (Wasmtime) deployer."""

from typing import Dict

from ops.deployers.base import BaseDeployer
from ops.providers.proxmox import ProxmoxProvider
from ops.providers.wasm import WasmProvider
from ops.models.blueprint import AppBlueprint


class WasmDeployer(BaseDeployer):
    """Deploys workloads as .wasm modules using wasmtime."""

    def __init__(self):
        self.wasm = WasmProvider()
        self._last_result: Dict[str, str] = {}

    def deploy(
        self,
        proxmox: ProxmoxProvider,
        node: str,
        vmid: int,
        blueprint: AppBlueprint,
        env: Dict[str, str],
    ) -> None:
        wasm_cfg = blueprint.deployment.wasm
        if not wasm_cfg:
            raise RuntimeError("Wasm deployment config missing")

        artifact = wasm_cfg.artifact
        result = self.wasm.run(artifact, wasm_cfg, env)
        self._last_result = result
        if result["status"] != "ok":
            raise RuntimeError(f"Wasm execution failed: {result.get('stderr', '')}")

    def get_logs(
        self,
        proxmox: ProxmoxProvider,
        node: str,
        vmid: int,
        blueprint: AppBlueprint,
        follow: bool = False,
        lines: int = 100,
    ) -> str:
        return self._last_result.get("stdout", "")

    def restart_service(
        self,
        proxmox: ProxmoxProvider,
        node: str,
        vmid: int,
        blueprint: AppBlueprint,
    ) -> None:
        self.wasm.stop()
        self.deploy(proxmox, node, vmid, blueprint, {})

    def get_service_status(
        self,
        proxmox: ProxmoxProvider,
        node: str,
        vmid: int,
        blueprint: AppBlueprint,
    ) -> str:
        return self.wasm.get_status()
