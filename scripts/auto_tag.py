#!/usr/bin/env python3
"""Auto-bump semantic version from conventional commits and create a release tag.

Reads conventional commits since the last ``v*`` tag, determines the next
semantic version, updates ``src/ops/__init__.py`` and ``pyproject.toml``,
commits the changes, and pushes a lightweight tag ``vX.Y.Z``.

Commit-message prefixes determine the bump level:
- ``feat!:`` or ``BREAKING CHANGE:`` in body → major
- ``feat:`` → minor
- ``fix:``, ``docs:``, ``style:``, ``refactor:``, ``perf:``, ``test:``, ``chore:`` → patch
- ``ci:``, ``build:`` alone (no feat/fix) → patch
- No conventional commits found → exit 0 (nothing to release)

Usage
-----
    python scripts/auto_tag.py [--dry-run]

Environment variables
---------------------
    GITHUB_REPOSITORY : str
        ``owner/repo`` target for release metadata. Defaults to ``jonathan-chery/ops``.

"""

import argparse
import re
import subprocess
from pathlib import Path


DEFAULT_REPO = "jonathan-chery/ops"


def _run(cmd: list[str], check: bool = True) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, check=check)
    return result.stdout.strip()


def _last_tag() -> str | None:
    try:
        return _run(["git", "describe", "--tags", "--abbrev=0"])
    except subprocess.CalledProcessError:
        return None


def _commits_since(tag: str | None) -> list[dict]:
    if tag:
        range_spec = f"{tag}..HEAD"
    else:
        range_spec = "HEAD"
    raw = _run(["git", "log", range_spec, "--format=%H|%s|%b%x00"], check=False)
    if not raw:
        return []
    commits = []
    for entry in raw.split("\x00"):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split("|", 2)
        if len(parts) < 2:
            continue
        commit_hash, subject = parts[0], parts[1]
        body = parts[2] if len(parts) > 2 else ""
        commits.append({"hash": commit_hash, "subject": subject, "body": body})
    return commits


def _bump_level(commits: list[dict]) -> str | None:
    major = minor = patch = False
    for c in commits:
        subj = c["subject"]
        body = c["body"]
        if (
            subj.startswith("feat!")
            or subj.startswith("fix!")
            or "BREAKING CHANGE:" in body
        ):
            major = True
        elif subj.startswith("feat:"):
            minor = True
        elif any(
            subj.startswith(p)
            for p in (
                "fix:",
                "docs:",
                "style:",
                "refactor:",
                "perf:",
                "test:",
                "chore:",
                "ci:",
                "build:",
            )
        ):
            patch = True
    if major:
        return "major"
    if minor:
        return "minor"
    if patch:
        return "patch"
    return None


def _parse_version(tag: str | None) -> tuple[int, int, int]:
    if tag is None:
        return (0, 1, 0)
    m = re.match(r"^v(\d+)\.(\d+)\.(\d+)$", tag)
    if not m:
        raise RuntimeError(f"Cannot parse version from tag: {tag}")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _next_version(current: tuple[int, int, int], level: str) -> tuple[int, int, int]:
    major, minor, patch = current
    if level == "major":
        return (major + 1, 0, 0)
    if level == "minor":
        return (major, minor + 1, 0)
    return (major, minor, patch + 1)


def _update_version_file(new_version: str) -> None:
    init_path = Path("src/ops/__init__.py")
    content = init_path.read_text()
    content = re.sub(
        r'^__version__\s*=\s*"[^"]+"',
        f'__version__ = "{new_version}"',
        content,
        flags=re.MULTILINE,
    )
    init_path.write_text(content)

    pyproject_path = Path("pyproject.toml")
    content = pyproject_path.read_text()
    content = re.sub(
        r'^version\s*=\s*"[^"]+"',
        f'version = "{new_version}"',
        content,
        flags=re.MULTILINE,
    )
    pyproject_path.write_text(content)


def _update_changelog(new_version: str, commits: list[dict]) -> None:
    changelog_path = Path("CHANGELOG.md")
    sections: dict[str, list[str]] = {
        "Added": [],
        "Changed": [],
        "Deprecated": [],
        "Removed": [],
        "Fixed": [],
        "Security": [],
    }
    for c in commits:
        subj = c["subject"]
        if (
            any(subj.startswith(p) for p in ("feat!", "fix!"))
            or "BREAKING CHANGE:" in c["body"]
        ):
            sections["Changed"].append(f"- {subj}")
        elif subj.startswith("feat:"):
            sections["Added"].append(f"- {subj}")
        elif subj.startswith("fix:"):
            sections["Fixed"].append(f"- {subj}")
        elif subj.startswith("docs:"):
            sections["Changed"].append(f"- {subj}")
        elif (
            subj.startswith("chore:")
            or subj.startswith("ci:")
            or subj.startswith("build:")
        ):
            sections["Changed"].append(f"- {subj}")
        elif subj.startswith("refactor:") or subj.startswith("perf:"):
            sections["Changed"].append(f"- {subj}")
        elif subj.startswith("test:"):
            sections["Changed"].append(f"- {subj}")
        elif subj.startswith("style:"):
            sections["Changed"].append(f"- {subj}")
        else:
            sections["Changed"].append(f"- {subj}")
    lines = [f"## [{new_version}]", ""]
    for title, items in sections.items():
        if items:
            lines.append(f"### {title}")
            lines.extend(items)
            lines.append("")
    if not changelog_path.exists():
        header = "# Changelog\n\nAll notable changes to this project will be documented in this file.\n\n"
        changelog_path.write_text(header + "\n".join(lines))
    else:
        existing = changelog_path.read_text()
        changelog_path.write_text(
            existing.replace("\n# ", "\n" + "\n".join(lines) + "\n# ", 1)
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-tag semantic version")
    parser.add_argument(
        "--dry-run", action="store_true", help="Compute but do not apply"
    )
    args = parser.parse_args()

    # Prevent recursion: if HEAD is already tagged, nothing to do
    try:
        _run(["git", "describe", "--tags", "--exact-match", "HEAD"])
        print("[INFO] HEAD is already tagged. Skipping auto-tag.")
        return 0
    except subprocess.CalledProcessError:
        pass

    last_tag = _last_tag()
    commits = _commits_since(last_tag)
    if not commits:
        print("[INFO] No commits since last tag. Nothing to release.")
        return 0

    level = _bump_level(commits)
    if level is None:
        print("[INFO] No conventional commits found. Skipping auto-tag.")
        return 0

    current = _parse_version(last_tag)
    next_ver_tuple = _next_version(current, level)
    new_version = f"{next_ver_tuple[0]}.{next_ver_tuple[1]}.{next_ver_tuple[2]}"
    new_tag = f"v{new_version}"

    print(f"[INFO] Last tag: {last_tag or '(none)'}")
    print(f"[INFO] Bump level: {level}")
    print(f"[INFO] Next version: {new_version}")
    print(f"[INFO] New tag: {new_tag}")

    if args.dry_run:
        print("[DRY-RUN] Would update version files, changelog, commit, and tag")
        return 0

    _update_version_file(new_version)
    _update_changelog(new_version, commits)

    _run(["git", "add", "src/ops/__init__.py", "pyproject.toml", "CHANGELOG.md"])
    _run(["git", "commit", "-m", f"chore(release): v{new_version} [skip ci]"])
    _run(["git", "tag", new_tag])
    _run(["git", "push", "origin", "HEAD"])
    _run(["git", "push", "origin", new_tag])

    print(f"[OK] Tagged and pushed {new_tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
