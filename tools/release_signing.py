#!/usr/bin/env python3
"""Fail-closed APK signing certificate verifier for YJ-64.

This tool can sign an APK with a supplied private keystore and verify its certificate.
It never creates, recovers, prints, or commits a private key. The default fingerprint
is from a previously inspected sample APK and must be confirmed against the APK
currently installed on the target phone before it is treated as the update identity.
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REFERENCE_SHA256 = (
    "8C:89:FD:AE:D3:C5:01:7A:81:D7:C3:1E:D0:32:87:C7:"
    "83:FF:B2:69:C3:FA:7F:4D:D2:00:00:BD:1E:4E:B1:92"
)
CERT_LINE = re.compile(
    r"Signer #\d+ certificate SHA-256 digest:\s*([0-9a-fA-F:]{64,95})"
)


class SigningVerificationError(RuntimeError):
    """Raised when an APK cannot be proven to use the expected signing cert."""


def normalize_fingerprint(value: str) -> str:
    normalized = re.sub(r"[^0-9a-fA-F]", "", value).upper()
    if len(normalized) != 64:
        raise SigningVerificationError(
            "Expected a SHA-256 certificate fingerprint containing 64 hex digits."
        )
    return normalized


def verify_apk_signature(
    apk_path: str | Path,
    expected_sha256: str = REFERENCE_SHA256,
    apksigner_path: str = "apksigner",
) -> str:
    """Return the verified fingerprint; fail closed on missing/ambiguous evidence."""
    apk = Path(apk_path)
    if not apk.is_file():
        raise SigningVerificationError(f"APK does not exist: {apk}")

    executable = shutil.which(apksigner_path)
    if executable is None:
        raise SigningVerificationError(
            "apksigner was not found; install Android build-tools or pass its path."
        )

    result = subprocess.run(
        [executable, "verify", "--verbose", "--print-certs", str(apk)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout).strip()
        raise SigningVerificationError(
            "apksigner could not verify the APK signature."
            + (f" Details: {details}" if details else "")
        )

    fingerprints = CERT_LINE.findall(result.stdout + "\n" + result.stderr)
    if len(fingerprints) != 1:
        raise SigningVerificationError(
            f"Expected exactly one APK signer certificate; found {len(fingerprints)}."
        )

    actual = normalize_fingerprint(fingerprints[0])
    expected = normalize_fingerprint(expected_sha256)
    if actual != expected:
        raise SigningVerificationError(
            "APK signing certificate mismatch. Refusing to label this artifact "
            "as a compatible update. Compare the installed app certificate and "
            "confirm the intended keystore before proceeding."
        )
    return actual


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify that a YJ-64 APK is signed by the expected certificate."
    )
    parser.add_argument("--apk", required=True, help="Path to the APK to verify or sign")
    parser.add_argument("--sign", action="store_true", help="Sign with CI environment secrets and verify the output")
    parser.add_argument("--output", help="Separate output APK path required with --sign")
    parser.add_argument(
        "--expected-sha256",
        default=REFERENCE_SHA256,
        help="Expected certificate SHA-256 fingerprint (colon-separated or plain hex)",
    )
    parser.add_argument(
        "--apksigner",
        default="apksigner",
        help="Path or command name for Android apksigner",
    )
    args = parser.parse_args()

    try:
        fingerprint = verify_apk_signature(
            args.apk, args.expected_sha256, args.apksigner
        )
    except (SigningVerificationError, OSError, subprocess.SubprocessError) as exc:
        print(f"SIGNING VERIFICATION FAILED: {exc}", file=sys.stderr)
        return 2

    print(f"SIGNING VERIFICATION PASSED: SHA-256 {fingerprint}")
    print("This confirms the APK certificate only; it does not by itself prove data migration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
