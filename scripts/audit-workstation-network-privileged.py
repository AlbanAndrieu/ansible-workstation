#!/usr/bin/env python3
"""Opt-in privileged firewall *read* probe; the Python process stays unprivileged.

Root may execute only three fixed system binaries via sudo -n. Never pass
repository scripts, user-supplied arguments, a shell or file paths to sudo.
No rules, addresses, stderr or ports are printed or saved.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess

COLLECTOR = Path(__file__).with_name("audit-workstation-network.py")
SPEC = importlib.util.spec_from_file_location("workstation_network_filter", COLLECTOR)
NETWORK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NETWORK)

SUDO = "/usr/bin/sudo"
MAX_RAW_BYTES = 1024 * 1024
DENIED_MARKERS = (
    "permission denied", "operation not permitted", "must be root",
    "requires root", "you must be root", "password is required",
    "a terminal is required", "not in the sudoers", "not allowed to execute",
    "authentication is required", "no tty present",
)


def privileged_probe(name, executor=None):
    """Return status and private stdout for the shared redacting parser."""
    if name not in NETWORK.COMMANDS:
        raise ValueError("unapproved packet-filter probe")
    if os.geteuid() == 0:
        return "error", ""
    args = NETWORK.COMMANDS[name]
    if not Path(SUDO).is_file() or not Path(args[0]).is_file():
        return "missing", ""
    if executor is None:
        executor = subprocess.run
    try:
        result = executor(
            [SUDO, "-n", "--", *args],
            input="", capture_output=True, text=True, check=False, timeout=5,
            env={"LC_ALL": "C", "PATH": "/usr/sbin:/usr/bin:/bin"},
        )
    except subprocess.TimeoutExpired:
        return "timed_out", ""
    except (OSError, ValueError):
        return "error", ""
    if result.returncode == 0:
        # Do not feed a truncated ruleset to parsers as a successful result.
        raw = result.stdout or ""
        return ("ok", raw) if len(raw.encode("utf-8")) <= MAX_RAW_BYTES else ("error", "")
    error = (result.stderr or "").lower()
    return ("access_denied" if any(v in error for v in DENIED_MARKERS)
            else "error"), ""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ack-privileged-readonly", action="store_true",
        help="Explicit authorization to run only fixed read-only system commands",
    )
    args = parser.parse_args()
    if not args.ack_privileged_readonly:
        parser.error("requires explicit --ack-privileged-readonly")
    if os.geteuid() == 0:
        parser.error("run this Python collector as a regular user, never as root")

    result = NETWORK.inspect(probe=privileged_probe)
    result["collection_mode"] = "opt_in_sudo_n_fixed_commands"
    result["limitations"] = [
        *result["limitations"],
        "Read-only privileged visibility does not prove external reachability.",
        "Only the system nft and iptables-save commands run via noninteractive sudo.",
        "No elevation of the user-owned Python code; no sudoers changes.",
        "A denied or timed-out probe is UNKNOWN, not an empty firewall.",
    ]
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
