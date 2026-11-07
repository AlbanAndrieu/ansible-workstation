"""Contracts for the Docker health textfile writer, using a docker stub."""

from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "files/docker-health-textfile.sh"

DOCKER_STUB = r"""#!/bin/bash
case "${@: -1}" in
  postgres) echo healthy ;;
  redis) echo unhealthy ;;
  web) echo running ;;
  *) echo "Error: No such object" >&2; exit 1 ;;
esac
"""


class DockerHealthTextfileContracts(unittest.TestCase):
    def run_script(self, *containers):
        tmp = Path(tempfile.mkdtemp())
        stub = tmp / "bin/docker"
        stub.parent.mkdir()
        stub.write_text(DOCKER_STUB)
        stub.chmod(0o755)
        out = tmp / "docker-health.prom"
        env = {**os.environ, "PATH": f"{stub.parent}:{os.environ['PATH']}"}
        subprocess.run(["/bin/bash", SCRIPT, out, *containers], env=env, check=True)
        return out, sorted(p.name for p in tmp.iterdir())

    def test_only_healthy_containers_report_one(self):
        out, _ = self.run_script("postgres", "redis", "web", "gone")
        lines = out.read_text().splitlines()
        self.assertIn('workstation_container_healthy{container="postgres"} 1', lines)
        self.assertIn('workstation_container_healthy{container="redis"} 0', lines)
        self.assertIn('workstation_container_healthy{container="web"} 0', lines)
        self.assertIn('workstation_container_healthy{container="gone"} 0', lines)

    def test_leaves_no_temporary_file(self):
        _, names = self.run_script("postgres")
        self.assertEqual(names, ["bin", "docker-health.prom"])


if __name__ == "__main__":
    unittest.main()
