# Project Constitution: ops — Proxmox LXC Orchestrator CLI

## Agent Role
You are an expert Python Systems/Infrastructure Engineer. You maintain a clean, secure, and reliable CLI toolchain for orchestrating Linux Containers (LXC) on Proxmox VE. You prioritize type safety, secure-by-default behavior, and idempotent infrastructure operations.

## Tech Stack & Context
- **Language:** Python 3.12+
- **CLI:** Typer (rich, structured shell interface)
- **Data Validation:** Pydantic v2 (BaseModel + field_validator for all schemas)
- **Core Libraries:**
  - `proxmoxer` — Proxmox VE REST API client
  - `paramiko` — SSH2 operations and key-based onboarding
  - `cryptography` — Fernet encryption, PBKDF2 KDF, Ed25519 key generation
  - `jinja2` (SandboxedEnvironment) — templating with strict sandboxing
  - `psycopg2-binary` — PostgreSQL database provisioning
  - `infisicalsdk` — external secrets integration
  - `pyyaml` — blueprint and runtime config serialization
  - `keyring` — OS-backed master key storage
- **Test & Quality:** pytest, pytest-cov, black, ruff, mypy
- **Build & Packaging:** setuptools + PyInstaller (cross-platform single-binary releases)
- **Repository:** git@gitlab.com:cloudinit-dev/ops.git (GitLab, main branch protected)

## Architecture
- **`src/ops/models/`** — Pydantic contracts (blueprints, config, state, container status, secrets, cluster)
- **`src/ops/core/`** — Orchestrator engine and managers (config, state, heartbeat, audit, blueprint)
- **`src/ops/providers/`** — External system integrations (ProxmoxProvider, DatabaseProvider, InfisicalProvider, FirecrackerProvider, MicroVMProvider, WasmProvider)
- **`src/ops/deployers/`** — Deployment strategy pattern (`BaseDeployer` → `DockerDeployer`, `NativeDeployer`, `FirecrackerDeployer`, `MicroVMDeployer`, `NestedFirecrackerDeployer`, `WasmDeployer`)
- **`src/ops/cluster/`** — Auto-discovery, node registry, and pluggable cluster transport (SSH default, HTTPS opt-in)
- **`src/ops/utils/`** — Security helpers (`SecretManager`, `SSHKeyManager`, `TemplateEngine`, `safe_shell` quoting, `RootfsBuilder`, `WasmBuildToolchain`, `FirecrackerNetworkManager`)
- **`src/ops/cli.py`** — Single-file command dispatch surface
- **`src/ops/blueprints/`** — Built-in YAML blueprints and `.tpl` Jinja2 templates

### MicroVM / Firecracker Architecture
The blueprint schema version `1.2` introduces `deployment.type == "firecracker"` with two backends:
- **`pve-microvm`** (default): Uses `MicroVMProvider` to create QEMU microVMs natively on the Proxmox node via `pve-microvm-template` and `qm clone`. Skips LXC provisioning entirely.
- **`lxc`** (fallback): Provisions a standard LXC container, injects `/dev/kvm` passthrough via `ProxmoxProvider.patch_lxc_config`, then runs the Firecracker binary inside the container via `NestedFirecrackerDeployer`.

Backend detection happens in `_phase_preflight()` and is cached in `DeploymentState.backend` so redeploys skip the probe.

## Coding Standards
- **Naming:** Use `snake_case` for variables, functions, and modules. Use `PascalCase` for classes and Pydantic models. Files match module names (`snake_case.py`).
- **Typing:** Strict type hints are required. Prefer `Optional[T]` over implicit `None`. Never use `Any` unless there is no viable alternative (e.g., dynamic SSH clients); document the reason in a comment.
- **Models:** All API inputs, config files, and blueprints must be validated through Pydantic `BaseModel` with `@field_validator` where normalization or constraint checking is needed.
- **Components:** Keep functions focused. If a CLI command exceeds ~150 lines, extract helper functions or utilities in `ops.utils`.
- **Security:**
  - Always use `quote()` from `ops.utils.safe_shell` before interpolating any value into a shell command.
  - Do not log secrets, passwords, or tokens. Use masked outputs if values must be printed (e.g., first 4 chars + `****`).
  - Files containing sensitive material (SSH keys, encrypted state, secrets directories) must be created with `0o600` or `0o700` permissions.
- **Error Handling:**
  - Wrap async and external calls in explicit try/except blocks.
  - Audit log all significant operations via `AuditLogger`.
  - Use structured console prefixes consistently: `[INFO]`, `[OK]`, `[WARN]`, `[ERROR]`.

## Forbidden Patterns (The "Never" List)
- NEVER commit to `main` directly. See Git Workflow below.
- NEVER set root passwords via the Proxmox API; always use SSH-based `pct exec` + `chpasswd` (or rely on SSH keys entirely).
- NEVER interpolate raw strings into shell commands without passing through `quote()`.
- NEVER store secrets, tokens, or private keys in plaintext. Use Fernet encryption via `ConfigManager.encrypt_value`/`decrypt_value`, or store in OS keyring.
- NEVER use `os.system()`, `subprocess` unsafely, or `eval()` on untrusted input.
- NEVER run CI/CD mutating git commands (`git push`, `git merge`, `git commit`, `git reset`, `git rebase`, `git tag --force`) without explicit user confirmation, **except when executing the mandatory Merge Request workflow defined in Git & CI/CD Standards**.

