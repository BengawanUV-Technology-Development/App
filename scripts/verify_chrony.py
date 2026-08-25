#!/usr/bin/env python3
"""Read-only pre-flight verification for chrony synchronization."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from typing import Any, Iterable


class ChronyVerificationError(RuntimeError):
    """Raised when chrony is unavailable or not synchronized."""


_SYSTEM_TIME_RE = re.compile(r"^System time\s*:\s*([+-]?[0-9.eE-]+)\s+seconds", re.MULTILINE)


def verify_chrony(
    *,
    role: str,
    max_offset_ms: float = 5.0,
    chronyc_path: str | None = None,
) -> dict[str, Any]:
    if role not in {"ground-server", "jetson-client"}:
        raise ChronyVerificationError("role must be ground-server or jetson-client")
    if max_offset_ms < 0:
        raise ChronyVerificationError("max_offset_ms must be non-negative")

    executable = chronyc_path or shutil.which("chronyc")
    if not executable:
        raise ChronyVerificationError("chronyc is not installed or not in PATH")

    tracking = _run(executable, "-n", "tracking")
    sources = _run(executable, "-n", "sources", "-v")
    leap_status = _line_value(tracking, "Leap status")
    if leap_status != "Normal":
        raise ChronyVerificationError(
            f"chrony leap status is not Normal: {leap_status or 'missing'}"
        )
    match = _SYSTEM_TIME_RE.search(tracking)
    if not match:
        raise ChronyVerificationError("chrony tracking has no System time offset")
    offset_seconds = abs(float(match.group(1)))
    offset_ms = offset_seconds * 1000.0
    if offset_ms > max_offset_ms:
        raise ChronyVerificationError(
            f"clock offset {offset_ms:.3f} ms exceeds {max_offset_ms:.3f} ms"
        )

    selected_source = any(
        line.lstrip().startswith("^*") or line.lstrip().startswith("^+")
        for line in sources.splitlines()
    )
    if role == "jetson-client" and not selected_source:
        raise ChronyVerificationError("Jetson has no selected chrony source")

    return {
        "ok": True,
        "role": role,
        "offset_ms": offset_ms,
        "max_offset_ms": max_offset_ms,
        "leap_status": leap_status,
        "selected_source": selected_source,
    }


def _run(executable: str, *args: str) -> str:
    try:
        result = subprocess.run(
            [executable, *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ChronyVerificationError(f"chronyc {' '.join(args)} failed: {exc}") from exc
    return result.stdout


def _line_value(output: str, label: str) -> str | None:
    pattern = re.compile(rf"^{re.escape(label)}\s*:\s*(.*)$")
    for line in output.splitlines():
        match = pattern.match(line)
        if match:
            return match.group(1).strip()
    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=("ground-server", "jetson-client"))
    parser.add_argument("--max-offset-ms", type=float, default=5.0)
    parser.add_argument(
        "--chronyc-path",
        help="explicit chronyc executable path, useful for Homebrew on macOS",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        report = verify_chrony(
            role=args.role,
            max_offset_ms=args.max_offset_ms,
            chronyc_path=args.chronyc_path,
        )
    except ChronyVerificationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
