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



def sign_apk(
    apk_path: str | Path,
    output_path: str | Path,
    expected_sha256: str = REFERENCE_SHA256,
    apksigner_path: str = "apksigner",
) -> str:
    """Sign to a separate output using CI-injected secrets, then verify the cert."""
    apk = Path(apk_path).resolve()
    output = Path(output_path).resolve()
    if not apk.is_file():
        raise SigningVerificationError(f"Input APK does not exist: {apk}")
    if apk == output:
        raise SigningVerificationError("Output must differ from the input APK.")
    if output.exists():
        raise SigningVerificationError(
            "Output already exists; refusing to overwrite an existing artifact."
        )

    required = (
        "YJ64_KEYSTORE_BASE64",
        "YJ64_KEYSTORE_PASSWORD",
        "YJ64_KEY_ALIAS",
        "YJ64_KEY_PASSWORD",
    )
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise SigningVerificationError(
            "Signing secrets are not configured: " + ", ".join(missing)
        )

    executable = shutil.which(apksigner_path)
    if executable is None:
        raise SigningVerificationError(
            "apksigner was not found; install Android build-tools or pass its path."
        )

    try:
        keystore_bytes = base64.b64decode(
            os.environ["YJ64_KEYSTORE_BASE64"], validate=True
        )
    except (ValueError, base64.binascii.Error) as exc:
        raise SigningVerificationError(
            "YJ64_KEYSTORE_BASE64 is not valid base64."
        ) from exc
    if not keystore_bytes:
        raise SigningVerificationError("Decoded keystore is empty.")

    key_fd, key_path = tempfile.mkstemp(prefix="yj64-sign-", suffix=".keystore")
    os.chmod(key_path, 0o600)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output.with_name(output.name + ".signing-tmp")
    try:
        with os.fdopen(key_fd, "wb") as handle:
            handle.write(keystore_bytes)
        if temp_output.exists():
            raise SigningVerificationError(
                "Temporary output already exists; refusing to overwrite it."
            )
        result = subprocess.run(
            [
                executable, "sign",
                "--ks", key_path,
                "--ks-key-alias", os.environ["YJ64_KEY_ALIAS"],
                "--ks-pass", "env:YJ64_KEYSTORE_PASSWORD",
                "--key-pass", "env:YJ64_KEY_PASSWORD",
                "--out", str(temp_output),
                str(apk),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
            env=os.environ.copy(),
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise SigningVerificationError(
                "apksigner failed to sign the APK."
                + (f" Details: {detail}" if detail else "")
            )
        fingerprint = verify_apk_signature(
            temp_output, expected_sha256, apksigner_path
        )
        temp_output.replace(output)
        return fingerprint
    finally:
        try:
            os.remove(key_path)
        except FileNotFoundError:
            pass
        try:
            temp_output.unlink()
        except FileNotFoundError:
            pass

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
        if args.sign:
            if not args.output:
                parser.error("--output is required with --sign")
            fingerprint = sign_apk(
                args.apk, args.output, args.expected_sha256, args.apksigner
            )
        else:
            if args.output:
                parser.error("--output is only valid with --sign")
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