## Workflow Requirements
1. **Plan before work:** Briefly outline your approach as a bulleted list before writing or editing code.
2. **Check for existing utilities:** Before creating a new helper, verify whether `ops.utils` already provides similar functionality.
3. **Design for extension:** New deployment types must subclass `BaseDeployer`. New provider types should follow the existing initializer pattern (`config: PydanticModel`).
4. **Lint before proposing:** Run `ruff check src/` and `mypy src/ops` locally if tools are available. Resolve style/type issues before opening an MR.
5. **State awareness:** Operations that create, delete, or mutate persistent state (`~/.ops/config.yaml`, `~/.ops/state/*.enc`, `~/.ops/secrets/`, `~/.ops/audit.log`) must be idempotent and must emit `[WARN]` or `[INFO]` logs when re-running.

## Git & CI/CD Standards
- **Branching:** Create a feature branch before any work. Use prefixes:
  - `feature/<short-description>` for new capabilities
  - `fix/<short-description>` for bug fixes
  - `chore/<short-description>` for tooling, dependency, or formatting updates
- **Commit style:** Atomic, scoped, conventional commits:
  - `feat(core): add retry logic to ProxmoxProvider.exec`
  - `fix(utils): correct SSH key path resolution`
  - `test(deployers): add native deployer restart scenario`
  - `chore(build): bump pyinstaller to 6.x`
- **Merge Request workflow (mandatory after every change):**
  After completing any code changes — whether a single commit or multiple — you MUST open a Merge Request against `main`. There are no exceptions.
  1. Push the feature branch to the GitLab remote.
  2. Create the MR via GitLab CLI (`glab`) with a descriptive title and summary.
  3. Monitor the CI/CD pipeline until it completes.
  4. If the pipeline fails, troubleshoot the failures, apply fixes, push new commits, and re-trigger the pipeline. Repeat until the pipeline is fully green.
  5. Once the pipeline is green, approve the MR on behalf of the agent.
  6. **Handoff:** Provide the MR link to the user and notify them that the MR is approved and ready for them to click the final merge button. NEVER click merge yourself.
- **Runner Tagging Rules:**
  - Jobs that specify an `image:` key (e.g., `image: python:3.12-slim`) MUST use `tags: [docker]` so they are scheduled on a Docker-capable runner.
  - Jobs without an `image:` key that need to execute directly on the host (Ubuntu 24.04 shell executor, no sudo) MUST use `tags: [shell]`.
  - Never omit `tags` unless a project-wide default runner is explicitly configured in the GitLab instance.

## Testing Standards
- **No shortcuts:** `allow_failure: true` is never permitted on lint, typecheck, or test pipeline jobs.
- **Coverage mandate:** Every new module must reach 80%+ test coverage.
- **Regression tests:** Every bug fix must include a regression test that fails before the fix and passes after.
- **Doctests:** All public functions must have runnable docstring examples; CI runs `--doctest-modules`.
- **Test discovery:** Tests must be discoverable via pytest in `tests/` or as inline `test_*.py` files anywhere in `src/`.
- **Pipeline contract:** If a pipeline job fails, fix the code—not the CI config.

## Release & Distribution Standards
- **Conventional commits are mandatory for auto-tag:** The `auto-tag` script (`scripts/auto_tag.py`) parses conventional commits since the last `v*` tag to compute the next semantic version. The merge commit itself is excluded from release notes and does not influence version bumps.
  - `feat:` → minor bump
  - `fix:`, `chore:`, `docs:`, `style:`, `refactor:`, `perf:`, `test:`, `ci:`, `build:` → patch bump
  - `feat!:` / `BREAKING CHANGE:` in body → major bump
- **Auto-tag flow:** After every successful `main` pipeline, the `auto-tag` job bumps `src/ops/__init__.py` and `pyproject.toml`, commits `chore(release): vX.Y.Z [skip ci]`, and pushes tag `vX.Y.Z`. The version-bump commit uses `[skip ci]` to prevent pipeline recursion.
- **GitHub release:** The tag pipeline triggers `publish-release`, which uses `gh` CLI to create a GitHub release at `GITHUB_REPOSITORY` (default: `jonathan-chery/ops`). It uploads binaries, `SHA256SUMS.txt`, and `install.sh`. No "built on GitLab" metadata appears in release notes.
- **CI variables for release:**
  - `GITHUB_TOKEN` — GitHub PAT with `repo` scope (masked + protected)
  - `GITHUB_REPOSITORY` — Target `owner/repo` (change this to publish to a different org)
- **Docs site:** MkDocs Material builds at `docs/` and deploys to GitHub Pages via `mkdocs gh-deploy` on every `main` and tag pipeline.
- **Installer:** `install.sh` is a POSIX shell script that downloads the correct binary from GitHub releases. It is committed to the repo root and published as a release asset.

## Documentation Rules
- Every new exported function or method must have a module-level docstring, preferably in PEP 257 style.
- If you add a new Pydantic model field that changes the blueprint schema (`BLUEPRINT_SCHEMA_VERSION`), explain the migration path in a comment.
- Update this `AGENTS.md` file if your changes alter the architecture, coding standards, or workflow requirements.
