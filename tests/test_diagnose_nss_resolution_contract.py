"""Offline NSS differential tests: no host DNS or sudo."""

from __future__ import annotations
import contextlib
import importlib.util
import io
from pathlib import Path
from unittest import mock
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "scripts/diagnose-nss-resolution.py"
spec = importlib.util.spec_from_file_location("homelab_nss_paths", FILE)
assert spec and spec.loader
nss = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = nss
spec.loader.exec_module(nss)


def sample(status="A_CONFIRMED", seconds=0.1):
    return nss.Sample(status, seconds)


def good():
    return {
        "resolved_native": sample(),
        "stub_udp": sample(),
        "nss_dns": sample(),
        "nss_resolve": sample("NOT_AVAILABLE"),
        "nss_default": sample(),
    }


class NSSPathTest(unittest.TestCase):
    def test_default_fast_pass(self):
        self.assertEqual(nss.classify(good()), "PASS")

    def test_default_timeout_with_forced_dns_good(self):
        state = good()
        state["nss_default"] = sample("TIMEOUT", 6)
        self.assertEqual(nss.classify(state), "NSS_DEFAULT_CHAIN_SLOW_OR_BROKEN")

    def test_default_success_at_12_seconds_is_still_slow(self):
        state = good()
        state["nss_default"] = sample("A_CONFIRMED", 12.4)
        self.assertEqual(nss.classify(state), "NSS_DEFAULT_CHAIN_SLOW_OR_BROKEN")

    def test_native_resolver_timeout(self):
        state = good()
        state["resolved_native"] = sample("TIMEOUT", 6)
        self.assertEqual(nss.classify(state), "RESOLVED_NATIVE_SLOW_OR_UNVERIFIED")

    def test_stub_udp_timeout(self):
        state = good()
        state.update(
            stub_udp=sample("TIMEOUT", 4),
            nss_dns=sample("TIMEOUT", 6),
            nss_default=sample("TIMEOUT", 6),
        )
        self.assertEqual(nss.classify(state), "RESOLVED_STUB_UDP_SLOW_OR_BROKEN")

    def test_forced_nss_dns_timeout_when_stub_replies(self):
        state = good()
        state.update(nss_dns=sample("TIMEOUT", 6), nss_default=sample("TIMEOUT", 6))
        self.assertEqual(nss.classify(state), "NSS_DNS_PATH_SLOW_OR_BROKEN")

    def test_optional_nss_resolve_module_missing_is_not_failure(self):
        self.assertEqual(nss.classify(good()), "PASS")

    def test_probe_commands_are_bounded_and_separate(self):
        commands = []

        def fake_run(argv, timeout):
            commands.append((argv, timeout))
            return sample()

        with mock.patch.object(nss, "run", side_effect=fake_run):
            with mock.patch.object(
                nss,
                "stub_dns_probe",
                return_value=sample(),
            ) as stub:
                self.assertEqual(len(nss.probe(6)), 5)
                stub.assert_called_once_with(6)
        self.assertEqual(
            [x[0][0] for x in commands],
            ["resolvectl", "getent", "getent", "getent"],
        )
        self.assertEqual(commands[1][0][:3], ["getent", "-s", "hosts:dns"])
        self.assertEqual(commands[2][0][:3], ["getent", "-s", "hosts:resolve"])
        self.assertEqual([x[1] for x in commands], [6, 6, 6, 6])

    def test_timeout_distinct_from_no_answer(self):
        with mock.patch.object(
            nss.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["getent"], 2),
        ):
            self.assertEqual(nss.run(["getent"], 2).status, "TIMEOUT")
        with mock.patch.object(
            nss.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 2, "", ""),
        ):
            self.assertEqual(nss.run(["getent"], 2).status, "NO_ANSWER")

    def test_stub_dns_rcodes_are_preserved(self):
        for rcode in ("SERVFAIL", "NXDOMAIN", "REFUSED"):
            output = ";; ->>HEADER<<- opcode: QUERY, status: " + rcode + ", id: 1\n"
            with (
                self.subTest(rcode=rcode),
                mock.patch.object(
                    nss.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess([], 0, output, ""),
                ),
            ):
                self.assertEqual(nss.stub_dns_probe(3).status, "RCODE_" + rcode)

    def test_stub_empty_noerror_distinct_from_no_response(self):
        header = ";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 1\n"
        with mock.patch.object(
            nss.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, header, ""),
        ):
            self.assertEqual(nss.stub_dns_probe(3).status, "NO_A_ANSWER")
        with mock.patch.object(
            nss.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 9, "", "connection timeout"),
        ):
            self.assertEqual(nss.stub_dns_probe(3).status, "NO_DNS_RESPONSE")

    def test_stub_correct_answer(self):
        output = (
            ";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 1\n"
            "defectdojo.int.albandrieu.com. 0 IN A 172.17.0.24\n"
        )
        with mock.patch.object(
            nss.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, output, ""),
        ):
            self.assertEqual(nss.stub_dns_probe(3).status, "A_CONFIRMED")

    def test_repeated_probes_preserve_per_sample_signals(self):
        failing = good()
        failing["resolved_native"] = sample("TIMEOUT", 3)
        failing["stub_udp"] = sample("RCODE_SERVFAIL", 0.1)
        failing["nss_default"] = sample("TIMEOUT", 3)
        with mock.patch.object(nss, "probe", side_effect=[failing, good()]):
            with mock.patch.object(nss, "hosts_chain", return_value="hosts: files dns"):
                with mock.patch.object(nss, "stub_config", return_value="SYSTEMD_STUB"):
                    with mock.patch.object(
                        sys,
                        "argv",
                        [str(FILE), "--check", "--samples", "2", "--timeout", "3"],
                    ):
                        with contextlib.redirect_stdout(io.StringIO()) as stream:
                            self.assertEqual(nss.main(), 1)
        output = stream.getvalue()
        self.assertIn("diagnosis=INTERMITTENT_RESOLUTION", output)
        self.assertIn("sample_1.stub_udp=RCODE_SERVFAIL", output)
        self.assertIn("sample_2.diagnosis=PASS", output)

    def test_default_can_be_fast_while_stub_is_broken(self):
        state = good()
        state["stub_udp"] = sample("RCODE_SERVFAIL", 0.1)
        self.assertEqual(nss.classify(state), "RESOLVED_STUB_UDP_SLOW_OR_BROKEN")

    def test_default_can_be_fast_while_forced_nss_dns_is_slow(self):
        state = good()
        state["nss_dns"] = sample("TIMEOUT", 6)
        self.assertEqual(nss.classify(state), "NSS_DNS_PATH_SLOW_OR_BROKEN")

    def test_every_sample_unverified_differently_reports_multi_layer(self):
        first = good()
        first["resolved_native"] = sample("TIMEOUT", 4)
        second = good()
        second["nss_default"] = sample("TIMEOUT", 4)
        with mock.patch.object(nss, "probe", side_effect=[first, second]):
            with mock.patch.object(nss, "hosts_chain", return_value="hosts: files dns"):
                with mock.patch.object(nss, "stub_config", return_value="SYSTEMD_STUB"):
                    with mock.patch.object(
                        sys,
                        "argv",
                        [str(FILE), "--samples", "2", "--timeout", "4"],
                    ):
                        with contextlib.redirect_stdout(io.StringIO()) as out:
                            self.assertEqual(nss.main(), 1)
        self.assertIn("diagnosis=MULTI_LAYER_RESOLUTION_UNVERIFIED", out.getvalue())

    def test_readonly_no_configuration_mutations(self):
        src = FILE.read_text()
        for bad in (
            "nmcli connection modify",
            "sudo ",
            "resolvectl dns ",
            "resolvectl domain ",
            "systemctl restart",
            "ln -sf /run/systemd",
            "tee /etc/nsswitch.conf",
        ):
            self.assertNotIn(bad, src)

    def test_failed_default_marks_exit_one(self):
        state = good()
        state["nss_default"] = sample("TIMEOUT", 6)
        with (
            mock.patch.object(nss, "probe", return_value=state),
            mock.patch.object(nss, "hosts_chain", return_value="hosts: files dns"),
            mock.patch.object(nss, "stub_config", return_value="SYSTEMD_STUB"),
            mock.patch.object(sys, "argv", [str(FILE), "--check"]),
            contextlib.redirect_stdout(io.StringIO()) as stream,
        ):
            self.assertEqual(nss.main(), 1)
        self.assertIn("diagnosis=NSS_DEFAULT_CHAIN_SLOW_OR_BROKEN", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
