#!/usr/bin/env python3
"""Fail-closed, local-only DNS/NTA preflight for ansible-workstation PR #15.

Default: run two offline test suites, then list ONLY DNS tasks.
--dry-run adds an Ansible --check --diff, never an apply.
No GitHub Actions, checkout mutation, git fetch, or DNS changes.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "playbooks/homelab-dns.yml"
TEST_SUITES = (
    ("test_homelab_dns_guard_contract.py", 8),
    ("test_homelab_dns_nta_dispatcher.py", 17),
)
REQUIRED_TASKS = (
    "Validate opt-in split DNS parameters",
    "Read active NetworkManager profile",
    "Install LAN-only DNSSEC NTA NetworkManager dispatcher",
)
EXTRA_VARS = (
    "workstation_split_dns_enabled=true",
    "workstation_split_dns_nta_dispatcher_enabled=true",
    "workstation_split_dns_nta_dispatcher_remove_enabled=false",
    "workstation_split_dns_persistent_nta_enabled=false",
    "workstation_split_dns_persistent_nta_remove_enabled=false",
)


def execute(argv: list[str], timeout: int = 90) -> tuple[int, str]:
    try:
        result = subprocess.run(
            argv, cwd=ROOT, capture_output=True, text=True,
            check=False, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 2, type(exc).__name__
    return result.returncode, result.stdout + "\n" + result.stderr


def verify_workspace() -> bool:
    paths = [PLAYBOOK, ROOT / "tasks/network_split_dns.yml"]
    paths.extend(ROOT / "tests" / pattern for pattern, _ in TEST_SUITES)
    missing = [str(p.relative_to(ROOT)) for p in paths if not p.is_file()]
    if missing:
        print("FAIL: wrong or stale checkout; missing: " + ", ".join(missing))
        return False
    rc, remote = execute(["git", "remote", "get-url", "origin"])
    if rc != 0 or not re.search(
        r"(?:[:/])AlbanAndrieu/ansible-workstation(?:\.git)?\s*$", remote.strip()
    ):
        print("FAIL: this checkout is not the expected ansible-workstation origin")
        return False
    print("OK: repository=ansible-workstation (role-root)")
    return True


def run_suite(pattern: str, minimum: int) -> bool:
    rc, out = execute(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests",
         "-p", pattern, "-v"],
        timeout=30,
    )
    counts = re.findall(r"\bRan\s+(\d+)\s+tests?\b", out)
    count = int(counts[-1]) if counts else 0
    if rc or count < minimum or "\nOK\n" not in out:
        print(f"FAIL: {pattern} tests={count}, minimum={minimum}, exit={rc}")
        print(out[-4000:])
        return False
    print(f"PASS: {pattern} = {count}/{count}")
    return True


def command(mode: str) -> list[str]:
    args = [
        "ansible-playbook", "-i", "localhost,",
        str(PLAYBOOK), "--tags", "dns",
    ]
    if mode == "list":
        args.append("--list-tasks")
    elif mode == "check":
        args.extend(["--check", "--diff"])
    else:
        raise ValueError("Unsupported mode")
    for pair in EXTRA_VARS:
        args.extend(["-e", pair])
    return args


def task_list() -> bool:
    rc, output = execute(command("list"), timeout=30)
    missing = [name for name in REQUIRED_TASKS if name not in output]
    if rc or missing:
        print("FAIL: Ansible selected 0 or incomplete DNS tasks; no apply authorized")
        print("missing_task_markers=" + (", ".join(missing) or "none"))
        print(output[-4000:])
        return False
    print(f"PASS: DNS-only Ansible list ({len(REQUIRED_TASKS)} required task markers)")
    return True


def dry_run() -> bool:
    rc, output = execute(command("check"), timeout=120)
    # Even when exit=0, require evidence that at least one real DNS task ran.
    markers = ("TASK [workstation | Validate opt-in split DNS parameters]",
               "TASK [workstation | Read active NetworkManager profile]")
    if rc or not any(m in output for m in markers):
        print("FAIL: Ansible check-mode did not execute expected DNS tasks")
        print(output[-5000:])
        return False
    print("PASS: Ansible scoped --check --diff (no apply)")
    print(output[-3500:])
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Also execute Ansible --check --diff after successful tests/list-tasks",
    )
    opts = parser.parse_args()
    print("WORKSTATION_DNS_ANSIBLE_GATE v1")
    if not verify_workspace():
        return 2
    for pattern, minimum in TEST_SUITES:
        if not run_suite(pattern, minimum):
            return 1
    if not task_list():
        return 1
    if opts.dry_run and not dry_run():
        return 1
    print("PASS: discovery verified; deployment NOT performed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
