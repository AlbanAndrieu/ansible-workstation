"""Offline guardrails for the TrueNAS NFS, stabilization and Zabbix host playbooks."""

from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
NFS = ROOT / "playbooks/truenas-nfs-shares.yml"
STABILIZE = ROOT / "playbooks/truenas-stabilize.yml"
ZABBIX = ROOT / "playbooks/zabbix-workstation-host.yml"
HOST = ROOT / "files/zabbix/albandrieu-host.yaml"
GATES = (
    (NFS, "truenas_nfs"),
    (STABILIZE, "truenas_stabilize"),
    (ZABBIX, "zabbix_host"),
)
WRITE_CALLS = (
    "sharing.nfs.update",
    "sharing.nfs.create",
    "sharing.nfs.delete",
    "vm.update",
    "network.configuration.update",
    "pool.snapshottask.delete",
    "cronjob.update",
    "cronjob.create",
    "reset-failed",
    "ui_restart",
    "configuration.import",
)


def play(path):
    return yaml.safe_load(path.read_text())[0]


class TrueNASIntegrationContracts(unittest.TestCase):
    def test_plan_only_by_default(self):
        for path, prefix in GATES:
            with self.subTest(playbook=path.name):
                doc = play(path)
                self.assertFalse(doc["become"])
                self.assertFalse(doc["vars"][f"{prefix}_apply"])
                self.assertFalse(doc["vars"][f"{prefix}_apply_approved"])

    def test_every_write_call_is_gated(self):
        for path, prefix in GATES:
            for task in play(path)["tasks"]:
                # The plan and its report only name the calls.
                if (
                    "ansible.builtin.set_fact" in task
                    or "ansible.builtin.debug" in task
                ):
                    continue
                if any(call in str(task) for call in WRITE_CALLS):
                    with self.subTest(task=task["name"]):
                        self.assertTrue(
                            str(task.get("when")).startswith(f"{prefix}_write"),
                        )

    def test_nfs_deletes_only_declared_absent_shares(self):
        shares = play(NFS)["vars"]["truenas_nfs_shares"]
        paths = [share["path"] for share in shares]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertTrue(all(p.startswith("/mnt/") for p in paths))
        for share in shares:
            with self.subTest(path=share["path"]):
                if share.get("state") == "absent":
                    self.assertTrue(share["path"].startswith("/mnt/dpool/"))
                else:
                    self.assertEqual(share["networks"], "{{ nfs_lan }}")
        delete = [t for t in play(NFS)["tasks"] if "sharing.nfs.delete" in str(t)]
        self.assertEqual(len(delete), 1)
        self.assertIn("'delete'", delete[0]["loop"])

    def test_zabbix_token_never_logged(self):
        for task in play(ZABBIX)["tasks"]:
            if "ansible.builtin.uri" in task:
                with self.subTest(task=task["name"]):
                    self.assertIs(task.get("no_log"), True)

    def test_host_matches_the_workstation(self):
        host = yaml.safe_load(HOST.read_text())["zabbix_export"]["hosts"][0]
        self.assertEqual(host["host"], "albandrieu")
        self.assertEqual(host["interfaces"][0]["ip"], "172.17.0.57")
        self.assertIn({"name": "Linux by Zabbix agent active"}, host["templates"])


if __name__ == "__main__":
    unittest.main()
