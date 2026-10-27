"""Offline contract: legacy YubiKey provisioning cannot run in generic role.

No workstation access, sudo, package mutation, credentials or hardware access.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WorkstationOwnershipContract(unittest.TestCase):
    def test_yubikey_legacy_bundle_unreachable_and_retired(self):
        role = (ROOT / "tasks/workstation.yml").read_text()
        self.assertNotIn("import_tasks: yubikey.yml", role)
        self.assertNotIn("include_tasks: yubikey.yml", role)
        self.assertFalse((ROOT / "tasks/yubikey.yml").exists())
        self.assertFalse((ROOT / "templates/pamd-common-auth.conf.j2").exists())

    def test_owner_docs_and_roadmap(self):
        policy = (ROOT / "docs/workstation-ownership-option-a.md").read_text()
        roadmap = (ROOT / "docs/roadmap-workstation.md").read_text()
        for term in ("dotfiles", "nabla-compose", "Restic", "PAM", "YubiKey"):
            with self.subTest(term=term):
                self.assertIn(term, policy)
        for term in ("P0", "P1", "P2", "audit-workstation.yml"):
            with self.subTest(term=term):
                self.assertIn(term, roadmap)

    def test_no_live_security_config_in_repository_snapshot_policy(self):
        policy = (ROOT / "docs/workstation-ownership-option-a.md").read_text()
        for expected in ("hors Git", "opt-in", "aucune modification de PAM"):
            with self.subTest(term=expected):
                self.assertIn(expected, policy)


if __name__ == "__main__":
    unittest.main()
