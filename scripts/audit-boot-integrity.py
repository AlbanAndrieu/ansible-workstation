#!/usr/bin/env python3
"""Read-only Secure Boot, TPM and NVIDIA module audit, without sudo.

Answers one question: can Secure Boot be turned on without losing the GPU?
LUKS key slots (TPM binding) need root and are not examined.
"""

from __future__ import annotations
import importlib.util
from pathlib import Path

_COMMON = importlib.util.spec_from_file_location(
    "audit_common",
    Path(__file__).with_name("audit_common.py"),
)
common = importlib.util.module_from_spec(_COMMON)
_COMMON.loader.exec_module(common)

EFI_GLOBAL = "8be4df61-93ca-11d2-aa0d-00e098032b8c"
SHIM_LOCK = "605dab50-e046-4300-abb6-3dd810dd8b23"
DKMS_MOK = "var/lib/shim-signed/mok/MOK.der"
# Kernel taint bits (Documentation/admin-guide/tainted-kernels.rst).
TAINT_FLAGS = {0: "P", 12: "O", 13: "E"}


def read(path):
    try:
        return path.read_bytes()
    except OSError:
        return None


def secure_boot(root):
    if not (root / "sys/firmware/efi").is_dir():
        return "legacy_bios"
    # efivarfs: 4 attribute bytes, then the 1-byte value.
    raw = read(root / f"sys/firmware/efi/efivars/SecureBoot-{EFI_GLOBAL}")
    if raw is None or len(raw) != 5:
        return "unknown"
    return "enabled" if raw[4] == 1 else "disabled"


def tpm(root):
    raw = read(root / "sys/class/tpm/tpm0/tpm_version_major")
    if raw is None:
        return "absent"
    return {b"2": "2.0", b"1": "1.2"}.get(raw.strip(), "unknown")


def dkms_mok(root):
    der = read(root / DKMS_MOK)
    if not der:
        return "missing"
    # The enrolled DER certificates sit verbatim in the EFI signature lists.
    lists = [
        read(p)
        for p in (
            *(root / "sys/firmware/efi/efivars").glob(f"MokListRT*-{SHIM_LOCK}"),
            *(root / "sys/firmware/efi/mok-variables").glob("MokListRT*"),
        )
    ]
    return "enrolled" if any(der in (raw or b"") for raw in lists) else "not_enrolled"


def nvidia(root, run):
    if not (root / "sys/module/nvidia").is_dir():
        return {"nvidia_module": "not_loaded"}
    taint = (read(root / "sys/module/nvidia/taint") or b"").decode("ascii", "replace")
    status, signer = run(["/usr/sbin/modinfo", "-F", "signer", "nvidia"])
    if status != "ok":
        signature = "unknown"
    else:
        signature = "signed" if signer.strip() else "unsigned"
    return {
        "nvidia_module": "loaded",
        "nvidia_signature": signature,
        # E: the kernel could not verify the signature against a trusted key.
        "nvidia_signature_trusted": "E" not in taint,
    }


def kernel_taint(root):
    raw = read(root / "proc/sys/kernel/tainted")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return ["unknown"]
    return [flag for bit, flag in TAINT_FLAGS.items() if value >> bit & 1]


def verdict(report):
    state = report["secure_boot"]
    if state == "enabled":
        return "secure_boot_on"
    if state != "disabled":
        return f"secure_boot_{state}"
    if report["nvidia_module"] == "not_loaded":
        return "secure_boot_off_ready_to_enable"
    if report["nvidia_signature"] != "signed":
        return "secure_boot_off_nvidia_not_signed"
    if report["dkms_mok"] != "enrolled":
        return "secure_boot_off_enroll_dkms_key_first"
    return "secure_boot_off_ready_to_enable"


def run(argv):
    return common.run_fixed(argv, timeout=5, max_bytes=256)


def audit(root=Path("/"), runner=run):
    report = {
        "schema": "workstation-boot-integrity/v1",
        "read_only": True,
        "secure_boot": secure_boot(root),
        "tpm": tpm(root),
        "dkms_mok": dkms_mok(root),
        "kernel_taint": kernel_taint(root),
        "luks_tpm_binding": "not_examined",
        **nvidia(root, runner),
    }
    report["verdict"] = verdict(report)
    return report


def main():
    report = audit()
    common.emit(report)
    ready = report["verdict"] in ("secure_boot_on", "secure_boot_off_ready_to_enable")
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
