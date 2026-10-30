"""Hermetic, read-only contracts for repository-scoped Ansible agent skills."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check-agent-skills.py"
SPEC = importlib.util.spec_from_file_location("workstation_agent_skills", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
SKILLS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SKILLS)


def fixture(root: Path, installed: bool = True) -> None:
    for relative, (heading, markers) in SKILLS.POLICIES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(heading + "\n" + "\n".join(markers) + "\n", encoding="utf-8")
    if not installed:
        return
    data = {"version": 1, "skills": {}}
    for name, source_path in SKILLS.EXPECTED.items():
        canonical = root / ".agents/skills" / name
        canonical.mkdir(parents=True)
        (canonical / "SKILL.md").write_text("# synthetic skill fixture\n", encoding="utf-8")
        data["skills"][name] = {
            "source": SKILLS.SOURCE,
            "sourceType": "github",
            "skillPath": source_path,
            "computedHash": "a" * 64,
        }
        for prefix, base in SKILLS.ALIASES.items():
            alias = root / prefix / name
            alias.parent.mkdir(parents=True, exist_ok=True)
            alias.symlink_to(f"{base}/{name}", target_is_directory=True)
    (root / "skills-lock.json").write_text(json.dumps(data), encoding="utf-8")


class AgentSkillsContract(unittest.TestCase):
    def test_healthy_vendor_layout(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fixture(root)
            self.assertEqual(SKILLS.audit(root), ("installed", []))
            self.assertEqual(SKILLS.main(["--root", str(root)]), 0)

    def test_empty_installation_is_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fixture(root, installed=False)
            self.assertEqual(SKILLS.audit(root), ("not_installed", []))

    def test_installed_without_lock_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fixture(root)
            (root / "skills-lock.json").unlink()
            self.assertTrue(any("without skills-lock" in x for x in SKILLS.audit(root)[1]))

    def test_missing_and_wrong_aliases_fail(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fixture(root)
            (root / "skills/ansible-validator").unlink()
            wrong = root / ".claude/skills/ansible-generator"
            wrong.unlink()
            wrong.symlink_to("../../../tmp/elsewhere")
            issues = SKILLS.audit(root)[1]
            self.assertTrue(any("skills/ansible-validator" in x for x in issues))
            self.assertTrue(any(".claude/skills/ansible-generator" in x for x in issues))

    def test_alias_directory_is_not_accepted_as_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fixture(root)
            alias = root / ".hermes/skills/ansible-generator"
            alias.unlink()
            alias.mkdir()
            self.assertTrue(any(".hermes/skills/ansible-generator" in x
                                for x in SKILLS.audit(root)[1]))

    def test_unknown_source_and_bad_hash_fail(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fixture(root)
            lock = root / "skills-lock.json"
            data = json.loads(lock.read_text())
            data["skills"]["ansible-generator"]["source"] = "other/untrusted"
            data["skills"]["ansible-validator"]["computedHash"] = "not-a-hash"
            lock.write_text(json.dumps(data))
            issues = SKILLS.audit(root)[1]
            self.assertTrue(any("provenance mismatch" in x for x in issues))
            self.assertTrue(any("computedHash" in x for x in issues))

    def test_unreviewed_skill_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fixture(root)
            lock = root / "skills-lock.json"
            data = json.loads(lock.read_text())
            data["skills"]["new-unreviewed"] = data["skills"]["ansible-validator"]
            lock.write_text(json.dumps(data))
            self.assertTrue(any("unreviewed skill" in x for x in SKILLS.audit(root)[1]))

    def test_missing_policy_marker_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fixture(root)
            path = root / "docs/agent-skills-workstation.md"
            path.write_text(path.read_text().replace("no automatic apply", "apply"))
            self.assertTrue(any("no automatic apply" in x for x in SKILLS.audit(root)[1]))

    def test_invalid_manifest_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fixture(root)
            (root / "skills-lock.json").write_text("{invalid json", encoding="utf-8")
            self.assertEqual(SKILLS.audit(root)[0], "invalid_manifest")
            self.assertEqual(SKILLS.main(["--root", str(root)]), 2)

    def test_check_does_not_mutate_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fixture(root)
            before = {str(p.relative_to(root)): p.read_bytes()
                      for p in root.rglob("*") if p.is_file()}
            self.assertEqual(SKILLS.audit(root), ("installed", []))
            after = {str(p.relative_to(root)): p.read_bytes()
                     for p in root.rglob("*") if p.is_file()}
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
