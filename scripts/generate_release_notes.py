#!/usr/bin/env python3
"""Generate GitHub release notes from conventional commits.

Parses commits since the last ``v*`` tag, groups them by type, and outputs
Markdown suitable for a GitHub release body. Merge commits (any commit with
multiple parents) and ``chore(release)`` commits are excluded.

Usage
-----
    python scripts/generate_release_notes.py [--since TAG]

Environment variables
---------------------
    GITHUB_REPOSITORY : str
        ``owner/repo`` target. Defaults to ``jonathan-chery/ops``.

"""

import argparse
import subprocess


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
    # %P = parent hashes (space-separated); merge commits have >1 parent
    raw = _run(["git", "log", range_spec, "--format=%H|%P|%s|%b%x00"], check=False)
    if not raw:
        return []
    commits = []
    for entry in raw.split("\x00"):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split("|", 3)
        if len(parts) < 3:
            continue
        commit_hash, parents, subject = parts[0], parts[1], parts[2]
        body = parts[3] if len(parts) > 3 else ""
        if len(parents.split()) > 1:
            continue  # Skip merge commits
        if "chore(release):" in subject:
            continue
        commits.append({"hash": commit_hash, "subject": subject, "body": body})
    return commits


def _categorize(commits: list[dict]) -> dict[str, list[str]]:
    cats: dict[str, list[str]] = {
        "Features": [],
        "Bug Fixes": [],
        "Documentation": [],
        "Performance": [],
        "Refactoring": [],
        "Testing": [],
        "Chores": [],
        "Other": [],
    }
    for c in commits:
        subj = c["subject"]
        if subj.startswith("feat:") or subj.startswith("feat("):
            cats["Features"].append(subj)
        elif subj.startswith("fix:") or subj.startswith("fix("):
            cats["Bug Fixes"].append(subj)
        elif subj.startswith("docs:") or subj.startswith("docs("):
            cats["Documentation"].append(subj)
        elif subj.startswith("perf:") or subj.startswith("perf("):
            cats["Performance"].append(subj)
        elif subj.startswith("refactor:") or subj.startswith("refactor("):
            cats["Refactoring"].append(subj)
        elif subj.startswith("test:") or subj.startswith("test("):
            cats["Testing"].append(subj)
        elif any(
            subj.startswith(p) or subj.startswith(p + "(")
            for p in ("chore", "ci", "build", "style")
        ):
            cats["Chores"].append(subj)
        else:
            cats["Other"].append(subj)
    return cats


def generate_notes(tag: str | None, commits: list[dict]) -> str:
    cats = _categorize(commits)
    lines: list[str] = []
    for title, items in cats.items():
        if not items:
            continue
        lines.append(f"## {title}")
        for item in items:
            lines.append(f"- {item}")
        lines.append("")
    if not lines:
        lines.append("No changes documented.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate GitHub release notes")
    parser.add_argument(
        "--since", default=None, help="Tag to compute notes since (default: last tag)"
    )
    args = parser.parse_args()

    since = args.since or _last_tag()
    commits = _commits_since(since)
    notes = generate_notes(since, commits)
    print(notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
