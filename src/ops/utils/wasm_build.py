"""Wasm build toolchain integration."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List

from ops.models.blueprint import WasmDeploymentConfig


class WasmBuildToolchain:
    """Validates and invokes language-specific toolchains to compile
    source code into WebAssembly components.
    """

    TOOLS: Dict[str, List[str]] = {
        "rust": ["cargo", "rustup"],
        "go": ["tinygo", "go"],
        "python": ["componentize-py"],
        "node": ["jco"],
    }

    def __init__(self, runtime: str):
        self.runtime = runtime
        self.tools = self.TOOLS.get(runtime, [])

    def is_available(self) -> bool:
        """Check if all required tools for this runtime are in PATH."""
        return all(shutil.which(tool) for tool in self.tools)

    def build(
        self, source_dir: str, output_path: str, cfg: WasmDeploymentConfig
    ) -> None:
        """Invoke the appropriate toolchain to produce a .wasm artifact."""
        if not self.is_available():
            missing = [t for t in self.tools if not shutil.which(t)]
            raise RuntimeError(
                f"Missing toolchain tools for {self.runtime}: {missing}. "
                f"Please install them and ensure they are in PATH."
            )

        src = Path(source_dir)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        if self.runtime == "rust":
            self._build_rust(src, out, cfg)
        elif self.runtime == "go":
            self._build_go(src, out, cfg)
        elif self.runtime == "python":
            self._build_python(src, out, cfg)
        elif self.runtime == "node":
            self._build_node(src, out, cfg)
        else:
            raise ValueError(f"Unsupported Wasm runtime: {self.runtime}")

    def _build_rust(self, src: Path, out: Path, cfg: WasmDeploymentConfig) -> None:
        subprocess.run(
            ["rustup", "target", "add", "wasm32-wasip2"],
            cwd=str(src),
            check=True,
        )
        subprocess.run(
            ["cargo", "build", "--target", "wasm32-wasip2", "--release"],
            cwd=str(src),
            check=True,
        )
        # Copy artifact from target directory
        artifact = src / "target" / "wasm32-wasip2" / "release" / f"{src.name}.wasm"
        if not artifact.exists():
            # Fallback: find any .wasm in release directory
            wasm_files = list(
                (src / "target" / "wasm32-wasip2" / "release").glob("*.wasm")
            )
            if not wasm_files:
                raise RuntimeError("No .wasm artifact produced by cargo build")
            artifact = wasm_files[0]
        out.write_bytes(artifact.read_bytes())

    def _build_go(self, src: Path, out: Path, cfg: WasmDeploymentConfig) -> None:
        # Prefer TinyGo for Component Model support
        tinygo = shutil.which("tinygo")
        if tinygo:
            subprocess.run(
                [
                    "tinygo",
                    "build",
                    "-target=wasip2",
                    "-o",
                    str(out),
                ],
                cwd=str(src),
                check=True,
            )
        else:
            subprocess.run(
                ["go", "build", "-o", str(out)],
                cwd=str(src),
                env={**os.environ, "GOOS": "wasip1", "GOARCH": "wasm"},
                check=True,
            )

    def _build_python(self, src: Path, out: Path, cfg: WasmDeploymentConfig) -> None:
        subprocess.run(
            [
                "componentize-py",
                "--wit-path",
                str(src / "wit") if (src / "wit").exists() else str(src),
                "componentize",
                str(src),
                "-o",
                str(out),
            ],
            check=True,
        )

    def _build_node(self, src: Path, out: Path, cfg: WasmDeploymentConfig) -> None:
        entry = src / "index.js"
        if not entry.exists():
            entry = src / "main.js"
        if not entry.exists():
            raise FileNotFoundError(
                "No index.js or main.js found for Node/TS Wasm build"
            )
        subprocess.run(
            [
                "jco",
                "componentize",
                str(entry),
                "--out",
                str(out),
            ],
            cwd=str(src),
            check=True,
        )
