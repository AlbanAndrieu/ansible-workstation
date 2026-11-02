"""Offline, non-mutating tests for private per-link NTA dispatcher reception."""

from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
import stat
import subprocess
import sys
from types import SimpleNamespace
from unittest import mock
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/accept-private-nta-dispatcher.py"
spec = importlib.util.spec_from_file_location("private_nta_reapply", SCRIPT)
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


class DispatcherAcceptanceTests(unittest.TestCase):
    def test_profile_matches_exact_link_and_dns(self):
        with mock.patch.object(
            probe,
            "run",
            side_effect=[
                (True, "Wired eno1\n"),
                (True, "Link 2 (eno1): 172.17.0.1\n"),
                (True, "Link 2 (eno1): ~int.albandrieu.com\n"),
            ],
        ) as commands:
            self.assertTrue(probe.expected_network())
            self.assertEqual(commands.call_count, 3)

    def test_wrong_profile_is_rejected_early(self):
        with mock.patch.object(probe, "run", return_value=(True, "Guest-WiFi\n")):
            self.assertFalse(probe.expected_network())

    def test_dispatcher_must_be_root_owned_and_private(self):
        good = SimpleNamespace(st_mode=stat.S_IFREG | 0o700, st_uid=0, st_gid=0)
        bad = SimpleNamespace(st_mode=stat.S_IFREG | 0o775, st_uid=0, st_gid=0)
        with mock.patch.object(Path, "lstat", return_value=good):
            self.assertTrue(probe.expected_dispatcher())
        with mock.patch.object(Path, "lstat", return_value=bad):
            self.assertFalse(probe.expected_dispatcher())

    def test_readonly_happy_path_does_not_mutate(self):
        with mock.patch.object(probe, "preflight", return_value=True):
            with mock.patch.object(probe, "probe_dns", return_value=(True, True)):
                with mock.patch.object(probe, "run") as call:
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(probe.acceptance(False), 0)
                    call.assert_not_called()

    def test_readonly_does_not_conceal_public_dnssec_failure(self):
        with mock.patch.object(probe, "preflight", return_value=True):
            with mock.patch.object(probe, "probe_dns", return_value=(True, False)):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(probe.acceptance(False), 1)

    def test_requires_explicit_ack_for_exercise(self):
        with mock.patch.object(sys, "argv", [str(SCRIPT), "--exercise"]):
            with mock.patch.object(probe, "preflight") as inspection:
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        probe.main()
                inspection.assert_not_called()

    def test_rejects_unknown_network_without_clearing(self):
        with mock.patch.object(probe, "expected_network", return_value=False):
            with mock.patch.object(probe, "expected_dispatcher", return_value=True):
                with mock.patch.object(
                    probe,
                    "link_nta",
                    return_value=(True, [probe.DOMAIN]),
                ):
                    with mock.patch.object(probe, "run") as command:
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(probe.acceptance(True), 2)
                        command.assert_not_called()

    def test_rejects_other_nta_before_mutation(self):
        with mock.patch.object(probe, "expected_network", return_value=True):
            with mock.patch.object(probe, "expected_dispatcher", return_value=True):
                with mock.patch.object(
                    probe,
                    "link_nta",
                    return_value=(True, [probe.DOMAIN, "other.example"]),
                ):
                    with mock.patch.object(probe, "run") as command:
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(probe.acceptance(True), 2)
                        command.assert_not_called()

    def test_mutation_requires_root(self):
        with mock.patch.object(probe, "preflight", return_value=True):
            with mock.patch.object(probe.os, "geteuid", return_value=1000):
                with mock.patch.object(probe, "run") as cmd:
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(probe.acceptance(True), 2)
                    cmd.assert_not_called()

    def test_event_restores_nta_after_actual_clear(self):
        with mock.patch.object(probe, "preflight", return_value=True):
            with mock.patch.object(probe.os, "geteuid", return_value=0):
                with mock.patch.object(
                    probe,
                    "link_nta",
                    side_effect=[
                        (True, []),
                        (True, [probe.DOMAIN]),
                    ],
                ):
                    with mock.patch.object(
                        probe,
                        "expected_network",
                        return_value=True,
                    ):
                        with mock.patch.object(
                            probe,
                            "probe_dns",
                            return_value=(True, True),
                        ):
                            with mock.patch.object(
                                probe,
                                "run",
                                return_value=(True, ""),
                            ) as cmd:
                                with contextlib.redirect_stdout(
                                    io.StringIO(),
                                ) as output:
                                    self.assertEqual(probe.acceptance(True), 0)
                                self.assertEqual(
                                    cmd.call_args_list[0].args[0],
                                    [probe.RESOLVECTL, "nta", "eno1", ""],
                                )
                                self.assertEqual(
                                    cmd.call_args_list[1].args[0],
                                    [
                                        probe.NMCLI,
                                        "--wait",
                                        "15",
                                        "device",
                                        "reapply",
                                        "eno1",
                                    ],
                                )
                                self.assertIn(
                                    "diagnosis=PASS_REAPPLY_PERSISTENCE",
                                    output.getvalue(),
                                )

    def test_nmcli_failure_invokes_scoped_rollback(self):
        with mock.patch.object(probe, "preflight", return_value=True):
            with mock.patch.object(probe.os, "geteuid", return_value=0):
                with mock.patch.object(probe, "link_nta", return_value=(True, [])):
                    with mock.patch.object(
                        probe,
                        "run",
                        side_effect=[(True, ""), (False, "")],
                    ):
                        with mock.patch.object(
                            probe,
                            "restore_on_failure",
                            return_value=True,
                        ) as recover:
                            with contextlib.redirect_stdout(io.StringIO()):
                                self.assertEqual(probe.acceptance(True), 1)
                            recover.assert_called_once()

    def test_reapply_did_not_restore_nta_reverts_to_previous_safe_state(self):
        with mock.patch.object(probe, "preflight", return_value=True):
            with mock.patch.object(probe.os, "geteuid", return_value=0):
                with mock.patch.object(probe, "link_nta", return_value=(True, [])):
                    with mock.patch.object(probe, "run", return_value=(True, "")):
                        with mock.patch.object(
                            probe,
                            "expected_network",
                            return_value=True,
                        ):
                            with mock.patch.object(probe.time, "sleep"):
                                with mock.patch.object(
                                    probe,
                                    "restore_on_failure",
                                    return_value=True,
                                ) as recover:
                                    with contextlib.redirect_stdout(io.StringIO()):
                                        self.assertEqual(probe.acceptance(True), 1)
                                    recover.assert_called_once()

    def test_rollback_fails_closed_when_other_anchor_appears(self):
        with mock.patch.object(probe, "expected_network", return_value=True):
            with mock.patch.object(
                probe,
                "link_nta",
                return_value=(True, ["external.example"]),
            ):
                with mock.patch.object(probe, "run") as command:
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertFalse(probe.restore_on_failure())
                    command.assert_not_called()

    def test_rollback_restores_only_private_nta(self):
        with mock.patch.object(probe, "expected_network", return_value=True):
            with mock.patch.object(probe, "link_nta", return_value=(True, [])):
                with mock.patch.object(
                    probe,
                    "run",
                    return_value=(True, ""),
                ) as command:
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertTrue(probe.restore_on_failure())
                    command.assert_called_once_with(
                        [probe.RESOLVECTL, "nta", "eno1", probe.DOMAIN],
                        timeout=6,
                    )

    def test_probe_requires_public_authenticated_yes(self):
        private = f"{probe.NAME}: {probe.ADDR} -- link: eno1\nData is authenticated: no"
        public = "cloudflare.com: 104.16.132.229\nData is authenticated: yes"
        with mock.patch.object(
            probe,
            "run",
            side_effect=[(True, private), (True, public)],
        ):
            self.assertEqual(probe.probe_dns(), (True, True))
        with mock.patch.object(
            probe,
            "run",
            side_effect=[(True, private), (True, "Data is authenticated: no")],
        ):
            self.assertEqual(probe.probe_dns(), (True, False))

    def test_no_global_dnssec_or_restart_mutation(self):
        source = SCRIPT.read_text()
        for forbidden in (
            "systemctl restart",
            "resolvectl dnssec ",
            "resolvectl revert",
            "resolvectl dnsovertls",
            "flush-caches",
            "nmcli connection modify",
        ):
            self.assertNotIn(forbidden, source)

    def test_run_timeout_is_bounded(self):
        with mock.patch.object(
            probe.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["resolvectl"], 5),
        ):
            self.assertEqual(probe.run(["resolvectl"], 5), (False, ""))


if __name__ == "__main__":
    unittest.main()
