#!/usr/bin/env python3
"""Read-only attribution of the GNOME "Capture Input" portal requester (W01).

Answers: which application asks for InputCapture, how it starts, and whether
its network side is authenticated. It reads /proc, autostart entries and the
Deskflow settings only: no D-Bus monitoring, no key, pointer or clipboard
capture, no certificate or fingerprint value in the output.
"""

from __future__ import annotations
import configparser
import importlib.util
from pathlib import Path

_COMMON = importlib.util.spec_from_file_location(
    "audit_common",
    Path(__file__).with_name("audit_common.py"),
)
common = importlib.util.module_from_spec(_COMMON)
_COMMON.loader.exec_module(common)

# Input-sharing apps that drive the InputCapture portal; /proc comm is cut at 15 chars.
KNOWN = {
    "deskflow": ("deskflow", "deskflow-core"),
    "input-leap": ("input-leap", "input-leaps", "input-leapc"),
    "barrier": ("barrier", "barriers", "barrierc"),
    "synergy": ("synergy", "synergy-service", "synergy-core"),
    "lan-mouse": ("lan-mouse",),
    "gnome-remote-desktop": ("gnome-remote-de",),
}
PORTAL_IFACE = "org.freedesktop.impl.portal.InputCapture"
DESKFLOW_CONF = ".var/app/org.deskflow.deskflow/config/Deskflow"
LISTEN = "0A"


def read_text(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def portal_backends(root):
    found = []
    for portal in sorted(
        (root / "usr/share/xdg-desktop-portal/portals").glob("*.portal"),
    ):
        if PORTAL_IFACE in (read_text(portal) or ""):
            found.append(portal.stem)
    return found


def running(root):
    seen = {}
    for comm in (root / "proc").glob("[0-9]*/comm"):
        name = (read_text(comm) or "").strip()
        for app, names in KNOWN.items():
            if name in names:
                seen.setdefault(app, []).append(int(comm.parent.name))
    return {app: sorted(pids) for app, pids in sorted(seen.items())}


def autostart(home):
    entries = {}
    for desktop in sorted((home / ".config/autostart").glob("*.desktop")):
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            parser.read_string(read_text(desktop) or "")
            entry = parser["Desktop Entry"]
        except (configparser.Error, KeyError):
            continue
        command = entry.get("Exec", "").lower()
        app = next(
            (a for a in KNOWN if a in command or a in desktop.name.lower()),
            None,
        )
        if app is None:
            continue
        enabled = entry.get("Hidden", "false").lower() != "true" and (
            entry.get("X-GNOME-Autostart-enabled", "true").lower() != "false"
        )
        entries[desktop.name] = {"app": app, "enabled": enabled}
    return entries


def deskflow(home):
    conf_dir = home / DESKFLOW_CONF
    raw = read_text(conf_dir / "Deskflow.conf")
    if raw is None:
        return {"config": "missing"}
    values = {}
    for line in raw.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip()] = value.strip().lower()
    trusted = read_text(conf_dir / "tls/trusted-clients") or ""
    return {
        "config": "present",
        "port": int(values.get("port", "24800") or 24800),
        "tls_enabled": values.get("tlsEnabled") == "true",
        "clipboard_shared": values.get("enableClipboard") == "true",
        # Count only: fingerprints identify peer machines.
        "trusted_clients": sum(1 for line in trusted.splitlines() if line.strip()),
    }


def listener_scope(root, port):
    scopes = set()
    for table in ("proc/net/tcp", "proc/net/tcp6"):
        for line in (read_text(root / table) or "").splitlines()[1:]:
            fields = line.split()
            if len(fields) < 4 or fields[3] != LISTEN:
                continue
            address, _, hex_port = fields[1].partition(":")
            if int(hex_port, 16) != port:
                continue
            if set(address) == {"0"}:
                scopes.add("wildcard")
            elif address in ("0100007F", "00000000000000000000000001000000"):
                scopes.add("loopback")
            else:
                scopes.add("interface_specific")
    return sorted(scopes) or ["not_listening"]


def verdict(report):
    if not report["running"] and not any(
        e["enabled"] for e in report["autostart"].values()
    ):
        return "no_known_requester"
    flow = report["deskflow"]
    if "deskflow" in report["running"] and flow.get("config") == "present":
        if not flow["tls_enabled"] or flow["trusted_clients"] == 0:
            return "deskflow_unauthenticated_peers"
        return "attributed_deskflow_tls_pinned"
    return "attributed_review_manually"


def audit(root=Path("/"), home=Path.home()):
    report = {
        "schema": "workstation-input-capture/v1",
        "read_only": True,
        "input_events_captured": False,
        "portal_backends": portal_backends(root),
        "running": running(root),
        "autostart": autostart(home),
        "deskflow": deskflow(home),
        "consent_dialog_refusal": "not_run_owner_action",
    }
    if report["deskflow"].get("config") == "present":
        report["deskflow"]["listener"] = listener_scope(
            root,
            report["deskflow"]["port"],
        )
    report["verdict"] = verdict(report)
    return report


def main():
    report = audit()
    common.emit(report)
    ok = ("no_known_requester", "attributed_deskflow_tls_pinned")
    return 0 if report["verdict"] in ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
