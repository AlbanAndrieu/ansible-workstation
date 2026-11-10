"""Offline contract: the historical playbook accepts any Ubuntu from 12.04.

No workstation access, sudo or apply: the playbook is only read as YAML.
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
        self.assertIn("version('12.04', '>=')", assertion["that"])


if __name__ == "__main__":
    unittest.main()
