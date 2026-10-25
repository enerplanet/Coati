#!/usr/bin/env python3
"""Print the notes of a release and tell whether it is a pre-release.

usage: release_notes.py TAG [--prerelease]

The notes are `.github/releases/<TAG>.md` if that file exists, else the section
of `CHANGELOG.md` that describes the version. With --prerelease, nothing is
printed and the exit status is 0 if the version is a pre-release and 1 if not.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from packaging.version import Version

ROOT = Path(__file__).resolve().parents[2]


def changelog_section(version: Version) -> str:
    """Return the section of the changelog whose heading names `version`."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    for match in re.finditer(r"(?ms)^## \[([^\]]+)\][^\n]*\n(.*?)(?=^## \[|\Z)", text):
        if match[1] != "Unreleased" and Version(match[1]) == version:
            return match[2].strip() + "\n"
    raise SystemExit(f"CHANGELOG.md has no section for the version {version}")


def main(arguments: list[str]) -> int:
    if not arguments or len(arguments) > 2:
        sys.stderr.write(__doc__)
        return 2
    tag = arguments[0]
    version = Version(tag.removeprefix("v"))
    if arguments[1:] == ["--prerelease"]:
        return 0 if version.is_prerelease else 1
    written = ROOT / ".github" / "releases" / f"{tag}.md"
    if written.is_file():
        sys.stdout.write(written.read_text(encoding="utf-8"))
    else:
        sys.stdout.write(changelog_section(version))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
