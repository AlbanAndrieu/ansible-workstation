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
        self.assertIn("%S/restic/last-success.prom", backup)
        zabbix = (UNITS / "zabbix-restic.conf").read_text()
        self.assertIn("UserParameter=restic.last_success_age,", zabbix)

    def test_node_exporter_exposes_host_metrics_to_truenas_only(self):
        args = (UNITS / "prometheus-node-exporter.default").read_text()
        # Host metrics (CPU, memory, filesystems, ZFS, systemd) feed TrueNAS
        # Prometheus and the OpenClaw heartbeat; ufw keeps them TrueNAS-only.
        self.assertNotIn("--collector.disable-defaults", args)
        self.assertIn("--collector.systemd", args)
        self.assertIn("--collector.textfile ", args)
        self.assertIn("--collector.textfile.directory=/var/lib/restic", args)
        # apt, docker-health, nvme and smartmon textfile collectors write here.
        self.assertIn(
            "--collector.textfile.directory=/var/lib/prometheus/node-exporter",
            args,
        )
        self.assertIn("--web.listen-address=172.17.0.57:9100", args)
        harden = yaml.safe_load((ROOT / "playbooks/harden-network.yml").read_text())
        rule = next(r for r in harden[0]["vars"]["harden_rules"] if r["port"] == "9100")
        self.assertEqual(rule["from"], "{{ harden_truenas }}")

    def test_init_never_overwrites_a_repository(self):
        init = (UNITS / "restic-init.service.j2").read_text()
        self.assertIn("ConditionPathExists=!{{ restic_repository }}/config", init)


if __name__ == "__main__":
    unittest.main()
