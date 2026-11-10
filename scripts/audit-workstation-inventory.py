#!/usr/bin/env python3
"""Read-only Ubuntu inventory beyond HOME; print only, no secrets or IDs.

Canonical collector of workstation-system-inventory/v1, ported from dotfiles
bin/inspect-workstation-system.py: same v1 fields, plus a ``provenance`` tree
that mirrors them with the source and UTC time of each observation. Fixed
commands go through audit_common.run_fixed, unprivileged.
"""

from __future__ import annotations

import argparse
from collections import namedtuple
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re

_COMMON = importlib.util.spec_from_file_location(
    "audit_common",
    Path(__file__).with_name("audit_common.py"),
)
common = importlib.util.module_from_spec(_COMMON)
_COMMON.loader.exec_module(common)

SCHEMA = "workstation-system-inventory/v1"
SERVICES = (
    "apparmor.service",
    "ufw.service",
    "nftables.service",
    "ssh.service",
    "fail2ban.service",
    "auditd.service",
    "unattended-upgrades.service",
    "fstrim.timer",
    "apt-daily.timer",
    "apt-daily-upgrade.timer",
)
PACKAGES = (
    "apparmor",
    "ufw",
    "nftables",
    "openssh-server",
    "fail2ban",
    "auditd",
    "unattended-upgrades",
    "cryptsetup",
    "fwupd",
    "intel-microcode",
    "amd64-microcode",
)
SYSCTLS = (
    "kernel.dmesg_restrict",
    "kernel.kptr_restrict",
    "kernel.yama.ptrace_scope",
    "kernel.unprivileged_bpf_disabled",
    "kernel.unprivileged_userns_clone",
    "fs.protected_hardlinks",
    "fs.protected_symlinks",
    "net.ipv4.ip_forward",
    "net.ipv4.conf.all.rp_filter",
)
MOUNTS = ("/", "/boot", "/boot/efi", "/workspace", "/data")
STATES = frozenset(
    (
        "active",
        "inactive",
        "failed",
        "activating",
        "deactivating",
        "enabled",
        "disabled",
        "static",
        "masked",
        "indirect",
        "generated",
        "transient",
        "alias",
        "linked",
        "linked-runtime",
        "enabled-runtime",
    ),
)
COMMANDS = {
    "systemctl": "/usr/bin/systemctl",
    "dpkg-query": "/usr/bin/dpkg-query",
    "lsblk": "/usr/bin/lsblk",
    "mokutil": "/usr/bin/mokutil",
    "nvidia-smi": "/usr/bin/nvidia-smi",
}
LIMITATIONS = [
    "Observed locally without sudo; missing means unknown.",
    "Unit state does not prove firewall policy or SSH security.",
    "LUKS detection does not prove root filesystem encryption.",
    "No hostnames, users, IP/MAC, UUID, serial numbers or secrets.",
    "No data is written to disk by this script.",
]

Observed = namedtuple("Observed", "value source observed_at")


def seen(value, source):
    at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return Observed(value, source, at)


def split(tree):
    """Return (v1 values, provenance) for a dict tree whose leaves are Observed."""
    if isinstance(tree, Observed):
        return tree.value, {"source": tree.source, "observed_at": tree.observed_at}
    pairs = {key: split(node) for key, node in tree.items()}
    return (
        {key: pair[0] for key, pair in pairs.items()},
        {key: pair[1] for key, pair in pairs.items()},
    )


def read(path, limit=4096):
    try:
        return Path(path).read_text(errors="replace")[:limit]
    except (OSError, ValueError):
        return ""


def execute(tool, *args):
    """Return ``(stdout, source)``; stdout is empty unless the command succeeded."""
    argv = (COMMANDS[tool], *args)
    # lsblk --json is already near 8 KiB; a refused listing would hide every mount.
    _, stdout = common.run_fixed(argv, timeout=3, max_bytes=65536)
    return stdout, " ".join(argv)


