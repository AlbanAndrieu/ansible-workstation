"""Pure tests on a fake root and home: no /proc, D-Bus or portal access."""

import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/audit-input-capture.py"
spec = importlib.util.spec_from_file_location("inputcapture", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

TCP_HEADER = "  sl  local_address rem_address   st\n"


def write(base, rel, text):
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def fake(base, *, tls="true", trusted="AA:BB\nCC:DD\n", bind="00000000"):
    root, home = base / "root", base / "home"
    write(
        root,
        "usr/share/xdg-desktop-portal/portals/gnome.portal",
        f"[portal]\nInterfaces={mod.PORTAL_IFACE};\n",
    )
    write(root, "proc/4242/comm", "deskflow-core\n")
    write(root, "proc/1/comm", "systemd\n")
    write(root, "proc/net/tcp", TCP_HEADER + f"0: {bind}:60E0 00000000:0000 0A\n")
    write(
        home,
        ".config/autostart/org.deskflow.deskflow.desktop",
        "[Desktop Entry]\nExec=/usr/bin/flatpak run org.deskflow.deskflow\n",
    )
    write(
        home,
        ".config/autostart/barrier.desktop",
        "[Desktop Entry]\nExec=/usr/bin/barrier\nHidden=true\n",
    )
    conf = mod.DESKFLOW_CONF
    write(
        home,
        f"{conf}/Deskflow.conf",
        f"[security]\ntlsEnabled={tls}\n[server]\nport=24800\nenableClipboard=true\n",
    )
    write(home, f"{conf}/tls/trusted-clients", trusted)
    return root, home


class InputCaptureContracts(unittest.TestCase):
    def test_pinned_deskflow_is_attributed_without_leaking_fingerprints(self):
        with tempfile.TemporaryDirectory() as d:
            report = mod.audit(*fake(Path(d)))
        self.assertEqual(report["verdict"], "attributed_deskflow_tls_pinned")
        self.assertEqual(report["running"], {"deskflow": [4242]})
        self.assertEqual(report["portal_backends"], ["gnome"])
        self.assertEqual(report["deskflow"]["trusted_clients"], 2)
        self.assertEqual(report["deskflow"]["listener"], ["wildcard"])
        self.assertFalse(report["autostart"]["barrier.desktop"]["enabled"])
        self.assertNotIn("AA:BB", repr(report))

    def test_no_tls_or_no_pinned_peer_is_flagged(self):
        for kwargs in ({"tls": "false"}, {"trusted": ""}):
            with tempfile.TemporaryDirectory() as d:
                report = mod.audit(*fake(Path(d), **kwargs))
            self.assertEqual(report["verdict"], "deskflow_unauthenticated_peers")

    def test_loopback_listener_and_empty_host(self):
        with tempfile.TemporaryDirectory() as d:
            report = mod.audit(*fake(Path(d), bind="0100007F"))
            self.assertEqual(report["deskflow"]["listener"], ["loopback"])
            empty = mod.audit(Path(d) / "none", Path(d) / "none")
        self.assertEqual(empty["verdict"], "no_known_requester")
        self.assertEqual(empty["deskflow"], {"config": "missing"})


if __name__ == "__main__":
    unittest.main()
