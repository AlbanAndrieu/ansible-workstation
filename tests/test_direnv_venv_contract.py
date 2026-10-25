#!/usr/bin/env python3
"""Offline venv lifecycle contracts: direnv never installs packages or erases data."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DirenvVenvContract(unittest.TestCase):
    def test_direnv_creates_only_empty_local_venv(self):
        text = (ROOT / ".envrc").read_text()
        self.assertIn('bash "$PWD/scripts/ensure-direnv-venv.sh"', text)
        self.assertIn('export VIRTUAL_ENV="$PWD/.venv"', text)
        self.assertIn('PATH_add "$VIRTUAL_ENV/bin"', text)
        for forbidden in ("uv sync", "pip install", "curl ", "wget ",
                          "source .env.secrets", "pre-commit install"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)

        helper = (ROOT / "scripts/ensure-direnv-venv.sh").read_text()
        self.assertIn("uv venv --offline --no-python-downloads", helper)
        self.assertNotIn("uv sync", helper.replace(
            "# No Python downloads, no network, no uv sync, no package install.",
            "",
        ).replace(
            "# Never overwrite an existing environment. A first-time empty venv is safe",
            "",
        ).replace(
            "# to sync later using the separately guarded 'mise run sync' task.",
            "",
        ))
        self.assertIn('touch "$MARKER"', helper)
        self.assertIn('if [ -e "$VENV" ] || [ -L "$VENV" ]; then', helper)

    def test_explicit_mise_tasks(self):
        with (ROOT / "mise.toml").open("rb") as source:
            cfg = tomllib.load(source)
        self.assertEqual(
            cfg["tasks"]["init"]["run"], "bash scripts/bootstrap-workstation.sh"
        )
        self.assertEqual(
            cfg["tasks"]["recover-venv"]["run"],
            "bash scripts/recover-workstation-venv.sh",
        )
        self.assertIn("scripts/uv-project.sh", cfg["tasks"]["sync"]["run"])
        init = (ROOT / "scripts/bootstrap-workstation.sh").read_text()
        self.assertIn('"$ROOT/scripts/uv-project.sh" sync', init)
        self.assertIn('"$ROOT/scripts/repair-pre-commit.sh"', init)
        self.assertIn("set -euo pipefail", init)

    def test_recover_preserves_corrupted_environment(self):
        with tempfile.TemporaryDirectory(prefix="ansible-venv-") as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            scripts.mkdir()
            script = scripts / "recover-workstation-venv.sh"
            shutil.copyfile(ROOT / "scripts/recover-workstation-venv.sh", script)
            broken = root / ".venv"
            broken.mkdir()
            (broken / "preserve-this-file").write_text("DO NOT DELETE")
            result = subprocess.run(
                ["/bin/bash", str(script)],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(broken.exists())
            archived = list(root.glob(".venv.incomplete-*"))
            self.assertEqual(len(archived), 1)
            self.assertEqual(
                (archived[0] / "preserve-this-file").read_text(),
                "DO NOT DELETE",
            )

    def test_recover_refuses_working_environment(self):
        with tempfile.TemporaryDirectory(prefix="ansible-valid-venv-") as tmp:
            root = Path(tmp)
            scripts = root / "scripts"
            scripts.mkdir()
            script = scripts / "recover-workstation-venv.sh"
            shutil.copyfile(ROOT / "scripts/recover-workstation-venv.sh", script)
            env = root / ".venv"
            (env / "bin").mkdir(parents=True)
            (env / "pyvenv.cfg").write_text("home = /usr/bin\n")
            py = env / "bin/python"
            py.write_text("#!/bin/sh\nexit 0\n")
            py.chmod(0o755)
            result = subprocess.run(
                ["/bin/bash", str(script)],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            self.assertEqual(result.returncode, 2)
            self.assertTrue(py.exists())
            self.assertEqual(list(root.glob(".venv.incomplete-*")), [])

    def test_existing_broken_venv_is_not_overwritten_by_direnv(self):
        with tempfile.TemporaryDirectory(prefix="ansible-envrc-") as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            scripts.mkdir()
            script = scripts / "ensure-direnv-venv.sh"
            shutil.copyfile(ROOT / "scripts/ensure-direnv-venv.sh", script)
            invalid = root / ".venv"
            invalid.mkdir()
            (invalid / "keep").write_text("unaltered")
            result = subprocess.run(
                ["/bin/bash", str(script)],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual((invalid / "keep").read_text(), "unaltered")
            self.assertFalse((invalid / ".ansible-workstation-uv-managed").exists())

    def test_ignore_archived_environments(self):
        gitignore = (ROOT / ".gitignore").read_text()
        self.assertIn(".venv.incomplete-*/", gitignore)


if __name__ == "__main__":
    unittest.main()