def safe_label(value):
    # Only named hardware/model fields; never query serial/UUID/device IDs.
    return re.sub(r"[^a-zA-Z0-9 ._()+/-]", "", value.strip())[:100] or None


def os_release():
    allowed = {"PRETTY_NAME", "ID", "VERSION_ID"}
    result = {}
    for line in read("/etc/os-release").splitlines():
        key, sep, raw = line.partition("=")
        if sep and key in allowed:
            label = safe_label(raw.strip().strip('"'))
            result[key.lower()] = seen(label, "/etc/os-release")
    return result


def cpu_memory():
    cpu = None
    for line in read("/proc/cpuinfo", 8192).splitlines():
        if line.startswith("model name"):
            cpu = safe_label(line.partition(":")[2])
            break
    match = re.search(r"^MemTotal:\s+(\d+)\s+kB", read("/proc/meminfo"), re.M)
    memory_gib = round(int(match.group(1)) / 1048576, 1) if match else None
    return {
        "cpu_model": seen(cpu, "/proc/cpuinfo"),
        "memory_gib": seen(memory_gib, "/proc/meminfo"),
    }


def dmi(name):
    path = "/sys/class/dmi/id/" + name
    return seen(safe_label(read(path)), path)


def service_state(unit):
    # is-active/is-enabled exit non-zero for inactive units, and run_fixed
    # drops that stdout; show exits 0 and reports the same states.
    raw, source = execute(
        "systemctl",
        "show",
        "--property=ActiveState",
        "--property=UnitFileState",
        unit,
    )
    props = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
    return {
        key: seen(value if value in STATES else "unknown", source)
        for key, value in (
            ("is-active", props.get("ActiveState")),
            ("is-enabled", props.get("UnitFileState")),
        )
    }


def package_version(package):
    raw, source = execute("dpkg-query", "-W", "-f=${Version}", package)
    value = raw.strip()
    valid = re.fullmatch(r"[a-zA-Z0-9.+:~_-]{1,64}", value)
    return seen(value[:64] if valid else None, source)


def boot_and_storage():
    raw, lsblk = execute("lsblk", "--json", "--output", "TYPE,FSTYPE,MOUNTPOINTS")
    mounts = set()
    luks, mapper = False, False

    def visit(items):
        nonlocal luks, mapper
        for item in items:
            if not isinstance(item, dict):
                continue
            luks |= item.get("fstype") == "crypto_LUKS"
            mapper |= item.get("type") == "crypt"
            for value in item.get("mountpoints") or []:
                if value in MOUNTS:
                    mounts.add(value)
            visit(item.get("children") or [])

    try:
        visit(json.loads(raw).get("blockdevices", []))
    except (ValueError, AttributeError, TypeError, RecursionError):
        pass
    result = {
        "mounts_present": {m: seen(m in mounts, lsblk) for m in MOUNTS},
        "luks_device_detected": seen(luks, lsblk),
        "dm_crypt_device_detected": seen(mapper, lsblk),
    }
    raw, mokutil = execute("mokutil", "--sb-state")
    secure = raw.lower()
    secure_boot = (
        "enabled"
        if "secureboot enabled" in secure
        else "disabled"
        if "secureboot disabled" in secure
        else "unknown"
    )
    efi, tpm = "/sys/firmware/efi", "/sys/class/tpm/tpm0"
    return {
        **result,
        "uefi_detected": seen(Path(efi).is_dir(), efi),
        "secure_boot": seen(secure_boot, mokutil),
        "tpm_device_detected": seen(Path(tpm).exists(), tpm),
    }


