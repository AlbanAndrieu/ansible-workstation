"""Contracts for the BleachBit-based workstation cleanup (isolated stubs)."""

from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import time
import tomllib
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/workstation-cleanup.sh"
CLEANER = ROOT / "files/bleachbit/workstation_dev.xml"
SYSTEM_TOOLS = (
    "bash env id cat grep sed awk sort tail head df du cmp install mkdir wc "
    "find dirname tr touch"
).split()
BUILTIN = """vscode.cache
vscode.backup
google_chrome.cache
google_chrome.ai
google_chrome.passwords
firefox.cache
thunderbird.cache
thumbnails.cache
claude.cache
claude.logs
claude.tmp
claude.shell_snapshots
system.trash
apt.clean
apt.autoclean
snap.disabled
"""
STUB = r"""#!/bin/bash
echo "NAME $*" >> "$STUB_STATE/calls.log"
"""
BLEACHBIT = r"""#!/bin/bash
echo "bleachbit $*" >> "$STUB_STATE/calls.log"
case "$1" in
  --list-cleaners)
    cat "$STUB_STATE/available.txt"
    if [ -f "$XDG_CONFIG_HOME/bleachbit/cleaners/workstation_dev.xml" ]; then
      cat "$STUB_STATE/custom.txt"
    fi
    ;;
  *) echo "Disk space to be recovered: 1MB"; echo "Files to be deleted: 1" ;;
esac
"""
SUDO = r"""#!/bin/bash
echo "sudo $*" >> "$STUB_STATE/calls.log"
exec "$@"
"""
FORBIDDEN_PREFIXES = (
    "~/.local/share/mise",
    "~/.mozilla",
    "~/.thunderbird",
    "~/.ssh",
    "~/.gnupg",
    "~/.password-store",
    "~/.config/Code/User",
    "~/.config/Cursor/User/workspaceStorage",
    "~/.local/share/wineprefixes",
    "~/.docker",
    "/",
)
PROCESS_ALLOWLIST = {
    "uv cache prune",
    "pre-commit gc",
    "docker image prune --force",
    "docker builder prune --force",
}


def custom_ids():
    root = ET.parse(CLEANER).getroot()
    return [f"{root.get('id')}.{o.get('id')}" for o in root.findall("option")]


class WorkstationCleanupContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="nabla-cleanup-")
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.home = base / "home"
        self.state = base / "state"
        self.checkout = base / "checkout"
        self.stubs = base / "stubs"
        self.sysbin = base / "sysbin"
        for path in (self.home, self.state, self.stubs, self.sysbin):
            path.mkdir(parents=True)
        (self.checkout / "scripts").mkdir(parents=True)
        (self.checkout / "files/bleachbit").mkdir(parents=True)
        shutil.copyfile(SCRIPT, self.checkout / "scripts" / SCRIPT.name)
        shutil.copyfile(CLEANER, self.checkout / "files/bleachbit" / CLEANER.name)
        for tool in SYSTEM_TOOLS:
            (self.sysbin / tool).symlink_to(shutil.which(tool))
        (self.state / "available.txt").write_text(BUILTIN)
        (self.state / "custom.txt").write_text("\n".join(custom_ids()) + "\n")
        self._exe("bleachbit", BLEACHBIT)
        self._exe("sudo", SUDO)
        for tool in ("uv", "docker", "journalctl", "snap", "apt-get"):
            self._exe(tool, STUB.replace("NAME", tool))

    def _exe(self, name, text):
        path = self.stubs / name
        path.write_text(text)
        path.chmod(0o755)

    def run_helper(self, action, **extra):
        env = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "PATH": f"{self.stubs}{os.pathsep}{self.sysbin}",
            "STUB_STATE": str(self.state),
        }
        env.update(extra)
        return subprocess.run(
            [str(self.sysbin / "bash"), "scripts/workstation-cleanup.sh", action],
            cwd=self.checkout,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

    def calls(self):
        log = self.state / "calls.log"
        return log.read_text() if log.exists() else ""

    def clean_args(self):
        line = next(x for x in self.calls().splitlines() if "--clean" in x)
        return set(line.split()[2:])

    def test_check_is_read_only(self):
        result = self.run_helper("check")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertIn("bleachbit --preview", calls)
        self.assertNotIn("--clean", calls)
        self.assertNotIn("sudo", calls)
        self.assertNotIn("docker image", calls)
        self.assertIn("custom cleaner not installed yet", result.stdout)
        cleaner = self.home / ".config/bleachbit/cleaners/workstation_dev.xml"
        self.assertFalse(cleaner.exists())

    def test_apply_installs_cleaner_and_cleans_safe_caches_without_sudo(self):
        result = self.run_helper("apply")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        installed = self.home / ".config/bleachbit/cleaners/workstation_dev.xml"
        self.assertEqual(installed.read_text(), CLEANER.read_text())
        args = self.clean_args()
        for expected in (
            "vscode.cache",
            "google_chrome.ai",
            "workstation_dev.python_caches",
            "workstation_dev.uv_cache",
            "workstation_dev.docker_build",
        ):
            self.assertIn(expected, args)
        for excluded in (
            "workstation_dev.pre_commit_gc",  # pre-commit absent from PATH
            "system.trash",
            "vscode.backup",
            "google_chrome.passwords",
            "workstation_dev.maven_repository",
            "workstation_dev.variety_downloads",
        ):
            self.assertNotIn(excluded, args)
        self.assertNotIn("sudo", self.calls())

    def test_unavailable_options_are_skipped(self):
        (self.state / "available.txt").write_text(
            BUILTIN.replace("google_chrome.ai\n", ""),
        )
        result = self.run_helper("apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("google_chrome.ai", self.clean_args())
        self.assertIn("skipped", result.stderr)

    def test_extra_opt_ins_and_denylist(self):
        result = self.run_helper(
            "apply",
            EXTRA_CLEANERS="system.trash workstation_dev.maven_repository",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            {"system.trash", "workstation_dev.maven_repository"} <= self.clean_args(),
        )
        for denied in (
            "google_chrome.passwords",
            "journald.clean",
            "system.free_disk_space",
            "system.memory",
            "*",
        ):
            with self.subTest(denied=denied):
                (self.state / "calls.log").unlink(missing_ok=True)
                result = self.run_helper("apply", EXTRA_CLEANERS=denied)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(self.calls(), "")

    def test_apply_system_is_bounded(self):
        result = self.run_helper("apply-system")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.calls()
        self.assertIn(
            "sudo bleachbit --clean apt.clean apt.autoclean snap.disabled",
            calls,
        )
        self.assertIn("sudo journalctl --vacuum-size=2G", calls)
        self.assertNotIn("autoremove", calls)
        self.assertNotIn("find", calls)

    def test_apply_system_opt_ins_keep_recent_motion_captures(self):
        motion = self.home / "motion"
        motion.mkdir()
        old, new = motion / "old.mkv", motion / "new.jpg"
        old.write_text("x")
        new.write_text("x")
        past = time.time() - 40 * 86400
        os.utime(old, (past, past))
        result = self.run_helper(
            "apply-system",
            APT_AUTOREMOVE="1",
            MOTION_DIR=str(motion),
            MOTION_RETENTION_DAYS="30",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("sudo apt-get autoremove --purge -y", self.calls())
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())

    def test_invalid_inputs_are_refused(self):
        for extra in (
            {"JOURNAL_MAX": "all"},
            {"APT_AUTOREMOVE": "yes"},
            {"MOTION_RETENTION_DAYS": "0"},
        ):
            with self.subTest(extra=extra):
                self.assertEqual(self.run_helper("apply-system", **extra).returncode, 2)

    def test_cleaner_targets_only_regenerable_caches(self):
        root = ET.parse(CLEANER).getroot()
        self.assertEqual(root.get("id"), "workstation_dev")
        commands = set()
        for option in root.findall("option"):
            for action in option.findall("action"):
                if action.get("command") == "process":
                    commands.add(action.get("cmd"))
                    continue
                self.assertEqual(action.get("command"), "delete")
                path = action.get("path")
                with self.subTest(path=path):
                    self.assertTrue(path.startswith("~/."), path)
                    for prefix in FORBIDDEN_PREFIXES[:-1]:
                        self.assertFalse(path.startswith(prefix), path)
        self.assertEqual(commands, PROCESS_ALLOWLIST)
        warned = {
            o.get("id") for o in root.findall("option") if o.find("warning") is not None
        }
        self.assertEqual(warned, {"maven_repository", "variety_downloads"})

    def test_script_never_uses_destructive_shortcuts(self):
        source = "\n".join(
            line
            for line in SCRIPT.read_text().splitlines()
            if not line.lstrip().startswith("#")
        )
        for pattern in (
            r"\brm\s+-[a-zA-Z]*[rR]",
            r"docker\s+(volume|system\s+prune)",
            r"--volumes",
            r"--delete-data",
            r"journalctl\s+--vacuum-(size|time)=1\b",
        ):
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, source))
        self.assertIn('if [ "$(id -u)" -eq 0 ]; then', source)
        self.assertIn('ACTION="${1:-check}"', source)

    def test_mise_tasks(self):
        with (ROOT / "mise.toml").open("rb") as stream:
            tasks = tomllib.load(stream)["tasks"]
        for name, action in (
            ("cleanup-check", "check"),
            ("cleanup-apply", "apply"),
            ("cleanup-apply-system", "apply-system"),
        ):
            with self.subTest(task=name):
                self.assertEqual(
                    tasks[name]["run"],
                    f"bash scripts/workstation-cleanup.sh {action}",
                )


if __name__ == "__main__":
    unittest.main()
