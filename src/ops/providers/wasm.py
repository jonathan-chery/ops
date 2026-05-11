"""Wasmtime WebAssembly runtime provider."""

import os
from pathlib import Path
from typing import Dict, Optional, Any

from ops.models.blueprint import WasmDeploymentConfig


class WasmProvider:
    """Embedded Wasmtime runtime for running .wasm components locally.

    Uses the official `wasmtime` PyPI package to load and execute
    WebAssembly modules with WASI capabilities.
    """

    def __init__(self):
        try:
            import wasmtime  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "wasmtime package not installed. Run: pip install wasmtime"
            ) from exc
        self._wasmtime = wasmtime
        self._store: Optional[Any] = None
        self._instance: Optional[Any] = None

    def _build_wasi_config(self, cfg: WasmDeploymentConfig, env: Dict[str, str]) -> Any:
        """Construct a WasiConfig from blueprint directives."""
        wasi = self._wasmtime.WasiConfig()
        # Environment variables
        for k, v in env.items():
            wasi.set_env(k, v)
        # Pre-opened directories
        for d in cfg.wasi_dirs:
            abs_d = os.path.abspath(d)
            if not os.path.exists(abs_d):
                raise FileNotFoundError(f"WASI directory not found: {abs_d}")
            wasi.preopen_dir(abs_d, os.path.basename(abs_d))
        # Network
        if not cfg.wasi_network:
            # Deny network access by default
            pass  # wasmtime WasiConfig defaults to no network
        return wasi

    def run(
        self, artifact_path: str, cfg: WasmDeploymentConfig, env: Dict[str, str]
    ) -> Dict[str, Any]:
        """Load and run a .wasm artifact, returning stdout/stderr/exit info."""
        path = Path(artifact_path)
        if not path.exists():
            raise FileNotFoundError(f"Wasm artifact not found: {artifact_path}")

        engine = self._wasmtime.Engine()
        store = self._wasmtime.Store(engine)
        self._store = store

        # WASI configuration
        wasi_config = self._build_wasi_config(cfg, env)
        store.set_wasi(wasi_config)

        # Load module
        module = self._wasmtime.Module.from_file(store.engine, str(path))

        # Link WASI
        linker = self._wasmtime.Linker(store.engine)
        linker.define_wasi()

        # Instantiate
        instance = linker.instantiate(store, module)
        self._instance = instance

        # Run main function if present
        stdout_buffer: list[str] = []
        stderr_buffer: list[str] = []
        exit_code = 0
        try:
            # Find and call the default export (often `_start` or `run`)
            func = instance.exports(store).get("_start") or instance.exports(store).get(
                "run"
            )
            if func is None:
                # If no explicit start, try to get any callable export
                for name, item in instance.exports(store).items():
                    if callable(item):
                        func = item
                        break
            if func:
                func(store)
        except Exception as e:
            stderr_buffer.append(str(e))
            exit_code = 1

        return {
            "stdout": "".join(stdout_buffer),
            "stderr": "".join(stderr_buffer),
            "exit_code": exit_code,
            "status": "ok" if exit_code == 0 else "failed",
        }

    def get_status(self) -> str:
        """Return the runtime status of the current instance."""
        if self._instance is None:
            return "stopped"
        return "running"

    def stop(self) -> None:
        """Drop the store and instance references."""
        self._instance = None
        self._store = None
