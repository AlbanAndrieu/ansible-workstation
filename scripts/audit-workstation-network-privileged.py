#!/usr/bin/env python3
"""Opt-in privileged firewall *read* probe; the Python process stays unprivileged.

Root may execute only three fixed system binaries via sudo -n. Never pass
repository scripts, user-supplied arguments, a shell or file paths to sudo.
No rules, addresses, stderr or ports are printed or saved.
"""

import argparse
import importlib.util
import os
from pathlib import Path

_COMMON = importlib.util.spec_from_file_location(
    "audit_common",
    Path(__file__).with_name("audit_common.py"),
)
common = importlib.util.module_from_spec(_COMMON)
_COMMON.loader.exec_module(common)

COLLECTOR = Path(__file__).with_name("audit-workstation-network.py")
SPEC = importlib.util.spec_from_file_location("workstation_network_filter", COLLECTOR)
NETWORK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NETWORK)

SUDO = "/usr/bin/sudo"
MAX_RAW_BYTES = NETWORK.MAX_RAW_BYTES


def privileged_probe(name, executor=None):
    """Return status and private stdout for the shared redacting parser."""
    if name not in NETWORK.COMMANDS:
        raise ValueError("unapproved packet-filter probe")
    if os.geteuid() == 0:
        return "error", ""
    args = NETWORK.COMMANDS[name]
    if not Path(args[0]).is_file():
        return "missing", ""
    # run_fixed refuses a missing sudo and never returns stderr or partial output.
    status, raw = common.run_fixed(
        [SUDO, "-n", "--", *args],
        timeout=5,
        max_bytes=MAX_RAW_BYTES,
        executor=executor,
    )
    return common.public_status(status), raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ack-privileged-readonly",
        action="store_true",
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
    common.emit(result)


if __name__ == "__main__":
    main()
