"""Static contract: OpenClaw source audit uses the project Python interpreter."""
from pathlib import Path
import unittest

PLAY = (Path(__file__).resolve().parents[1] /
        "playbooks/audit-openclaw-source.yml")


class OpenClawAuditInterpreterContract(unittest.TestCase):
    def test_fixed_project_interpreter(self):
        text = PLAY.read_text(encoding="utf-8")
        self.assertIn('ansible_python_interpreter: "{{ ansible_playbook_python }}"', text)
        self.assertIn("gather_facts: false", text)
        self.assertIn("become: false", text)
        self.assertIn("{{ ansible_playbook_python }}", text)
        self.assertNotIn("ansible.builtin.shell:", text)


if __name__ == "__main__":
    unittest.main()
