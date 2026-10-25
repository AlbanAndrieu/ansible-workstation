#!/usr/bin/env python3
"""Offline contracts: project locking, non-destructive shells, secure Ansible."""
from pathlib import Path
import configparser
import os
import subprocess
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/uv-project.sh"


class UvAndAnsibleContract(unittest.TestCase):
    def test_project_metadata(self):
        with (ROOT / "pyproject.toml").open("rb") as source:
            project = tomllib.load(source)["project"]
        self.assertEqual(project["name"], "ansible-workstation")
        self.assertEqual(project["requires-python"], ">=3.12,<3.15")
        self.assertTrue(
            any(
                name.startswith("ansible-core>=2.21")
                for name in project["dependencies"]
            )
        )

    def test_no_empty_lockfile_can_be_committed(self):
        path = ROOT / "uv.lock"
        if not path.exists():
            return  # Pending reviewed resolution with "mise run lock".
        with path.open("rb") as source:
            names = {p.get("name") for p in tomllib.load(source).get("package", [])}
        self.assertTrue({"ansible-core", "pytest", "ruff"} <= names)

    def test_external_environment_override_refused_without_uv(self):
        env = os.environ.copy()
        env["UV_PROJECT_ENVIRONMENT"] = "/usr/local"
        result = subprocess.run(
            ["bash", str(SCRIPT), "info"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("UV_PROJECT_ENVIRONMENT", result.stderr)

    def test_precommit_must_not_sync_or_mutate_on_commit(self):
        text = (ROOT / ".pre-commit-config.yaml").read_text()
        self.assertNotIn("      - id: uv-sync", text)
        for hook in ("uv-lock", "uv-export", "pre-commit-update"):
            section = text.split("      - id: " + hook + "\n", 1)
            self.assertEqual(len(section), 2, hook)
            self.assertIn("stages: [manual]", section[1].split("\n      - id:", 1)[0])

    def test_precommit_diagnose_is_read_only_and_reports_missing_python(self):
        script = ROOT / "scripts/diagnose-pre-commit.sh"
        source = script.read_text()
        self.assertIn("pre-commit installed: NO", source)
        self.assertIn("Project Python: ABSENT", source)
        self.assertIn("git check-ignore --no-index -v", source)
        self.assertNotIn("uv pip install", source)
        self.assertNotIn("pre_commit install", source)
        self.assertNotIn("`", source)
        with (ROOT / "mise.toml").open("rb") as stream:
            config = tomllib.load(stream)
        self.assertEqual(
            config["tasks"]["hooks-diagnose"]["run"],
            "bash scripts/diagnose-pre-commit.sh",
        )

    def test_precommit_repair_is_explicit_and_worktree_scoped(self):
        wrapper = ROOT / "scripts/repair-pre-commit.sh"
        contents = wrapper.read_text()
        self.assertIn('PYTHON="$ROOT/.venv/bin/python"', contents)
        self.assertIn("linked worktree shares hooks", contents)
        self.assertIn('if [ ! -x "$PYTHON" ]', contents)
        self.assertIn('pathlib.Path(sys.prefix).resolve() != venv', contents)
        self.assertIn('"pre-commit==$PIN"', contents)
        self.assertIn('uv pip install --python "$PYTHON"', contents)
        self.assertNotIn("uv sync", contents.split("uv pip install")[1])
        self.assertIn('"$PYTHON" -m pre_commit install', contents)
        with (ROOT / "mise.toml").open("rb") as source:
            config = tomllib.load(source)
        self.assertIn(
            "scripts/repair-pre-commit.sh",
            config["tasks"]["hooks-repair"]["run"],
        )

    def test_ruff_precommit_does_not_use_nonexistent_hook_or_unsafe_fixes(self):
        hooks = (ROOT / ".pre-commit-config.yaml").read_text()
        self.assertNotIn("      - id: ruff-check", hooks)
        self.assertNotIn("args: [--unsafe-fixes]", hooks)
        self.assertIn("args: [--no-fix]", hooks)

    def test_mise_uses_immutable_safe_sync_command(self):
        with (ROOT / "mise.toml").open("rb") as source:
            config = tomllib.load(source)
        self.assertEqual(config["tools"]["uv"], "0.13.5")
        self.assertFalse(config["settings"]["auto_install"])
        self.assertFalse(config["settings"]["python"]["uv_venv_auto"])
        self.assertIn("scripts/uv-project.sh", config["tasks"]["sync"]["run"])
        script = SCRIPT.read_text()
        self.assertIn('uv --project "$ROOT" lock --check', script)
        self.assertIn('if [ -e "$ROOT/.venv" ]', script)
        self.assertIn('uv --project "$ROOT" sync --locked --python 3.12', script)
        self.assertIn('"$ROOT/.venv/bin/ansible" --version', script)

    def test_workflows_do_not_use_system_ansible_fallback(self):
        for filename in ("ci.yml", "ansible-playbook.yml"):
            source = (ROOT / ".github/workflows" / filename).read_text()
            self.assertIn("uv sync --project . --locked", source)
            self.assertNotIn("uv run --no-sync ansible", source)
        syntax = (ROOT / ".github/workflows/ansible-playbook.yml").read_text()
        self.assertIn(".venv/bin/ansible-playbook", syntax)

    def test_secure_ansible_defaults(self):
        config = configparser.ConfigParser(interpolation=None)
        config.read(ROOT / "ansible.cfg")
        self.assertTrue(config.getboolean("defaults", "host_key_checking"))
        self.assertFalse(config.getboolean("galaxy", "ignore_certs"))
        self.assertEqual(config["defaults"]["fact_caching"], "memory")
        self.assertNotIn("log_path", config["defaults"])
        self.assertNotIn("vault_password_file", config["defaults"])
        ssh_args = config["ssh_connection"]["ssh_args"]
        self.assertIn("StrictHostKeyChecking=yes", ssh_args)
        self.assertNotIn("UserKnownHostsFile=/dev/null", ssh_args)


if __name__ == "__main__":
    unittest.main()
