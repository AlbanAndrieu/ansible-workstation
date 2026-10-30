"""Contract: stale OpenClaw unit is not a deployable Ansible template."""
from pathlib import Path
import importlib.util
import unittest

MOD_PATH=Path(__file__).resolve().parents[1]/"scripts/check-openclaw-template-ownership.py"
sp=importlib.util.spec_from_file_location("oc_ownership",MOD_PATH)
mod=importlib.util.module_from_spec(sp)
sp.loader.exec_module(mod)

class TemplateOwnership(unittest.TestCase):
    def test_stale_template_blocked_without_systemctl_or_ansible(self):
        raw=(mod.ROOT/"mise.toml").read_text()
        template=mod.TEMPLATE.read_text()
        result=mod.inspect(raw,template)
        self.assertTrue(result["template_legacy"])
        self.assertFalse(result["template_node_major_match"])
        self.assertTrue(result["no_mutation"])
        self.assertEqual(mod.main(),2)

    def test_parser_does_not_read_credentials(self):
        result=mod.inspect('[tools]\nnode = "24"\n',
                           'ExecStart=/opt/mise/installs/node/25.4.0/bin/node')
        self.assertFalse(result["template_node_major_match"])
        self.assertTrue(result["template_has_hardcoded_runtime"])
        self.assertNotIn("api_key",str(result).lower())

if __name__ == "__main__":
    unittest.main()
