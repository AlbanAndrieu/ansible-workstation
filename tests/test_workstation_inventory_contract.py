"""Offline contracts for the read-only system inventory (JSON v1 + provenance).

Ported from dotfiles bin/test-workstation-system-inventory.py. Commands and
file reads are stubbed, so nothing depends on the host.
"""

from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/audit-workstation-inventory.py"
SPEC = importlib.util.spec_from_file_location("workstation_inventory", SOURCE)
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)

V1_KEYS = {
    "schema",
    "system",
    "hardware",
    "storage_and_boot",
    "security",
    "packages",
    "limitations",
}
UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
FILES = {
    "/etc/os-release": (
        'PRETTY_NAME="Ubuntu 26.04.1 LTS"\nID=ubuntu\nVERSION_ID="26.04"\n'
        "HOME_URL=https://never.export/\n"
    ),
    "/proc/cpuinfo": "model name\t: Intel(R) Core(TM) i7-9700K CPU @ 3.60GHz\n",
    "/proc/meminfo": "MemTotal:       65748692 kB\n",
    "/sys/class/dmi/id/board_name": "ROG STRIX Z390-F GAMING\n",
    "/sys/module/apparmor/parameters/enabled": "Y\n",
    "/proc/sys/net/ipv4/ip_forward": "1\n",
}
OUTPUTS = {
    "systemctl": "ActiveState=inactive\nUnitFileState=disabled\n",
    "dpkg-query": "1:10.2p1-2ubuntu3.8",
    "lsblk": json.dumps({"blockdevices": [{"type": "part", "mountpoints": ["/"]}]}),
    "mokutil": "SecureBoot disabled\n",
    "nvidia-smi": "NVIDIA GeForce RTX 2060, 595.71.05\n",
}


def fake_read(path, limit=4096):
    return FILES.get(path, "")[:limit]


def fake_execute(name, *args):
    return OUTPUTS[name], " ".join((tool.COMMANDS[name], *args))


def walk(tree, is_leaf, path=()):
    if is_leaf(tree):
        yield path, tree
    else:
        for key, node in tree.items():
            yield from walk(node, is_leaf, path + (key,))


