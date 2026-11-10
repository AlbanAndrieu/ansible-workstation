"""Offline guardrails for the opt-in Howdy / motion camera split playbook."""

from pathlib import Path
import re
import tomllib
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "playbooks/howdy-cameras.yml"
WRITE_MODULES = {
    "ansible.builtin.copy",
    "ansible.builtin.lineinfile",
    "ansible.builtin.template",
    "ansible.builtin.blockinfile",
    "ansible.builtin.file",
    "ansible.builtin.apt",
    "ansible.builtin.systemd_service",
}


def play():
    return yaml.safe_load(PLAYBOOK.read_text())[0]


def module_of(task):
    return next(k for k in task if k.startswith("ansible.builtin."))


class HowdyCamerasContracts(unittest.TestCase):
    def test_read_only_by_default_with_two_approvals(self):
        doc = play()
        self.assertFalse(doc["become"])
        self.assertFalse(doc["vars"]["howdy_cameras_apply"])
        self.assertFalse(doc["vars"]["howdy_cameras_apply_approved"])
        self.assertEqual(doc["vars"]["howdy_camera_device"], "")
        self.assertEqual(doc["vars"]["motion_camera_device"], "")

    def test_every_write_is_gated_and_privileged_only_when_applying(self):
        for task in play()["tasks"]:
            module = module_of(task)
            gated = "howdy_cameras_write | bool" in str(task.get("when", ""))
            with self.subTest(task=task["name"]):
                if module in WRITE_MODULES or task.get("become"):
                    self.assertTrue(gated, "write or sudo task without apply gate")

    def test_never_edits_pam(self):
        source = PLAYBOOK.read_text()
        self.assertNotIn("pam-auth-update --", source)
        for task in play()["tasks"]:
            args = task[module_of(task)]
            if module_of(task) in WRITE_MODULES and isinstance(args, dict):
                target = str(args.get("path", "")) + str(args.get("dest", ""))
                with self.subTest(task=task["name"]):
                    self.assertNotIn("/etc/pam.d", target)
        self.assertIn("pam_configuration_changed: false", source)

    def test_howdy_stays_inert_with_upstream_certainty(self):
        source = PLAYBOOK.read_text()
        self.assertIn('line: "disabled = true"', source)
        self.assertEqual(play()["vars"]["howdy_certainty"], "3.5")

    def test_cameras_must_be_stable_and_distinct(self):
        source = PLAYBOOK.read_text()
        self.assertIn(
            "motion_camera_device is match('^/dev/v4l/by-(path|id)/')",
            source,
        )
        self.assertIn("howdy_camera_device is match('^/dev/v4l/by-(path|id)/')", source)
        self.assertIn(
            "results[0].stat.lnk_source != howdy_cameras_requested.results[1]",
            source,
        )
        self.assertIsNone(re.search(r"device:\s*\"?/dev/video\d", source))

    def test_motion_autostop_frees_camera_after_each_start(self):
        source = PLAYBOOK.read_text()
        self.assertIn("Wants=motion-autostop.timer", source)
        self.assertIn("PartOf=motion.service", source)
        self.assertIn("OnActiveSec={{ motion_autostop_after }}", source)
        self.assertIn("RemainAfterElapse=no", source)
        self.assertIn("Conflicts=motion.service", source)
        self.assertEqual(play()["vars"]["motion_autostop_after"], "5min")

    def test_ppa_is_reused_and_pinned_never_added(self):
        source = PLAYBOOK.read_text()
        self.assertNotIn("apt_repository", source)
        self.assertNotIn("deb822_repository", source)
        self.assertIn("Pin-Priority: 100", source)
        self.assertIn("backrefs: true", source)

    def test_global_role_no_longer_installs_howdy(self):
        webcam = (ROOT / "tasks/webcam.yml").read_text()
        self.assertNotIn('repo: "ppa:boltgolt/howdy"', webcam)
        self.assertNotIn("howdy.conf.j2", webcam)
        defaults = (ROOT / "defaults/main.yml").read_text()
        self.assertNotIn("howdy_enabled: true", defaults)
        role_files = [ROOT / "workstation.yml", *sorted((ROOT / "tasks").glob("*.yml"))]
        for path in role_files:
            with self.subTest(path=path.name):
                self.assertNotRegex(
                    path.read_text(),
                    r"(import|include)_(tasks|playbook|role):.*howdy",
                )

    def test_mise_tasks(self):
        with (ROOT / "mise.toml").open("rb") as stream:
            tasks = tomllib.load(stream)["tasks"]
        self.assertIn(
            "--syntax-check playbooks/howdy-cameras.yml",
            tasks["howdy-cameras-syntax"]["run"],
        )
        audit = tasks["howdy-cameras-audit"]["run"]
        self.assertIn("playbooks/howdy-cameras.yml", audit)
        self.assertNotIn("howdy_cameras_apply", audit)
        self.assertNotIn(" -K", audit)


if __name__ == "__main__":
    unittest.main()
