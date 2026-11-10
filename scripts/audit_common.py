"""Shared helpers for the read-only workstation audit scripts.

Sibling scripts load this file by path, without touching the import path, so
it also works under ``python -I``. It never runs a shell, writes files, makes
network connections or changes privileges: callers pass fixed argv tuples only,
and raw output stays in memory.
"""

from __future__ import annotations

import ipaddress
import json
import subprocess
from pathlib import Path

# Minimal environment: no HOME, user PATH, DOCKER_HOST, proxies or credentials.
FIXED_ENV = {"LC_ALL": "C", "PATH": "/usr/sbin:/usr/bin:/sbin:/bin"}
DENIED_MARKERS = (
    "permission denied",
    "operation not permitted",
    "not permitted",
    "permission error",
    "must be root",
    "requires root",
    "you must be root",
    "password is required",
    "a terminal is required",
    "not in the sudoers",
    "not allowed to execute",
    "authentication is required",
    "no tty present",
)
# Statuses the reports expose; everything else collapses to "error".
PUBLIC_STATUSES = ("ok", "missing", "timed_out", "access_denied")


def run_fixed(argv, *, timeout, max_bytes, env=FIXED_ENV, executor=None):
    """Run one fixed command; return ``(status, stdout)``.

    status is ok, missing, timed_out, access_denied, failed (non-zero exit),
    oversize or error. stdout is returned only with ok: stderr and partial or
    oversized output never leave this function. ``env=None`` inherits the
    caller environment, for user-session tools such as ``systemctl --user``.
    """
    if Path(argv[0]).is_absolute() and not Path(argv[0]).is_file():
        return "missing", ""
    if executor is None:
        executor = subprocess.run
    try:
        result = executor(
            argv,
            input="",
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return "timed_out", ""
    except (OSError, ValueError):
        return "error", ""
    if result.returncode != 0:
        detail = ((result.stderr or "") + (result.stdout or "")[:256]).lower()
        if any(marker in detail for marker in DENIED_MARKERS):
            return "access_denied", ""
        return "failed", ""
    raw = result.stdout or ""
    # A truncated ruleset or listing must never be parsed as a complete one.
    if len(raw.encode("utf-8", "replace")) > max_bytes:
        return "oversize", ""
    return "ok", raw


def public_status(status):
    return status if status in PUBLIC_STATUSES else "error"


def bind_scope(address):
    """Classify a bound IP as wildcard, loopback or interface_specific."""
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_unspecified:
        return "wildcard"
    return "loopback" if ip.is_loopback else "interface_specific"


def emit(data, *, indent=2):
    print(json.dumps(data, sort_keys=True, indent=indent))
