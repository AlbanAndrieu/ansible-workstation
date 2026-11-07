"""Contracts for the NVIDIA GPU textfile writer, using an nvidia-smi stub."""

from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "files/nvidia-gpu-textfile.sh"

# Two samples, as nvidia-smi -l prints them; the second one has no fan speed.
NVIDIA_SMI_STUB = r"""#!/bin/bash
echo "GPU-1, RTX 2060, 595.71, 99, 40, 4000, 6144, 70, 150.10, 190.00, 1900, 60"
echo "GPU-1, RTX 2060, 595.71, 15, 3, 557, 6144, 42, 34.52, 190.00, 1755, [N/A]"
"""


class NvidiaGpuTextfileContracts(unittest.TestCase):
    def run_script(self):
        tmp = Path(tempfile.mkdtemp())
        stub = tmp / "bin/nvidia-smi"
        stub.parent.mkdir()
        stub.write_text(NVIDIA_SMI_STUB)
        stub.chmod(0o755)
        out = tmp / "nvidia-gpu.prom"
        env = {**os.environ, "PATH": f"{stub.parent}:{os.environ['PATH']}"}
        subprocess.run(["/bin/bash", SCRIPT, out, "1"], env=env, check=True)
        return out.read_text().splitlines(), sorted(p.name for p in tmp.iterdir())

    def test_last_sample_in_base_units(self):
        lines, _ = self.run_script()
        self.assertIn(
            'nvidia_gpu_info{uuid="GPU-1",name="RTX 2060",driver_version="595.71"} 1',
            lines,
        )
        self.assertIn('nvidia_gpu_utilization_ratio{uuid="GPU-1"} 0.15', lines)
        self.assertIn('nvidia_gpu_memory_used_bytes{uuid="GPU-1"} 584056832', lines)
        self.assertIn('nvidia_gpu_power_draw_watts{uuid="GPU-1"} 34.52', lines)
        self.assertIn('nvidia_gpu_clock_graphics_hertz{uuid="GPU-1"} 1755000000', lines)

    def test_skips_values_the_gpu_does_not_report(self):
        lines, _ = self.run_script()
        self.assertFalse(
            any(line.startswith("nvidia_gpu_fan_speed_ratio") for line in lines),
        )

    def test_leaves_no_temporary_file(self):
        _, names = self.run_script()
        self.assertEqual(names, ["bin", "nvidia-gpu.prom"])


if __name__ == "__main__":
    unittest.main()
