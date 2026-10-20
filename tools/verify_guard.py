#!/usr/bin/env python3
"""Verify Guard fragments, version control, and whole-file Git blob identities."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

GUARD = Path("PROTECTED-LINE-GUARD")
SPEC = Path("buildozer.spec")
SECTION_RE = re.compile(
    r"^FILE: (?P<path>.+?) BEGIN ALLOWED\n(?P<content>.*?)\nEND ALLOWED$",
    re.MULTILINE | re.DOTALL,
)
VERSION_BLOCK_RE = re.compile(
    r"^VERSION CONTROL — ЗАЩИЩЁННЫЙ БЛОК НОМЕРА ВЕРСИИ APK\n"
    r"(?P<body>.*?)(?=^={10,})",
    re.MULTILINE | re.DOTALL,
)
SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


def git_blob_sha(path: str) -> str:
    result = subprocess.run(
        ["git", "hash-object", path],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def parse_version(value: str, label: str) -> tuple[int, int, int]:
    match = SEMVER_RE.fullmatch(value.strip())
    if not match:
        raise SystemExit(
            f"VERSION CHECK FAILED: {label} must be major.minor.patch; got {value!r}"
        )
    return tuple(int(part) for part in match.groups())


def read_single_version(body: str, label: str) -> str:
    pattern = re.compile(
        rf"^Модуль \d+ — {re.escape(label)}:\s*\n([^\r\n]+)$",
        re.MULTILINE,
    )
    matches = pattern.findall(body)
    if len(matches) != 1:
        raise SystemExit(
            f"VERSION CHECK FAILED: Guard must contain exactly one {label}; "
            f"found {len(matches)}"
        )
    return matches[0].strip()


def verify_version(guard: str) -> None:
    blocks = list(VERSION_BLOCK_RE.finditer(guard))
    if len(blocks) != 1:
        raise SystemExit(
            "VERSION CHECK FAILED: Guard must contain exactly one VERSION CONTROL block"
        )

    body = blocks[0].group("body")
    old_text = read_single_version(body, "OLD_VERSION")
    new_text = read_single_version(body, "NEW_VERSION")
    old_version = parse_version(old_text, "OLD_VERSION")
    new_version = parse_version(new_text, "NEW_VERSION")

    if new_version <= old_version:
        raise SystemExit(
            f"VERSION CHECK FAILED: NEW_VERSION {new_text} must be greater than "
            f"OLD_VERSION {old_text}"
        )

    if not SPEC.is_file():
        raise SystemExit("VERSION CHECK FAILED: buildozer.spec is missing")
    spec_text = SPEC.read_text(encoding="utf-8")
    spec_versions = re.findall(r"^version\s*=\s*(\S+)\s*$", spec_text, re.MULTILINE)
    if len(spec_versions) != 1:
        raise SystemExit(
            "VERSION CHECK FAILED: buildozer.spec must contain exactly one version = line"
        )
    spec_text_version = spec_versions[0].strip()
    parse_version(spec_text_version, "buildozer.spec version")

    if spec_text_version != new_text:
        raise SystemExit(
            f"VERSION CHECK FAILED: Guard NEW_VERSION {new_text} does not match "
            f"buildozer.spec version {spec_text_version}"
        )

    print(
        f"VERSION CHECK PASSED: OLD_VERSION={old_text}, "
        f"NEW_VERSION={new_text}, buildozer.spec={spec_text_version}"
    )


def main() -> int:
    guard = GUARD.read_text(encoding="utf-8")
    sections = list(SECTION_RE.finditer(guard))
    if not sections:
        raise SystemExit("GUARD CHECK FAILED: no allowed sections found")

    for match in sections:
        path = match.group("path")
        expected = match.group("content")
        if "ЗДЕСЬ " + "ДОЛЖЕН НАХОДИТЬСЯ" in expected:
            raise SystemExit(f"GUARD CHECK FAILED: placeholder remains for {path}")
        working_path = Path(path)
        if not working_path.is_file():
            raise SystemExit(f"GUARD CHECK FAILED: missing working file {path}")
        actual = working_path.read_text(encoding="utf-8")
        if actual.count(expected) != 1:
            raise SystemExit(
                f"GUARD CHECK FAILED: {path}: protected fragment count "
                f"is {actual.count(expected)}, expected 1"
            )

    verify_version(guard)

    marker = "EXPECTED-GIT-BLOB-SHA:"
    for line in guard.splitlines():
        if not line.startswith(marker):
            continue
        path, expected_sha = line[len(marker):].split("=", 1)
        actual_sha = git_blob_sha(path)
        if actual_sha != expected_sha:
            raise SystemExit(
                f"GUARD CHECK FAILED: {path}: git blob SHA {actual_sha} "
                f"!= Guard {expected_sha}"
            )

    print("GUARD CHECK PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
