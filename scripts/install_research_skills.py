"""Install research skills once; never replace an existing skill or user config.

Pass a client-specific skills directory explicitly. Re-running installation
adds missing skills only. Existing directories (including incomplete installs)
remain user-owned and must be reviewed/merged manually against the source.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / ".claude" / "skills"


def install_skills(destination: Path, *, dry_run: bool = False, source: Path = SOURCE) -> None:
    """Copy whole, absent skill directories; do not mix versions within a skill."""
    destination = destination.expanduser().absolute()
    if destination.resolve().is_relative_to(source.resolve()):
        raise ValueError("Choose a destination outside the bundled skill source")
    if any(path.is_symlink() for path in (destination, *destination.parents)):
        raise ValueError("The destination and its parents must not be symlinks")
    skills = sorted(
        path for path in source.iterdir() if path.name.startswith("pubmed-") or path.name == "pipeline-persistence"
    )
    for skill in skills:
        if skill.is_symlink() or not skill.is_dir() or not (skill / "SKILL.md").is_file():
            raise ValueError(f"Invalid bundled skill: {skill.name}")
        if any(path.is_symlink() for path in skill.rglob("*")):
            raise ValueError(f"Bundled skill contains a symlink: {skill.name}")
    if not dry_run:
        destination.mkdir(parents=True, exist_ok=True)
    for skill in skills:
        target = destination / skill.name
        if target.exists() or target.is_symlink():
            print(f"Preserved: {target} (compare manually with {skill})")
            continue
        if dry_run:
            print(f"Would install: {target}")
            continue
        try:
            # copytree refuses an existing destination, including one created
            # between the existence check and this call. No dirs_exist_ok.
            shutil.copytree(skill, target)
        except FileExistsError:
            print(f"Preserved: {target} (created by another installer)")
        else:
            print(f"Installed: {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-dir", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        install_skills(args.skills_dir, dry_run=args.dry_run)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Installation stopped: {exc}\nExisting skills were not replaced.\n")


if __name__ == "__main__":
    main()
