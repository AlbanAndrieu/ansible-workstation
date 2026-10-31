"""Offline guardrails for the opt-in Restic backup playbook and units."""

from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
UNITS = ROOT / "files/restic"


def play():
    return yaml.safe_load((ROOT / "playbooks/restic-backup.yml").read_text())[0]


class ResticBackupContract(unittest.TestCase):
    def test_check_only_by_default(self):
        p = play()
        self.assertIs(p["become"], False)
        self.assertIs(p["vars"]["restic_apply"], False)
        self.assertIs(p["vars"]["restic_apply_approved"], False)
        for task in p["tasks"]:
            if task.get("become"):
                self.assertEqual(task["when"], "restic_write", task["name"])

    def test_password_never_in_git_or_unit(self):
        for path in UNITS.iterdir():
            text = path.read_text()
            self.assertNotIn("RESTIC_PASSWORD=", text, path)
        backup = (UNITS / "restic-backup.service.j2").read_text()
        self.assertIn("LoadCredentialEncrypted=restic.password:", backup)

    def test_backup_runs_unprivileged_and_is_monitored(self):
        backup = (UNITS / "restic-backup.service.j2").read_text()
        self.assertIn("User={{ restic_user }}", backup)
        self.assertIn("AmbientCapabilities=CAP_DAC_READ_SEARCH", backup)
        self.assertIn("OnFailure=restic-notify@%n.service", backup)
        self.assertTrue(backup.rstrip().endswith("/last-success"))
        timer = (UNITS / "restic-backup.timer").read_text()
        self.assertIn("Persistent=true", timer)
        zabbix = (UNITS / "zabbix-restic.conf").read_text()
        self.assertIn("UserParameter=restic.last_success_age,", zabbix)

    def test_init_never_overwrites_a_repository(self):
        init = (UNITS / "restic-init.service.j2").read_text()
        self.assertIn("ConditionPathExists=!{{ restic_repository }}/config", init)


if __name__ == "__main__":
    unittest.main()
