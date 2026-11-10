"""Offline guardrails for the captured /etc files and their opt-in restore."""

import ipaddress
from pathlib import Path
import re
import subprocess
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
    r"^\s*[\w.-]*(password|passwd|secret|token|api_?key|psk|private_?key)[\w.-]*"
    r"\s*[=:]\s*(?!@@SECRET@@)\S"
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

    def test_capture_script_redacts_derived_secret_keys(self):
        # The rules live in capture-common.sh, sourced by capture-etc.sh.
        common = ROOT / "scripts/capture-common.sh"
        self.assertIn(
            '. "${root}/scripts/capture-common.sh"',
            (ROOT / "scripts/capture-etc.sh").read_text(),
        )
        sample = (
            "db_password = a\nclient_secret: b\nPrivateKey = c\npsk=d\n"
            "password requisite pam_pwquality.so retry=3\n"
        )
        out = subprocess.run(
            ["/bin/bash", "-c", '. "$1"; redact', "redact", str(common)],
            input=sample,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertEqual(out.count("@@SECRET@@"), 4)
        self.assertIn("password requisite pam_pwquality.so retry=3", out)
        self.assertIsNone(UNREDACTED.search(out))

    def test_no_internal_address_or_name_left(self):
        generic = {"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"}
        private = [
            ipaddress.ip_network(n)
            for n in (
                "10.0.0.0/8",
                "172.16.0.0/12",
                "192.168.0.0/16",
                "100.64.0.0/10",
                "fc00::/7",
            )
        ]
        ipv4 = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(/\d{1,2})?(?!\d)")
        for path in CAPTURED.rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(errors="replace")
            self.assertNotRegex(text, r"(?i)int\.albandrieu\.com", path)
            for match in ipv4.finditer(text):
                if match.group(0) in generic:
                    continue
                try:
                    ip = ipaddress.ip_address(match.group(1))
                except ValueError:
                    continue
                self.assertFalse(any(ip in net for net in private), path)

    def test_restore_marks_manual_only_for_markers_on_active_lines(self):
        v = play()["vars"]
        pattern = (
            v["etc_restore_manual_pattern"]
            .replace("{{ etc_restore_secret_marker }}", v["etc_restore_secret_marker"])
            .replace(
                "{{ etc_restore_internal_marker }}",
                v["etc_restore_internal_marker"],
            )
        )
        manual = re.compile(pattern, re.MULTILINE)
        self.assertTrue(manual.search("a = 1\nDNS=@@INTERNAL@@\n"))
        self.assertTrue(manual.search('Environment="KEY=@@SECRET@@"\n'))
        self.assertFalse(manual.search("a = 1\n# DNS=@@INTERNAL@@\n; p=@@SECRET@@\n"))
        task = next(t for t in play()["tasks"] if "etc_restore_manual" in str(t))
        self.assertIn(
            "is search(etc_restore_manual_pattern, multiline=True)",
            task["when"],
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

    def test_targeted_rollback_touches_nothing_else(self):
        p = play()
        self.assertEqual(p["vars"]["etc_restore_only"], [])
        for task in p["tasks"]:
            if task.get("become") is True:
                with self.subTest(task=task["name"]):
                    self.assertIn("etc_restore_only | length == 0", task["when"])
        names = [t["name"] for t in p["tasks"]]
        self.assertLess(
            names.index("Refuse a requested path that is not restorable"),
            names.index(
                "Restore files, keeping a timestamped backup of what they replace",
            ),
        )

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

    def test_docker_routes_admit_only_truenas_and_deny_the_lan(self):
        routes = self.play["vars"]["harden_docker_routes"]
        for route in routes:
            with self.subTest(route=route["comment"]):
                expected = (
                    "{{ harden_truenas }}"
                    if route["rule"] == "allow"
                    else "{{ harden_lan }}"
                )
                self.assertEqual(route["from"], expected)
        # ufw keeps insertion order: the TrueNAS allow must precede the LAN deny.
        litellm = [r["rule"] for r in routes if r["port"] == "4000"]
        self.assertEqual(litellm, ["allow", "deny"])


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
        self.assertIs(v["os_chmod_home_folders"], False)
        self.assertIs(v["ufw_manage_defaults"], False)
        self.assertEqual(v["sysctl_overwrite"]["net.ipv4.ip_forward"], 1)
        self.assertIs(v["ssh_server_service_enabled"], False)
        self.assertIs(v["ssh_client_hardening"], False)

    def test_sshd_is_never_started(self):
        self.assertIs(self.play["vars"]["ssh_server_enabled"], False)
        stop = self.play["post_tasks"][0]["ansible.builtin.systemd_service"]
        self.assertEqual(stop, {"name": "ssh.service", "state": "stopped"})

    def test_snaps_and_efi_filesystems_stay_loadable(self):
        blocked = self.play["vars"]["os_unused_filesystems"]
        self.assertNotIn("squashfs", blocked)
        self.assertNotIn("vfat", blocked)
        self.assertIn("cramfs", blocked)

    def test_collection_is_pinned(self):
        req = yaml.safe_load((ROOT / "requirements.yml").read_text())
        devsec = next(c for c in req["collections"] if c["name"] == "devsec.hardening")
        self.assertRegex(devsec["version"], r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
