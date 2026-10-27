#!/usr/bin/env python3
"""Offline lockfile and generated-cache safeguards for mise, uv and npm."""

import json
from pathlib import Path
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LockfileContract(unittest.TestCase):
    def test_mise_lock_matches_declarations(self):
        with (ROOT / "mise.toml").open("rb") as stream:
            tools = tomllib.load(stream)["tools"]
        with (ROOT / "mise.lock").open("rb") as stream:
            lock = tomllib.load(stream)["tools"]
        for name in ("node", "python", "uv"):
            with self.subTest(tool=name):
                self.assertIn(name, tools)
                self.assertEqual(len(lock[name]), 1)
                self.assertIn(tools[name], lock[name][0]["specifiers"])
        self.assertEqual(lock["uv"][0]["version"], tools["uv"])

    def test_uv_lock_contains_project_and_toolchain(self):
        with (ROOT / "pyproject.toml").open("rb") as stream:
            metadata = tomllib.load(stream)
        with (ROOT / "uv.lock").open("rb") as stream:
            lock = tomllib.load(stream)
        self.assertGreater(len(lock.get("package", [])), 8)
        packages = {entry["name"] for entry in lock["package"]}
        required = {metadata["project"]["name"], "ansible-core", "ruff", "pytest"}
        self.assertTrue(required.issubset(packages), required - packages)
        self.assertIn("3.12", lock["requires-python"])

    def test_npm_manifest_matches_lockfile(self):
        manifest = json.loads((ROOT / "package.json").read_text())
        lock = json.loads((ROOT / "package-lock.json").read_text())
        self.assertEqual(
            manifest["devDependencies"],
            lock["packages"][""]["devDependencies"],
        )
        self.assertEqual(lock["lockfileVersion"], 3)

    def test_ignore_only_generated_caches(self):
        entries = set((ROOT / ".gitignore").read_text().splitlines())
        self.assertIn(".node_cache/", entries)
        self.assertIn(".config/requirements-lock.txt", entries)
        self.assertNotIn(".config/", entries)
        for expected in ("mise.lock", "uv.lock", "package-lock.json"):
            self.assertNotIn(expected, entries)


if __name__ == "__main__":
    unittest.main()
