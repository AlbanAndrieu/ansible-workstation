"""Offline contract: the Nexus client switch is opt-in, HTTPS-only, signed."""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "playbooks/nexus-clients.yml"


class NexusClientsContract(unittest.TestCase):
    def setUp(self):
        self.text = PLAYBOOK.read_text(encoding="utf-8")
        self.play = yaml.safe_load(self.text)[0]
        self.tasks = {t["name"]: t for t in self.play["tasks"]}

    def test_check_only_by_default(self):
        v = self.play["vars"]
        self.assertIs(self.play["become"], False)
        self.assertIs(v["nexus_apply"], False)
        self.assertIs(v["nexus_apply_approved"], False)
        for task in self.play["tasks"]:
            if task.get("become"):
                self.assertEqual(task["when"], "nexus_write", task["name"])

    def test_every_repository_is_probed_before_any_write(self):
        names = list(self.tasks)
        gate = names.index(
            "Refuse to switch while a repository is missing or unreachable",
        )
        writes = [i for i, t in enumerate(self.play["tasks"]) if t.get("become")]
        self.assertTrue(writes and min(writes) > gate)
        self.assertEqual(len(self.play["vars"]["nexus_probes"]), 5)
        self.assertIn(
            "dists/{{ nexus_suite }}-updates/InRelease",
            self.play["vars"]["nexus_probes"][1],
        )
        probe = self.tasks["Probe every Nexus repository the clients would use"]
        self.assertTrue(probe["ansible.builtin.uri"]["validate_certs"])
        self.assertTrue(probe["ansible.builtin.uri"]["return_content"])
        self.assertTrue(probe["no_log"])
        signed = self.tasks[
            "Require signed metadata for all Ubuntu suites before writing APT sources"
        ]
        self.assertEqual(signed["when"], "nexus_write")
        self.assertEqual(len(signed["ansible.builtin.assert"]["that"]), 4)
        self.assertIn("BEGIN PGP SIGNED MESSAGE", str(signed["ansible.builtin.assert"]["that"]))
        self.assertLess(
            list(self.tasks).index(signed["name"]),
            list(self.tasks).index("Fetch APT through the Nexus proxies"),
        )

    def test_https_only_and_signatures_kept(self):
        self.assertEqual(
            self.play["vars"]["nexus_url"],
            "https://nexus.int.albandrieu.com",
        )
        gate = self.tasks["Refuse a cache that is not served over HTTPS"]
        self.assertIn(
            "nexus_url == 'https://nexus.int.albandrieu.com'",
            gate["ansible.builtin.assert"]["that"],
        )
        apt = self.tasks["Fetch APT through the Nexus proxies"]["ansible.builtin.copy"]
        self.assertTrue(apt["backup"])
        self.assertEqual(
            apt["content"].count(
                "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg",
            ),
            2,
        )
        # -security goes through its own security.ubuntu.com proxy.
        self.assertIn(
            "URIs: {{ nexus_apt_security }}\nSuites: {{ nexus_suite }}-security",
            apt["content"],
        )
        for forbidden in ("trusted=yes", "Trusted: yes", "apt-key", "AllowInsecure"):
            self.assertNotIn(forbidden, self.text)

    def test_user_credential_files_are_never_written(self):
        for path in (".npmrc", "pip.conf", "uv.toml"):
            self.assertNotIn(f"dest: ~/{path}", self.text)
            self.assertNotIn(f"/{path}\n", self.text.replace("# ", ""))
        env = self.tasks["Point npm, pip and uv at the Nexus groups"][
            "ansible.builtin.copy"
        ]
        self.assertEqual(env["dest"], "/etc/profile.d/nexus-package-cache.sh")


if __name__ == "__main__":
    unittest.main()
