"""Prove current-shell Direnv acceptance using isolated Bash fixtures."""

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


HELPER = Path(__file__).resolve().parents[1] / "scripts/verify-direnv-shell.sh"


class DirenvShellVerifyContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="nabla-direnv-verify-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "checkout"
        scripts = self.root / "scripts"
        scripts.mkdir(parents=True)
        shutil.copyfile(HELPER, scripts / HELPER.name)
        self.venv = self.root / ".venv"
        (self.venv / "bin").mkdir(parents=True)
        (self.venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
        for name in ("python", "ansible"):
            command = self.venv / "bin" / name
            command.write_text("#!/bin/sh\nexit 0\n")
            command.chmod(0o755)

    def run_shell(self, *, interactive=True, define_hook=True,
                  venv=True, venv_on_path=True, bad_prompt=False, source=True):
        env = os.environ.copy()
        env["HOME"] = self.tmp.name
        env["BASH_ENV"] = "/dev/null"
        env["PATH"] = (
            (str(self.venv / "bin") + os.pathsep if venv_on_path else "")
            + "/usr/bin:/bin"
        )
        if venv:
            env["VIRTUAL_ENV"] = str(self.venv)
        else:
            env.pop("VIRTUAL_ENV", None)
        pre = "_direnv_hook() { :; }\n" if define_hook else ""
        cmd = (
            pre + "PROMPT_COMMAND='_direnv_hook'\n"
            + ("PS1='_mise_hookhistory'\n" if bad_prompt else "PS1='$ '\n")
            + ("source scripts/verify-direnv-shell.sh\n" if source
               else "bash scripts/verify-direnv-shell.sh\n")
        )
        argv = ["/bin/bash", "--noprofile", "--norc"]
        if interactive:
            argv.append("-i")
        argv += ["-c", cmd]
        return subprocess.run(argv, cwd=self.root, env=env, text=True,
                              capture_output=True, check=False, timeout=10)

    def test_valid_interactive_shell(self):
        result = self.run_shell()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS: interactive Direnv", result.stdout)

    def test_missing_prompt_hook_fails_closed(self):
        result = self.run_shell(define_hook=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL: Direnv", result.stderr)

    def test_global_python_or_ansible_fails_closed(self):
        result = self.run_shell(venv_on_path=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("outside the project venv", result.stderr)

    def test_missing_venv_activation_fails_closed(self):
        result = self.run_shell(venv=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("VIRTUAL_ENV", result.stderr)

    def test_invalid_mise_history_token_fails(self):
        result = self.run_shell(bad_prompt=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("malformed mise/history token", result.stderr)

    def test_noninteractive_shell_fails(self):
        result = self.run_shell(interactive=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not interactive", result.stderr)

    def test_refuses_execution_in_a_subprocess(self):
        result = self.run_shell(source=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("REFUSED: source", result.stderr)

    def test_source_does_not_invoke_install_or_mutate_files(self):
        source = HELPER.read_text()
        for forbidden in ("uv sync", "mise install", "git reset",
                          "rm -rf", "ansible-playbook", "curl ",
                          "direnv allow", "eval $(direnv"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        result = self.run_shell()
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