def security():
    sysctls = {}
    for key in SYSCTLS:
        path = "/proc/sys/" + key.replace(".", "/")
        raw = read(path).strip()
        sysctls[key] = seen(raw if re.fullmatch(r"[0-9]{1,3}", raw) else None, path)
    aa_path = "/sys/module/apparmor/parameters/enabled"
    aa = read(aa_path).strip()
    return {
        "apparmor_kernel_enabled": seen(
            aa == "Y" if aa in ("Y", "N") else None,
            aa_path,
        ),
        "sysctls": sysctls,
        "unit_states": {unit: service_state(unit) for unit in SERVICES},
    }


def inventory():
    raw, gpu_source = execute(
        "nvidia-smi",
        "--query-gpu=name,driver_version",
        "--format=csv,noheader,nounits",
    )
    nvidia = raw.splitlines()
    gpu = nvidia[0].split(",", 1) if nvidia else []
    uname = os.uname()
    values, provenance = split(
        {
            "system": {
                "os": os_release(),
                "kernel_release": seen(safe_label(uname.release), "uname(2)"),
                "architecture": seen(safe_label(uname.machine), "uname(2)"),
            },
            "hardware": {
                **cpu_memory(),
                "motherboard_model": dmi("board_name"),
                "bios_version": dmi("bios_version"),
                "bios_date": dmi("bios_date"),
                "nvidia_gpu": seen(safe_label(gpu[0]) if gpu else None, gpu_source),
                "nvidia_driver": seen(
                    safe_label(gpu[1]) if len(gpu) > 1 else None,
                    gpu_source,
                ),
            },
            "storage_and_boot": boot_and_storage(),
            "security": security(),
            "packages": {name: package_version(name) for name in PACKAGES},
        },
    )
    return {
        "schema": SCHEMA,
        **values,
        "limitations": LIMITATIONS,
        "provenance": provenance,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--format", choices=("summary", "json"), default="summary")
    args = p.parse_args()
    data = inventory()
    if args.format == "json":
        print(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False))
        return
    print("WORKSTATION SYSTEM INVENTORY (read only, no identifiers)")
    system, hw = data["system"], data["hardware"]
    boot, sec = data["storage_and_boot"], data["security"]
    print(f"OS: {system['os'].get('pretty_name') or 'unknown'}")
    print(f"Kernel: {system['kernel_release'] or 'unknown'}")
    print(f"CPU: {hw['cpu_model'] or 'unknown'}")
    print(f"Memory GiB: {hw['memory_gib'] or 'unknown'}")
    print(f"Motherboard: {hw['motherboard_model'] or 'unknown'}")
    print(f"BIOS: {hw['bios_version'] or 'unknown'} ({hw['bios_date'] or 'unknown'})")
    print(
        f"GPU: {hw['nvidia_gpu'] or 'unknown'} / "
        f"NVIDIA driver: {hw['nvidia_driver'] or 'unknown'}",
    )
    print(
        f"UEFI: {boot['uefi_detected']} / Secure Boot: {boot['secure_boot']} / "
        f"TPM: {boot['tpm_device_detected']}",
    )
    print(
        f"LUKS detected: {boot['luks_device_detected']} / "
        f"dm-crypt detected: {boot['dm_crypt_device_detected']}",
    )
    print(
        "Expected mounts:",
        ", ".join(
            key + "=" + ("yes" if value else "no")
            for key, value in boot["mounts_present"].items()
        ),
    )
    print(f"AppArmor kernel enabled: {sec['apparmor_kernel_enabled']}")
    print("Selected sysctls:")
    for key, value in sec["sysctls"].items():
        print(f"  {key}: {value if value is not None else 'unknown'}")
    print("Selected systemd units (active / enabled):")
    for unit, state in sec["unit_states"].items():
        print(f"  {unit}: {state['is-active']} / {state['is-enabled']}")
    present = [
        f"{pkg}={version}" for pkg, version in data["packages"].items() if version
    ]
    print(
        "Selected installed security packages:",
        ", ".join(present) or "none detected",
    )
    print("NOTE: unknown != fail; no hostname, IP, MAC, UUID, serial or secrets.")


if __name__ == "__main__":
    main()