class SystemInventoryContract(unittest.TestCase):
    def test_only_explicit_system_commands_and_fields(self):
        code = SOURCE.read_text()
        for forbidden in (
            "shell=True",
            "sudo ",
            "hostnamectl",
            "ip addr",
            "ifconfig",
            "dmidecode",
            "serial_number",
            "by-uuid",
            "blkid",
            "os.environ",
            "write_text(",
            "open(",
            "ssh-key",
            "/etc/shadow",
            "/etc/ssh/",
            "/home/",
            "git push",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, code)
        self.assertEqual(
            set(tool.COMMANDS),
            {"systemctl", "dpkg-query", "lsblk", "mokutil", "nvidia-smi"},
        )
        self.assertTrue(all(x.startswith("/") for x in tool.COMMANDS.values()))

    def test_safe_hardware_labels_are_bounded(self):
        value = tool.safe_label("RTX 2060\nHOSTNAME=secret\x00" + "x" * 200)
        self.assertNotIn("\n", value)
        self.assertNotIn("=", value)
        self.assertLessEqual(len(value), 100)

    def test_disabled_and_inactive_are_not_misclassified(self):
        with mock.patch.object(tool, "execute", side_effect=fake_execute):
            state, _ = tool.split(tool.service_state("ufw.service"))
        self.assertEqual(state, {"is-active": "inactive", "is-enabled": "disabled"})

    def test_storage_never_emits_device_identifiers_or_custom_mounts(self):
        devices = {
            "blockdevices": [
                {
                    "type": "disk",
                    "name": "sda",
                    "serial": "NEVER_EXPORT",
                    "fstype": "crypto_LUKS",
                    "mountpoints": [None],
                    "children": [
                        {
                            "type": "crypt",
                            "name": "private-data",
                            "uuid": "NEVER_EXPORT",
                            "fstype": "ext4",
                            "mountpoints": ["/workspace", "/sensitive/mount"],
                        },
                    ],
                },
            ],
        }

        def execute(name, *args):
            output = json.dumps(devices) if name == "lsblk" else "SecureBoot enabled"
            return output, name

        with (
            mock.patch.object(tool, "execute", side_effect=execute),
            mock.patch.object(tool.Path, "is_dir", return_value=False),
            mock.patch.object(tool.Path, "exists", return_value=False),
        ):
            result, provenance = tool.split(tool.boot_and_storage())
        self.assertTrue(result["luks_device_detected"])
        self.assertTrue(result["dm_crypt_device_detected"])
        self.assertTrue(result["mounts_present"]["/workspace"])
        self.assertEqual(result["secure_boot"], "enabled")
        for output in (json.dumps(result), json.dumps(provenance)):
            self.assertNotIn("NEVER_EXPORT", output)
            self.assertNotIn("/sensitive/mount", output)

    def test_lsblk_listing_over_8_kib_still_reports_mounts(self):
        # The station's listing was 7962 bytes on 10 Nov 2026.
        loops = [{"type": "loop", "fstype": "squashfs", "mountpoints": ["/snap/x"]}]
        devices = {
            "blockdevices": loops * 200
            + [{"type": "part", "fstype": "ext4", "mountpoints": ["/workspace"]}],
        }
        raw = json.dumps(devices)
        self.assertGreater(len(raw), 8192)
        done = subprocess.CompletedProcess([], 0, stdout=raw, stderr="")
        with (
            mock.patch.object(tool.common.Path, "is_file", return_value=True),
            mock.patch.object(tool.common.subprocess, "run", return_value=done),
        ):
            result, _ = tool.split(tool.boot_and_storage())
        self.assertTrue(result["mounts_present"]["/workspace"])

    def test_absence_is_unknown_not_false_secure_state(self):
        with mock.patch.object(tool, "execute", return_value=("", "stub")):
            state, _ = tool.split(tool.service_state("ssh.service"))
            storage, _ = tool.split(tool.boot_and_storage())
            package, _ = tool.split(tool.package_version("ufw"))
        self.assertEqual(state["is-active"], "unknown")
        self.assertEqual(state["is-enabled"], "unknown")
        self.assertEqual(storage["secure_boot"], "unknown")
        self.assertIsNone(package)

    def test_every_v1_field_has_a_source_and_utc_date(self):
        with (
            mock.patch.object(tool, "read", side_effect=fake_read),
            mock.patch.object(tool, "execute", side_effect=fake_execute),
        ):
            data = tool.inventory()
        self.assertEqual(set(data), V1_KEYS | {"provenance"})
        self.assertEqual(data["schema"], "workstation-system-inventory/v1")
        values = {key: data[key] for key in V1_KEYS - {"schema", "limitations"}}
        fields = dict(walk(values, lambda node: not isinstance(node, dict)))
        sources = dict(
            walk(
                data["provenance"],
                lambda node: set(node) == {"source", "observed_at"},
            ),
        )
        self.assertEqual(set(fields), set(sources))
        self.assertGreater(len(fields), 60)
        for path, entry in sources.items():
            with self.subTest(field=".".join(path)):
                self.assertTrue(entry["source"])
                self.assertRegex(entry["observed_at"], UTC)
        self.assertEqual(set(data["system"]["os"]), {"pretty_name", "id", "version_id"})
        self.assertEqual(
            sources[("security", "sysctls", "net.ipv4.ip_forward")]["source"],
            "/proc/sys/net/ipv4/ip_forward",
        )
        self.assertEqual(
            sources[("security", "unit_states", "ssh.service", "is-enabled")]["source"],
            "/usr/bin/systemctl show --property=ActiveState "
            "--property=UnitFileState ssh.service",
        )
        self.assertEqual(data["hardware"]["nvidia_driver"], "595.71.05")
        self.assertNotIn("never.export", json.dumps(data))

    def test_json_output_is_valid_and_has_no_host_identity_fields(self):
        fixture = {
            "schema": tool.SCHEMA,
            "system": {"os": {"pretty_name": "Ubuntu 26.04"}},
            "hardware": {"cpu_model": "Intel"},
            "storage_and_boot": {"secure_boot": "unknown"},
            "security": {"sysctls": {}, "unit_states": {}},
            "packages": {},
            "limitations": [],
            "provenance": {},
        }
        with (
            mock.patch.object(tool, "inventory", return_value=fixture),
            mock.patch("sys.argv", ["inventory", "--format", "json"]),
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                tool.main()
        self.assertEqual(json.loads(output.getvalue()), fixture)
        self.assertNotIn("hostname", output.getvalue().lower())
        self.assertNotIn("serial", output.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
