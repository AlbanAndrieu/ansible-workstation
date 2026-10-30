"""Pure tests: no systemctl, OpenClaw, model, SSH or TrueNAS connections."""
import importlib.util
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[1]/"scripts/audit-openclaw-source.py"
spec=importlib.util.spec_from_file_location("sourceaudit",SCRIPT)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

class SourceAuditContracts(unittest.TestCase):
    def test_truenas_never_checks_local_gateway(self):
        with patch.object(mod,"run",return_value=(0,"TrueNAS-26.0.0-BETA.2")) as runner:
            result=mod.audit()
        self.assertEqual(result["source_audit"],"wrong_host_no_runtime_inference")
        runner.assert_called_once()

    def test_missing_profile_never_checks_node_or_service(self):
        with tempfile.TemporaryDirectory() as d, patch.object(mod,"run",return_value=(127,"")) as runner:
            result=mod.audit(Path(d))
        self.assertEqual(result["source_audit"],"source_profile_unverified")
        runner.assert_called_once()

    def test_source_observed_not_target_ready(self):
        with tempfile.TemporaryDirectory() as d:
            conf=Path(d)/".openclaw/openclaw.json";conf.parent.mkdir()
            conf.write_text("{}")
            with patch.object(mod,"run",side_effect=[
                (127,""), (0,"LoadState=loaded\nActiveState=active\n"),
                (0,"v24.22.1\n"), (0,"OpenClaw 2026.10.7 (build)\n")]) as cmd:
                result=mod.audit(Path(d))
        self.assertEqual(result["source_audit"],"source_cli_and_unit_observed")
        self.assertEqual(result["target"],"truenas_not_examined")
        self.assertEqual(result["effective_gateway_execstart"],"not_verified")
        self.assertEqual(result["model_requests"],0)
        self.assertEqual(cmd.call_count,4)

    def test_drift_is_not_down(self):
        with tempfile.TemporaryDirectory() as d:
            conf=Path(d)/".openclaw/openclaw.json";conf.parent.mkdir()
            conf.write_text("{}")
            with patch.object(mod,"run",side_effect=[
                (127,""), (0,"LoadState=loaded\nActiveState=inactive\n"),
                (0,"v25.0.0"), (127,"")]):
                result=mod.audit(Path(d))
        self.assertEqual(result["source_audit"],"source_drift_or_unverified")
        self.assertEqual(result["gateway_user_unit"],"inactive_or_unverified")

    def test_bounded_version_and_no_leaked_raw_output(self):
        self.assertIsNone(mod.major("v24.1.0 secret=BAD"))
        self.assertEqual(mod.major("v24.22.1\n"),24)
        with patch.object(mod,"run",return_value=(0,"TrueNAS-26.0.0-BETA.2")):
            self.assertNotIn("credential",str(mod.audit()))

if __name__=="__main__":unittest.main()
