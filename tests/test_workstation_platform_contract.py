"""Offline contract: the role targets Ubuntu 20.04 or later.

No workstation access, sudo or apply: playbooks and tasks are only read as text.
"""

from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class WorkstationPlatformContract(unittest.TestCase):
    def test_version_floor_replaces_release_list(self):
        text = (ROOT / "workstation.yml").read_text()
        self.assertNotIn("Ubuntu-25*", text)
        self.assertNotIn("!supported", text)
        plays = yaml.safe_load(text)
        gate = next(
            p for p in plays if p.get("name") == "Fail for an unsupported distribution"
        )
        self.assertIn("platform", gate["tags"])
        assertion = gate["tasks"][0]["ansible.builtin.assert"]
        self.assertIn("version('20.04', '>=')", assertion["that"])

    def test_role_tasks_have_no_old_release_guard(self):
        for path in sorted((ROOT / "tasks").glob("*.yml")):
            for n, line in enumerate(path.read_text().splitlines(), 1):
                if not line.lstrip().startswith("#"):
                    self.assertNotIn(
                        "ansible_distribution_version",
                        line,
                        f"{path.name}:{n}",
                    )

    def test_playbook_loads_the_repository_role(self):
        # "../" resolved to playbooks/ itself and silently loaded no task.
        play = yaml.safe_load((ROOT / "playbooks/workstation.yml").read_text())[0]
        self.assertEqual(play["roles"][0]["role"], "{{ playbook_dir | dirname }}")


if __name__ == "__main__":
    unittest.main()
