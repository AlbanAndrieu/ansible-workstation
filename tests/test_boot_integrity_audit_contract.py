"""Pure tests on a fake root: no efivars, modinfo or TPM access."""

import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/audit-boot-integrity.py"
spec = importlib.util.spec_from_file_location("bootaudit", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

CERT = b"\x30\x82fake-dkms-der"


def write(root, rel, data):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def fake_root(root, *, secure_boot=0, enrolled=False, taint=b"POE\n"):
    efivars = "sys/firmware/efi/efivars"
    write(
        root,
        f"{efivars}/SecureBoot-{mod.EFI_GLOBAL}",
        b"\x06\x00\x00\x00" + bytes([secure_boot]),
    )
    mok_list = b"\x07\x00\x00\x00header" + (CERT if enrolled else b"canonical-ca")
    write(root, f"{efivars}/MokListRT-{mod.SHIM_LOCK}", mok_list)
    write(root, mod.DKMS_MOK, CERT)
    write(root, "sys/class/tpm/tpm0/tpm_version_major", b"2\n")
    write(root, "sys/module/nvidia/taint", taint)
    write(root, "proc/sys/kernel/tainted", b"12289\n")


def signed(argv):
    return "ok", "dkms key\n"


class BootIntegrityContracts(unittest.TestCase):
    def test_unenrolled_dkms_key_blocks_secure_boot(self):
        with tempfile.TemporaryDirectory() as d:
            fake_root(Path(d))
            report = mod.audit(Path(d), signed)
        self.assertEqual(report["verdict"], "secure_boot_off_enroll_dkms_key_first")
        self.assertEqual(report["kernel_taint"], ["P", "O", "E"])
        self.assertFalse(report["nvidia_signature_trusted"])
        self.assertEqual(report["tpm"], "2.0")

    def test_enrolled_key_is_ready(self):
        with tempfile.TemporaryDirectory() as d:
            fake_root(Path(d), enrolled=True)
            report = mod.audit(Path(d), signed)
        self.assertEqual(report["dkms_mok"], "enrolled")
        self.assertEqual(report["verdict"], "secure_boot_off_ready_to_enable")

    def test_unsigned_module_is_never_ready(self):
        with tempfile.TemporaryDirectory() as d:
            fake_root(Path(d), enrolled=True)
            report = mod.audit(Path(d), lambda argv: ("ok", "\n"))
        self.assertEqual(report["verdict"], "secure_boot_off_nvidia_not_signed")

    def test_secure_boot_on_and_legacy_bios(self):
        with tempfile.TemporaryDirectory() as d:
            fake_root(Path(d), secure_boot=1, taint=b"PO\n")
            self.assertEqual(mod.audit(Path(d), signed)["verdict"], "secure_boot_on")
        with tempfile.TemporaryDirectory() as d:
            report = mod.audit(Path(d), signed)
        self.assertEqual(report["verdict"], "secure_boot_legacy_bios")
        self.assertEqual(report["nvidia_module"], "not_loaded")

    def test_report_holds_no_signer_name_nor_path(self):
        with tempfile.TemporaryDirectory() as d:
            fake_root(Path(d))
            report = mod.audit(Path(d), signed)
        text = repr(report)
        self.assertNotIn("dkms key", text)
        self.assertNotIn(d, text)


if __name__ == "__main__":
    unittest.main()
