"""Offline guardrails for the captured /etc files and their opt-in restore."""

from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "files/etc-manifest.txt"
CAPTURED = ROOT / "files/etc"
PLAYBOOK = ROOT / "playbooks/restore-etc.yml"
FORBIDDEN = re.compile(
    r"shadow|ssh_host_|system-connections|letsencrypt|auth\.conf\.d|"
    r"credentials|GeoIP\.conf|docker/key\.json|wireguard|sudoers",
)
UNREDACTED = re.compile(
    r"^\s*(password|passwd|secret|token|api_key)\s*[=:]\s*(?!@@SECRET@@)\S"
    r"|HashedControlPassword\s+(?!@@SECRET@@)\S"
    r"|Environment=\"?[A-Z_]*(KEY|TOKEN|SECRET|PASSWORD)=(?!@@SECRET@@)[^\"\s]",
    re.IGNORECASE | re.MULTILINE,
)


def manifest_paths():
    lines = MANIFEST.read_text().splitlines()
    return [x.strip() for x in lines if x.strip() and not x.lstrip().startswith("#")]


def play():
    doc = yaml.safe_load(PLAYBOOK.read_text())
    assert isinstance(doc, list) and len(doc) == 1
    return doc[0]


class EtcCaptureContract(unittest.TestCase):
    def test_manifest_matches_captured_tree(self):
        listed = {p.removeprefix("/etc/") for p in manifest_paths()}
        self.assertTrue(all(p.startswith("/etc/") for p in manifest_paths()))
        tracked = {
            str(p.relative_to(CAPTURED)) for p in CAPTURED.rglob("*") if p.is_file()
        }
        self.assertEqual(listed, tracked)

    def test_no_forbidden_path(self):
        for path in manifest_paths():
            self.assertIsNone(FORBIDDEN.search(path), path)

    def test_secrets_are_redacted(self):
        for path in CAPTURED.rglob("*"):
            if path.is_file():
                self.assertIsNone(
                    UNREDACTED.search(path.read_text(errors="replace")),
                    path,
                )

    def test_restore_is_check_only_by_default(self):
        p = play()
        self.assertEqual(p["hosts"], "localhost")
        self.assertIs(p["become"], False)
        v = p["vars"]
        self.assertIs(v["etc_restore_apply"], False)
        self.assertIs(v["etc_restore_apply_approved"], False)
        self.assertIs(v["etc_restore_pam"], False)
        copy = next(t for t in p["tasks"] if "ansible.builtin.copy" in t)
        self.assertIs(copy["diff"], False)
        self.assertIs(copy["ansible.builtin.copy"]["backup"], True)
        self.assertEqual(copy["check_mode"], "{{ not etc_restore_write }}")

    def test_not_imported_by_legacy_playbook(self):
        legacy = (ROOT / "playbooks/workstation.yml").read_text()
        self.assertNotIn("restore-etc", legacy)
        self.assertNotIn("restore-packages", legacy)


class PackagesCaptureContract(unittest.TestCase):
    def test_every_privileged_task_needs_both_approvals(self):
        doc = yaml.safe_load((ROOT / "playbooks/restore-packages.yml").read_text())[0]
        self.assertIs(doc["become"], False)
        self.assertIs(doc["vars"]["packages_restore_apply"], False)
        self.assertIs(doc["vars"]["packages_restore_apply_approved"], False)
        for task in doc["tasks"]:
            if task.get("become"):
                when = task["when"]
                when = when if isinstance(when, list) else [when]
                self.assertTrue(
                    any("packages_restore_write" in w for w in when),
                    task["name"],
                )

    def test_selection_excludes_retired_services_and_kernels(self):
        apt = (ROOT / "files/packages/apt.txt").read_text().split()
        self.assertTrue(apt)
        retired = re.compile(r"^(graylog|tomcat|nexus|pacemaker|linux-image-[0-9])")
        self.assertEqual([p for p in apt if retired.match(p)], [])

    def test_keyrings_cover_captured_sources(self):
        refs = set()
        for path in (CAPTURED / "apt/sources.list.d").iterdir():
            refs |= set(re.findall(r"/usr/share/keyrings/([^],\s]+)", path.read_text()))
        stored = {p.name for p in (ROOT / "files/keyrings").iterdir()}
        self.assertLessEqual(refs, stored)


class NetworkHardeningContract(unittest.TestCase):
    def setUp(self):
        text = (ROOT / "playbooks/harden-network.yml").read_text()
        self.play = yaml.safe_load(text)[0]

    def test_check_only_by_default(self):
        self.assertIs(self.play["become"], False)
        self.assertIs(self.play["vars"]["harden_apply"], False)
        self.assertIs(self.play["vars"]["harden_apply_approved"], False)
        for task in self.play["tasks"]:
            if task.get("become"):
                self.assertEqual(task["when"], "harden_write", task["name"])

    def test_every_allow_rule_has_a_restricted_source(self):
        v = self.play["vars"]
        sources = {v["harden_lan"], v["harden_truenas"], v["harden_docker_nets"]}
        self.assertNotIn("any", sources)
        self.assertNotIn("0.0.0.0/0", sources)
        for rule in v["harden_rules"]:
            self.assertRegex(
                rule["from"],
                r"^\{\{ harden_(lan|truenas|docker_nets) \}\}$",
            )
            self.assertIn(rule["proto"], {"tcp", "udp"})


class OsHardeningContract(unittest.TestCase):
    def setUp(self):
        text = (ROOT / "playbooks/harden-os.yml").read_text()
        self.play = yaml.safe_load(text)[0]

    def test_check_mode_unless_both_approvals(self):
        v = self.play["vars"]
        self.assertIs(v["harden_os_apply"], False)
        self.assertIs(v["harden_os_apply_approved"], False)
        self.assertEqual(self.play["check_mode"], "{{ not harden_os_write }}")

    def test_workstation_overrides(self):
        v = self.play["vars"]
        self.assertIs(v["os_pam_enabled"], False)
        self.assertIs(v["os_netrc_enabled"], False)
        self.assertIs(v["ufw_manage_defaults"], False)
        self.assertEqual(v["sysctl_overwrite"]["net.ipv4.ip_forward"], 1)
        self.assertIs(v["ssh_server_service_enabled"], False)
        self.assertIs(v["ssh_client_hardening"], False)

    def test_collection_is_pinned(self):
        req = yaml.safe_load((ROOT / "requirements.yml").read_text())
        devsec = next(c for c in req["collections"] if c["name"] == "devsec.hardening")
        self.assertRegex(devsec["version"], r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
