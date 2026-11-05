"""Offline scoped NTA experiment: never query DNS or use sudo."""

from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
import sys
from unittest import mock
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "scripts/recover-split-dns-nta.py"
spec = importlib.util.spec_from_file_location("scoped_dnssec_nta", FILE)
assert spec and spec.loader
nta = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nta)


class ScopedNTATests(unittest.TestCase):
    def test_default_check_is_readonly(self):
        with (
            mock.patch.object(sys, "argv", [str(FILE)]),
            mock.patch.object(
                nta,
                "verified_profile",
                return_value=True,
            ),
            mock.patch.object(nta, "link_nta", return_value=(True, [])),
            mock.patch.object(
                nta,
                "check_validated",
                return_value=(False, 4),
            ),
            mock.patch.object(nta, "call") as action,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(nta.main(), 1)
            action.assert_not_called()

    def test_acknowledgement_required_before_any_probe(self):
        for op in ("--apply", "--remove"):
            with (
                self.subTest(op=op),
                mock.patch.object(
                    sys,
                    "argv",
                    [str(FILE), op],
                ),
                mock.patch.object(nta, "verified_profile") as inspection,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(SystemExit):
                    nta.main()
                inspection.assert_not_called()

    def test_unknown_profile_refuses_mutation(self):
        with (
            mock.patch.object(
                sys,
                "argv",
                [str(FILE), "--apply", "--acknowledge", nta.ACK],
            ),
            mock.patch.object(
                nta,
                "verified_profile",
                return_value=False,
            ),
            mock.patch.object(nta, "link_nta", return_value=(True, [])),
            mock.patch.object(
                nta,
                "call",
            ) as action,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(nta.main(), 2)
            action.assert_not_called()

    def test_existing_anchors_are_not_overwritten(self):
        with (
            mock.patch.object(
                sys,
                "argv",
                [str(FILE), "--apply", "--acknowledge", nta.ACK],
            ),
            mock.patch.object(
                nta,
                "verified_profile",
                return_value=True,
            ),
            mock.patch.object(nta, "link_nta", return_value=(True, ["other.private"])),
            mock.patch.object(
                nta,
                "call",
            ) as action,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(nta.main(), 2)
            action.assert_not_called()

    def test_apply_only_scoped_nta_command(self):
        with (
            mock.patch.object(
                sys,
                "argv",
                [str(FILE), "--apply", "--acknowledge", nta.ACK],
            ),
            mock.patch.object(
                nta,
                "verified_profile",
                return_value=True,
            ),
            mock.patch.object(
                nta,
                "link_nta",
                side_effect=[(True, []), (True, [nta.DOMAIN])],
            ),
            mock.patch.object(
                nta,
                "check_validated",
                return_value=(True, 0.03),
            ),
            mock.patch.object(nta, "call", return_value=(True, "", "OK")) as action,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(nta.main(), 0)
            action.assert_called_once_with(
                ["sudo", "resolvectl", "nta", "eno1", "int.albandrieu.com"],
                15,
            )

    def test_exact_existing_anchor_not_duplicated(self):
        with (
            mock.patch.object(
                sys,
                "argv",
                [str(FILE), "--apply", "--acknowledge", nta.ACK],
            ),
            mock.patch.object(
                nta,
                "verified_profile",
                return_value=True,
            ),
            mock.patch.object(nta, "link_nta", return_value=(True, [nta.DOMAIN])),
            mock.patch.object(
                nta,
                "check_validated",
                return_value=(True, 0.03),
            ),
            mock.patch.object(nta, "call") as action,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(nta.main(), 0)
            action.assert_not_called()

    def test_rollback_only_single_known_nta(self):
        with (
            mock.patch.object(
                sys,
                "argv",
                [str(FILE), "--remove", "--acknowledge", nta.ACK],
            ),
            mock.patch.object(
                nta,
                "verified_profile",
                return_value=True,
            ),
            mock.patch.object(
                nta,
                "link_nta",
                side_effect=[(True, [nta.DOMAIN]), (True, [])],
            ),
            mock.patch.object(
                nta,
                "check_validated",
                return_value=(False, 5),
            ),
            mock.patch.object(nta, "call", return_value=(True, "", "OK")) as action,
            contextlib.redirect_stdout(io.StringIO()) as stream,
        ):
            self.assertEqual(nta.main(), 0)
            action.assert_called_once_with(
                ["sudo", "resolvectl", "nta", "eno1", ""],
                15,
            )
            self.assertIn("ROLLBACK_CONFIRMED", stream.getvalue())

    def test_rollback_refuses_additional_nta(self):
        with (
            mock.patch.object(
                sys,
                "argv",
                [str(FILE), "--remove", "--acknowledge", nta.ACK],
            ),
            mock.patch.object(
                nta,
                "verified_profile",
                return_value=True,
            ),
            mock.patch.object(
                nta,
                "link_nta",
                return_value=(True, [nta.DOMAIN, "other.test"]),
            ),
            mock.patch.object(
                nta,
                "call",
            ) as action,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(nta.main(), 2)
            action.assert_not_called()

    def test_read_ntas(self):
        with mock.patch.object(
            nta,
            "call",
            return_value=(True, "Link 2 (eno1):", "OK"),
        ):
            self.assertEqual(nta.link_nta(), (True, []))
        with mock.patch.object(
            nta,
            "call",
            return_value=(True, "Link 2 (eno1): int.albandrieu.com", "OK"),
        ):
            self.assertEqual(nta.link_nta(), (True, ["int.albandrieu.com"]))

    def test_source_has_no_dnssec_global_disables(self):
        s = FILE.read_text()
        for forbidden in (
            "resolvectl dnssec ",
            "resolvectl dnsovertls ",
            "nmcli connection modify",
            "systemctl restart",
            "resolvectl revert",
            "flush-caches",
        ):
            self.assertNotIn(forbidden, s)


if __name__ == "__main__":
    unittest.main()
