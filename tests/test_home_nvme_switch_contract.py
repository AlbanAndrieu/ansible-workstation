"""Contracts for the one-shot /home switch onto the NVMe LV, with mount stubs."""

import configparser
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "files/home-nvme-switch.sh"
UNIT = ROOT / "files/home-nvme-switch.service"

# The mount table is a file of mounted paths; FAIL_MOUNT makes mounting that path fail.
STUBS = {
    "mountpoint": 'grep -qxF "$2" "$MOUNTS"',
    "mount": '[ "$2" != "${FAIL_MOUNT:-}" ] && echo "$2" >> "$MOUNTS"',
    "umount": 'grep -vxF "$1" "$MOUNTS" > "$MOUNTS.new"; mv "$MOUNTS.new" "$MOUNTS"',
    "rsync": '[ -z "${FAIL_RSYNC:-}" ] && echo "$@" >> "$MOUNTS.rsync"',
}


class HomeNvmeSwitchContracts(unittest.TestCase):
    def run_switch(self, mounted=(), **env):
        tmp = Path(tempfile.mkdtemp())
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        for name, body in STUBS.items():
            (bin_dir / name).write_text(f"#!/bin/bash\n{body}\n")
            (bin_dir / name).chmod(0o755)
        home, staging, fstab = tmp / "home", tmp / "staging", tmp / "fstab"
        (home / "user").mkdir(parents=True)
        (home / "user/file").write_text("data")
        staging.mkdir()
        fstab.write_text("/dev/root / ext4 defaults 0 1\n")
        mounts = tmp / "mounts"
        mounts.write_text("".join(f"{tmp / m}\n" for m in mounted))
        result = subprocess.run(
            ["/bin/bash", SCRIPT, "/dev/vg/home", home, staging, fstab],
            env={
                **os.environ,
                **env,
                "PATH": f"{bin_dir}:/usr/bin:/bin",
                "MOUNTS": str(mounts),
                "FAIL_MOUNT": str(home) if env.get("FAIL_MOUNT") else "",
            },
            capture_output=True,
            text=True,
        )
        return tmp, result, mounts.read_text().split()

    def test_switches_after_the_final_pass(self):
        tmp, result, mounted = self.run_switch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(mounted, [str(tmp / "home")])
        self.assertEqual((tmp / "home.sda-old/user/file").read_text(), "data")
        rsync = (tmp / "mounts.rsync").read_text()
        self.assertIn(f"--delete {tmp / 'home'}/ {tmp / 'staging'}/", rsync)
        opts = "defaults,nofail,x-systemd.device-timeout=30s"
        self.assertEqual(
            (tmp / "fstab").read_text().splitlines()[-1],
            f"/dev/vg/home {tmp / 'home'} ext4 {opts} 0 0",
        )

    def test_failed_mount_puts_the_old_home_back(self):
        tmp, result, mounted = self.run_switch(FAIL_MOUNT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((tmp / "home/user/file").read_text(), "data")
        self.assertFalse((tmp / "home.sda-old").exists())
        self.assertEqual(mounted, [])
        self.assertNotIn("/dev/vg/home", (tmp / "fstab").read_text())

    def test_failed_copy_moves_nothing(self):
        tmp, result, _ = self.run_switch(FAIL_RSYNC="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((tmp / "home/user/file").read_text(), "data")
        self.assertFalse((tmp / "home.sda-old").exists())

    def test_already_switched_does_nothing(self):
        tmp, result, mounted = self.run_switch(mounted=("home",))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(mounted, [str(tmp / "home")])
        self.assertFalse((tmp / "mounts.rsync").exists())

    def test_unit_runs_once_before_anything_writes_home(self):
        unit = configparser.ConfigParser(interpolation=None)
        unit.optionxform = str
        unit.read(UNIT)
        before = unit["Unit"]["Before"].split()
        for name in (
            "systemd-user-sessions.service",
            "display-manager.service",
            "docker.service",
            "cron.service",
        ):
            self.assertIn(name, before)
        self.assertEqual(unit["Unit"]["ConditionPathExists"], "!/home.sda-old")
        self.assertEqual(
            unit["Service"]["ExecStart"].split()[1:],
            ["/dev/vg-nvme-crypt/home", "/home", "/mnt/home-nvme", "/etc/fstab"],
        )


if __name__ == "__main__":
    unittest.main()
