"""Offline DNSSEC differential contracts; no DNS queries, config edits or sudo."""

from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
from unittest import mock
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "scripts/diagnose-dnssec-chain.py"
spec = importlib.util.spec_from_file_location("dnssec_chain_check", SRC)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def confirmed():
    return {
        "private_validated": module.Result("A_CONFIRMED", 0.1),
        "private_no_validation": module.Result("A_CONFIRMED", 0.1),
        "public_validated": module.Result("A_CONFIRMED", 0.1),
        "public_no_validation": module.Result("A_CONFIRMED", 0.1),
        "pfsense_signed_a": module.Result("ANSWER", 0.1, True, True),
        "pfsense_parent_ds": module.Result("ANSWER", 0.1, True, True),
        "pfsense_dnssec_bogus": module.Result("RCODE_SERVFAIL", 0.1),
    }


class DNSSECChainTests(unittest.TestCase):
    def test_good_dnssec_chain(self):
        self.assertEqual(module.verdict([confirmed()]), "PASS")
        self.assertEqual(module.signals(confirmed()), [])

    def test_per_query_dnssec_validation_contrast(self):
        data = confirmed()
        data["public_validated"] = module.Result("TIMEOUT", 4)
        self.assertEqual(
            module.verdict([data]),
            "CLIENT_DNSSEC_VALIDATION_PATH_SUSPECTED",
        )

    def test_transient_bypass_success_not_automatically_root_cause(self):
        first = confirmed()
        first["private_validated"] = module.Result("TIMEOUT", 4)
        second = confirmed()
        second["private_no_validation"] = module.Result("TIMEOUT", 4)
        self.assertEqual(
            module.verdict([first, second]),
            "DNSSEC_PATH_UNVERIFIED_OR_INTERMITTENT",
        )

    def test_upstream_signature_missing_even_when_answers_succeed(self):
        data = confirmed()
        data["pfsense_signed_a"] = module.Result("ANSWER", 0.2, False, False)
        self.assertEqual(
            module.verdict([data]),
            "PFSENSE_DNSSEC_SIGNATURES_NOT_CONFIRMED",
        )

    def test_unchecked_dnssec_bogus_result_stays_unverified(self):
        data = confirmed()
        data["pfsense_dnssec_bogus"] = module.Result("ANSWER", 0.1, True, False)
        self.assertEqual(
            module.verdict([data]),
            "DNSSEC_PATH_UNVERIFIED_OR_INTERMITTENT",
        )

    def test_resolvectl_validate_no_is_only_on_bypass_request(self):
        seen = []

        def fake_command(argv, deadline):
            seen.append(argv)
            return 0, "cloudflare.com: 104.16.132.229 -- link: eno1", 0.1

        with mock.patch.object(module, "command", side_effect=fake_command):
            module.resolved(module.SIGNED, False, 3)
            module.resolved(module.SIGNED, True, 3)
        self.assertEqual(
            seen,
            [
                ["resolvectl", "query", "-4", module.SIGNED],
                ["resolvectl", "query", "-4", "--validate=no", module.SIGNED],
            ],
        )

    def test_rRSIG_and_ad_from_upstream(self):
        out = (
            ";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 123\n"
            ";; flags: qr rd ra ad; QUERY: 1, ANSWER: 2\n"
            "cloudflare.com. 300 IN A 104.16.132.229\n"
            "cloudflare.com. 300 IN RRSIG A 13 2 300 0 0 0 ABCDE\n"
        )
        with mock.patch.object(module, "command", return_value=(0, out, 0.05)):
            response = module.upstream(module.SIGNED, "A", 3)
        self.assertEqual(response.state, "ANSWER")
        self.assertTrue(response.rrsig)
        self.assertTrue(response.ad)

    def test_dnssec_failed_servfail_is_separate(self):
        raw = ";; ->>HEADER<<- opcode: QUERY, status: SERVFAIL, id: 124\n"
        with mock.patch.object(module, "command", return_value=(0, raw, 0.2)):
            self.assertEqual(
                module.upstream(module.INVALID, "A", 3).state,
                "RCODE_SERVFAIL",
            )

    def test_no_header_is_not_noerror(self):
        with mock.patch.object(module, "command", return_value=(9, "", 2.0)):
            self.assertEqual(
                module.upstream(module.SIGNED, "A", 3).state,
                "NO_DNS_RESPONSE",
            )

    def test_command_timeout_is_bounded(self):
        with mock.patch.object(
            module.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["resolvectl"], 3),
        ):
            self.assertEqual(module.command(["resolvectl"], 3)[0], None)

    def test_invalid_arguments_fail_before_network(self):
        with mock.patch.object(sys, "argv", [str(SRC), "--samples", "5"]):
            with mock.patch.object(module, "sample") as probe:
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        module.main()
                probe.assert_not_called()

    def test_cli_does_not_change_resolver_config(self):
        code = SRC.read_text(encoding="utf-8")
        for bad in (
            "sudo ",
            "resolvectl dns ",
            "resolvectl domain ",
            "resolvectl dnssec ",
            "resolvectl dnsovertls ",
            "systemctl restart",
            "nmcli connection modify",
            "systemctl stop",
            "flush-caches",
        ):
            self.assertNotIn(bad, code)
        self.assertIn("--validate=no", code)

    def test_full_pass_is_explicitly_checked(self):
        with mock.patch.object(module, "sample", return_value=confirmed()):
            with mock.patch.object(sys, "argv", [str(SRC), "--check"]):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(module.main(), 0)
        self.assertIn("diagnosis=PASS", output.getvalue())


if __name__ == "__main__":
    unittest.main()
