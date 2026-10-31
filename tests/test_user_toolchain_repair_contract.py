"""Contracts for the user toolchain repair helper, using isolated stubs."""

from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/repair-user-toolchain.sh"
NODE_VERSION = "24.22.1"

MISE_STUB = r"""#!/bin/bash
echo "mise $*" >> "$STUB_STATE/calls.log"
case "$1" in
  --version) echo "2026.10.0 linux-x64" ;;
  ls)
    [ -e "$STUB_STATE/global-installed" ] || echo "starship latest (missing)"
    ;;
  which)
    tool="$STUB_STATE/tools/$2"
    [ -x "$tool" ] && echo "$tool" || exit 1
    ;;
  install)
    if [ -z "$2" ]; then
      mkdir -p "$STUB_STATE/tools"
      for t in starship direnv; do
        printf '#!/bin/sh\nexit 0\n' > "$STUB_STATE/tools/$t"
        chmod +x "$STUB_STATE/tools/$t"
      done
      touch "$STUB_STATE/global-installed"
    else
      dir="$HOME/.local/share/mise/installs/node/${2#node@}/bin"
      mkdir -p "$dir"
      printf '#!/bin/sh\nexit 0\n' > "$dir/node"
      cp "$STUB_STATE/npm" "$dir/npm"
      chmod +x "$dir/node" "$dir/npm"
    fi
    ;;
  reshim) ;;
  exec)
    shift
    [ "$1" = "--" ] && shift
    exec "$@"
    ;;
esac
"""

NPM_STUB = r"""#!/bin/bash
echo "npm $*" >> "$STUB_STATE/calls.log"
prefix=""
while [ $# -gt 0 ]; do
  [ "$1" = "--prefix" ] && prefix="$2"
  shift
done
mkdir -p "$prefix/lib/node_modules/openclaw"
touch "$prefix/lib/node_modules/openclaw/openclaw.mjs"
"""

SYSTEMCTL_STUB = r"""#!/bin/bash
echo "systemctl $*" >> "$STUB_STATE/calls.log"
node="$HOME/.local/share/mise/installs/node/NODE_VERSION"
case "$*" in
  "--user cat openclaw-gateway.service")
    echo "[Service]"
    echo "ExecStart=/usr/bin/node --max-old-space-size=16053 \
/old/lib/node_modules/openclaw/dist/index.js gateway --port 18789"
    echo "ExecStart="
    echo "ExecStart=$node/bin/node --max-old-space-size=16053 \
$node/lib/node_modules/openclaw/openclaw.mjs gateway --port 18789"
    ;;
  "--user is-active --quiet openclaw-gateway.service")
    [ -e "$STUB_STATE/restarted" ] || exit 3
    ;;
  "--user --failed --no-legend --plain")
    [ -n "$STUB_NO_FAILED" ] || echo "bitcoin-qt.service loaded failed failed x"
    ;;
  "--user restart openclaw-gateway.service") touch "$STUB_STATE/restarted" ;;
esac
""".replace("NODE_VERSION", NODE_VERSION)


class UserToolchainRepairContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="nabla-toolchain-")
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.home = base / "home"
        self.state = base / "state"
        self.checkout = base / "checkout"
        self.bin = base / "bin"
        for path in (self.home, self.state, self.checkout / "scripts", self.bin):
            path.mkdir(parents=True)
        shutil.copyfile(SCRIPT, self.checkout / "scripts" / SCRIPT.name)
        self._exe(self.checkout / "scripts/uv-project.sh", "#!/bin/sh\nexit 0\n")
        self._exe(self.checkout / ".venv/bin/python", "#!/bin/sh\nexit 0\n")
        self._exe(self.bin / "mise", MISE_STUB)
        self._exe(self.bin / "systemctl", SYSTEMCTL_STUB)
        self._exe(self.state / "npm", NPM_STUB)

    @staticmethod
    def _exe(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(0o755)

    def run_helper(self, action, **extra):
        env = {
            "HOME": str(self.home),
            "PATH": f"{self.bin}{os.pathsep}/usr/bin:/bin",
            "STUB_STATE": str(self.state),
            "MIN_FREE_GB": "0",
            "OPENCLAW_RESTART_WAIT": "0",
        }
        env.update(extra)
        return subprocess.run(
            ["/bin/bash", "scripts/repair-user-toolchain.sh", action],
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

    def test_check_is_read_only_and_redacts_execstart(self):
        result = self.run_helper("check")
        self.assertEqual(result.returncode, 1, result.stderr)
        out = result.stdout
        self.assertIn("WARN: starship not installed by mise", out)
        self.assertIn("gateway OpenClaw entrypoint missing", out)
        self.assertIn("failed user unit: bitcoin-qt.service", out)
        self.assertNotIn("--max-old-space-size", out)
        self.assertNotIn("18789", out)
        calls = self.calls()
        self.assertNotIn("mise install", calls)
        self.assertNotIn("npm ", calls)
        self.assertNotIn("restart", calls)

    def test_apply_reinstalls_pinned_gateway_with_allowlist(self):
        result = self.run_helper("apply", STUB_NO_FAILED="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.calls()
        prefix = self.home / f".local/share/mise/installs/node/{NODE_VERSION}"
        self.assertIn("mise install\n", calls)
        self.assertIn(f"mise install node@{NODE_VERSION}", calls)
        self.assertIn(
            f"npm install -g --prefix {prefix} "
            "--allow-scripts=openclaw,koffi,esbuild openclaw@2026.10.7",
            calls,
        )
        self.assertLess(calls.index("npm install"), calls.index("--user restart"))
        self.assertIn("PASS: gateway OpenClaw entrypoint present", result.stdout)
        self.assertIn("PASS: starship resolved by mise", result.stdout)

    def test_refuses_unpinned_or_wildcard_inputs(self):
        for extra in (
            {"OPENCLAW_VERSION": "latest"},
            {"NPM_ALLOW_SCRIPTS": "*"},
            {"OPENCLAW_UNIT": "x;reboot"},
        ):
            with self.subTest(extra=extra):
                result = self.run_helper("apply", **extra)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(self.calls(), "")

    def test_apply_refuses_without_free_space(self):
        result = self.run_helper("apply", MIN_FREE_GB="999999")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("mise install", self.calls())

    def test_static_safety(self):
        source = SCRIPT.read_text()
        self.assertIn("set -euo pipefail", source)
        self.assertIn('if [ "$(id -u)" -eq 0 ]; then', source)
        self.assertIn('--allow-scripts="${NPM_ALLOW_SCRIPTS}"', source)
        self.assertIn('OPENCLAW_VERSION="${OPENCLAW_VERSION:-2026.10.7}"', source)
        self.assertIn('ACTION="${1:-check}"', source)
        for line in source.splitlines():
            code = line.split("#", 1)[0] if line.lstrip().startswith("#") else line
            code = re.sub(r"'[^']*'|\"[^\"]*\"", "", code)
            with self.subTest(line=line):
                self.assertIsNone(re.search(r"\b(sudo|curl|wget)\b", code))
                self.assertIsNone(re.search(r"\|\s*(ba)?sh\b", code))

    def test_mise_tasks_expose_check_and_explicit_repair(self):
        with (ROOT / "mise.toml").open("rb") as stream:
            tasks = tomllib.load(stream)["tasks"]
        self.assertEqual(
            tasks["toolchain-check"]["run"],
            "bash scripts/repair-user-toolchain.sh check",
        )
        self.assertEqual(
            tasks["toolchain-repair"]["run"],
            "bash scripts/repair-user-toolchain.sh apply",
        )


if __name__ == "__main__":
    unittest.main()
