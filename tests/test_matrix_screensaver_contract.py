"""Contracts for the Matrix screensaver loop, using command stubs."""

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "files/matrix-screensaver.sh"

STUBS = {
    "gdbus": r"""#!/bin/bash
case "$*" in
  *GetIdletime*) echo "(uint64 ${IDLE_MS},)" ;;
  *GetActive*) echo "(${LOCKED},)" ;;
esac
""",
    "xrandr": r"""#!/bin/bash
echo "Monitors: 2"
echo " 0: +*DP-2 1920/1200x1080/340+0+0  DP-2"
echo " 1: +HDMI-2 1920/1200x1080/340+1920+0  HDMI-2"
""",
    "wmctrl": r"""#!/bin/bash
if [[ "$1" == -lp ]]; then
  n=0
  while read -r pid; do
    n=$((n + 1))
    echo "0x0${n}  0 ${pid} host XMatrix: from the XScreenSaver 6.08 distribution"
  done <"${PIDS}"
  echo "0x09  0 1 host Terminal"
else
  echo "wmctrl $*" >>"${LOG}"
fi
""",
    "xmatrix": r"""#!/bin/bash
echo "$$" >>"${PIDS}"
echo "xmatrix $*" >>"${LOG}"
""",
}


class MatrixScreensaverContracts(unittest.TestCase):
    def run_once(self, idle_ms, locked="false"):
        # Cleaned up: executables left under /tmp trip chkrootkit (Xor.DDoS).
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        for name, body in STUBS.items():
            (bin_dir / name).write_text(body)
            (bin_dir / name).chmod(0o755)
        log = tmp / "calls.log"
        env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "MATRIX_HACK": str(bin_dir / "xmatrix"),
            "MATRIX_IDLE_MIN": "10",
            "IDLE_MS": str(idle_ms),
            "LOCKED": locked,
            "LOG": str(log),
            "PIDS": str(tmp / "pids"),
        }
        subprocess.run(["/bin/bash", SCRIPT, "--once"], env=env, check=True, timeout=10)
        time.sleep(0.2)  # the hack stubs run in the background
        return sorted(log.read_text().splitlines()) if log.exists() else []

    def test_idle_draws_one_fullscreen_matrix_per_monitor(self):
        self.assertEqual(
            self.run_once(600_000),
            [
                "wmctrl -i -r 0x01 -b add,fullscreen",
                "wmctrl -i -r 0x02 -b add,fullscreen",
                "xmatrix -geometry 1920x1080+0+0",
                "xmatrix -geometry 1920x1080+1920+0",
            ],
        )

    def test_recent_input_draws_nothing(self):
        self.assertEqual(self.run_once(599_999), [])

    def test_locked_session_draws_nothing(self):
        self.assertEqual(self.run_once(3_600_000, locked="true"), [])


if __name__ == "__main__":
    unittest.main()
