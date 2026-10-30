"""Offline guardrails for Ubuntu YubiKey *OS-only* package prerequisites."""
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "playbooks/yubikey-os-prerequisites.yml"
GENERIC = ROOT / "tasks/workstation.yml"
LEGACY = ROOT / "tasks/yubikey.yml"
BASE_RUNTIME = {
    "yubikey-manager", "pcscd", "libu2f-udev", "libfido2-1",
    "opensc", "gnupg", "scdaemon",
}
BUILD = {"libpcsclite-dev", "pkg-config"}
PAM_TOOLS = {"libpam-u2f"}


def play():
    doc = yaml.safe_load(PLAYBOOK.read_text())
    assert isinstance(doc, list) and len(doc) == 1
    return doc[0]


class YubiKeyOSPrerequisitesContract(unittest.TestCase):
    def test_separate_from_generic_legacy_bundle(self):
        self.assertFalse(LEGACY.exists())
        generic = GENERIC.read_text()
        self.assertNotIn("import_tasks: yubikey", generic)
        self.assertNotIn("include_tasks: yubikey", generic)
        self.assertNotIn("yubikey-os-prerequisites.yml", generic)

    def test_default_is_localhost_without_sudo_or_changes(self):
        p = play()
        self.assertEqual(p["hosts"], "localhost")
        self.assertEqual(p["connection"], "local")
        self.assertIs(p["gather_facts"], False)
        self.assertIs(p["become"], False)
        self.assertEqual(
            p["vars"]["ansible_python_interpreter"], "{{ ansible_playbook_python }}"
        )
        self.assertIs(p["vars"]["yubikey_os_apply"], False)
        self.assertIs(p["vars"]["yubikey_os_apply_approved"], False)
        self.assertIs(p["vars"]["yubikey_os_build_deps_enabled"], False)
        self.assertIs(p["vars"]["yubikey_os_pam_tools_enabled"], False)

    def test_packages_follow_compose_capabilities_without_ppa(self):
        v = play()["vars"]
        self.assertEqual(set(v["yubikey_os_runtime_packages"]), BASE_RUNTIME)
        self.assertEqual(set(v["yubikey_os_build_packages"]), BUILD)
        self.assertEqual(set(v["yubikey_os_pam_tools_packages"]), PAM_TOOLS)
        contents = PLAYBOOK.read_text()
        for forbidden in (
            "apt_repository", "ppa:yubico", "apt-key", "shell:",
            "ansible.builtin.shell", "ansible.builtin.template",
            "/etc/pam.d", "ykman piv", "ykman otp", "ykman fido",
            "pamu2fcfg", "gpg --card", "age-plugin-yubikey --generate",
            "systemd:", "ansible.builtin.service",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, contents)

    def test_allowlisted_distribution_only(self):
        tasks = play()["tasks"]
        os_gate = next(t for t in tasks if "Reject unsupported" in t["name"])
        rules = os_gate["ansible.builtin.assert"]["that"]
        self.assertTrue(any("Ubuntu" in c for c in rules))
        self.assertTrue(any("24.04" in c and "26.04" in c for c in rules))
        self.assertIs(os_gate["no_log"], True)

    def test_all_mutating_operations_are_double_opt_in(self):
        tasks = play()["tasks"]
        privileged = [t for t in tasks if t.get("become") is True]
        self.assertEqual(len(privileged), 1)
        apt = privileged[0]
        self.assertEqual(apt["ansible.builtin.apt"]["state"], "present")
        self.assertEqual(apt["ansible.builtin.apt"]["update_cache"], False)
        self.assertEqual(apt["ansible.builtin.apt"]["install_recommends"], False)
        # Do not allow selecting only the apt task by --tags and skipping
        # the two approval and Ubuntu package availability guards.
        self.assertNotIn("tags", apt)
        self.assertEqual(set(apt["when"]), {
            "yubikey_os_apply | bool", "yubikey_os_apply_approved | bool"
        })
        self.assertTrue(any(
            "second explicit approval" in t["name"] for t in tasks
        ))
        self.assertTrue(any(
            "unavailable package" in t["name"] for t in tasks
        ))

    def test_package_cache_probe_is_read_only_no_log(self):
        tasks = play()["tasks"]
        for task in tasks:
            if "ansible.builtin.command" in task:
                cmd = task["ansible.builtin.command"]["argv"]
                self.assertEqual(cmd[:2], ["/usr/bin/apt-cache", "show"])
                self.assertIs(task["changed_when"], False)
                self.assertIs(task["failed_when"], False)
                self.assertIs(task["no_log"], True)
            if "ansible.builtin.package_facts" in task:
                self.assertIs(task["no_log"], True)
        self.assertTrue(any("ansible.builtin.package_facts" in t for t in tasks))

    def test_mise_only_offers_read_only_tasks(self):
        cfg = (ROOT / "mise.toml").read_text()
        self.assertIn("[tasks.yubikey-os-syntax]", cfg)
        self.assertIn("[tasks.yubikey-os-audit]", cfg)
        self.assertNotIn("[tasks.yubikey-os-apply]", cfg)
        self.assertIn("playbooks/yubikey-os-prerequisites.yml", cfg)
        self.assertIn("scripts/uv-project.sh check", cfg)

    def test_no_hardware_mutation_or_secret_material(self):
        p = play()
        contents = PLAYBOOK.read_text().lower()
        for forbidden in (
            "secret:", "private_key", "pin:", "puk:", "challenge_response",
            "enrollment", "ykman fido reset", "fido2_reset", "piv reset",
            "ssh-keygen", "scdaemon.conf", "sudoers",
        ):
            self.assertNotIn(forbidden, contents)
        self.assertIn("hardware_accessed", contents)
        self.assertIn("pam_configuration_changed", contents)


if __name__ == "__main__":
    unittest.main()
