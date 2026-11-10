"""Offline guardrails for the workstation stabilization playbook."""

from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "playbooks/stabilize-workstation.yml"
JOURNALD = ROOT / "files/etc/systemd/journald.conf.d/size.conf"
READ_ONLY = ("ansible.builtin.assert", "ansible.builtin.debug")


def play():
    return yaml.safe_load(PLAYBOOK.read_text())[0]


class StabilizeWorkstationContracts(unittest.TestCase):
    def test_plan_only_by_default(self):
        doc = play()
        self.assertFalse(doc["become"])
        self.assertFalse(doc["vars"]["stabilize_apply"])
        self.assertFalse(doc["vars"]["stabilize_apply_approved"])

    def test_every_change_is_gated(self):
        for task in play()["tasks"]:
            if not any(module in task for module in READ_ONLY):
                with self.subTest(task=task["name"]):
                    self.assertEqual(task.get("when"), "stabilize_write")

    def test_never_mounts_over_existing_docker_data(self):
        names = [task["name"] for task in play()["tasks"]]
        guard = names.index("Refuse to mount over existing Docker data")
        mount = next(
            i for i, task in enumerate(play()["tasks"]) if "ansible.posix.mount" in task
        )
        self.assertLess(guard, mount)
        probe = play()["tasks"][guard - 1]
        self.assertIs(probe["check_mode"], False, probe["name"])

    def test_node_exporter_feeds_the_truenas_heartbeat(self):
        flags = play()["vars"]["stabilize_node_exporter_flags"]
        self.assertIn("--collector.systemd", flags)
        # Both playbooks write ARGS: each flag here must already be in the restic file.
        restic = (ROOT / "files/restic/prometheus-node-exporter.default").read_text()
        self.assertNotIn("--collector.disable-defaults", restic)
        for flag in flags:
            self.assertRegex(restic, rf'[" ]{re.escape(flag)}[ "]')

    def test_nfs_mounts_on_access_and_gives_up_when_truenas_is_down(self):
        opts = play()["vars"]["stabilize_nfs_opts"].split(",")
        self.assertIn("x-systemd.automount", opts)
        self.assertTrue(any(o.startswith("x-systemd.idle-timeout=") for o in opts))
        self.assertTrue(any(o.startswith("x-systemd.mount-timeout=") for o in opts))
        # bg makes systemd-fstab-generator wait forever (TimeoutSec=infinity).
        self.assertNotIn("bg", opts)
        defaults = yaml.safe_load((ROOT / "defaults/main.yml").read_text())
        self.assertEqual(defaults["mount_nfs_opts"], ",".join(opts))

    def test_refuses_to_reload_systemd_while_truenas_nfs_is_down(self):
        tasks = play()["tasks"]
        guard = next(i for i, t in enumerate(tasks) if "ansible.builtin.wait_for" in t)
        self.assertEqual(tasks[guard]["ansible.builtin.wait_for"]["port"], 2049)
        reloads = [
            i
            for i, t in enumerate(tasks)
            if "notify" in t or "ansible.builtin.apt" in t or "daemon_reload" in str(t)
        ]
        self.assertLess(guard, min(reloads))

    def test_gpu_metrics_land_in_the_scraped_textfile_directory(self):
        self.assertIn(
            "/var/lib/prometheus/node-exporter/nvidia-gpu.prom",
            PLAYBOOK.read_text(),
        )
        self.assertIn(
            "--collector.textfile.directory=/var/lib/prometheus/node-exporter",
            play()["vars"]["stabilize_node_exporter_flags"],
        )

    def test_ollama_tuning_survives_upgrades_and_holds_no_secret(self):
        dropin = ROOT / "files/etc/systemd/system/ollama.service.d/workstation.conf"
        self.assertIn('"OLLAMA_MODELS=/data/models/ollama"', dropin.read_text())
        self.assertNotIn("OLLAMA_API_KEY=", dropin.read_text())
        # install.sh rewrites the unit: tuning put there is lost at the next upgrade.
        unit = ROOT / "files/etc/systemd/system/ollama.service"
        self.assertNotIn("OLLAMA_", unit.read_text())

    def test_apache_serves_neither_dotfiles_nor_the_site_checkout(self):
        apache = ROOT / "files/etc/apache2"
        security = (apache / "conf-available/security.conf").read_text()
        deny = re.search(r'^RedirectMatch 404 "(.+)"$', security, re.M).group(1)
        for path in (
            "/.git/HEAD",
            "/.envrc",
            "/.venv/bin/x",
            "/api/info.php",
            "/api/php.ini",
        ):
            self.assertRegex(path, deny)
        for path in (
            "/.well-known/acme-challenge/x",
            "/public/index.html",
            "/info.php.txt",
        ):
            self.assertNotRegex(path, deny)
        self.assertIn("ServerTokens Prod", security.splitlines())
        site = (apache / "sites-available/000-default.conf").read_text()
        self.assertNotRegex(site, r"DocumentRoot /var/www/nabla-site-apache/\s")
        for name in play()["vars"]["stabilize_apache_files"]:
            self.assertTrue((apache / name).is_file(), name)

    def test_writeback_is_capped_in_bytes(self):
        conf = (ROOT / "files/etc/sysctl.d/99-ai-workstation.conf").read_text()
        settings = dict(
            line.replace(" ", "").split("=")
            for line in conf.splitlines()
            if line and not line.startswith("#")
        )
        self.assertLessEqual(int(settings["vm.dirty_bytes"]), 1 << 30)
        self.assertLess(
            int(settings["vm.dirty_background_bytes"]),
            int(settings["vm.dirty_bytes"]),
        )
        # A ratio set later in the file would silently zero the byte limit.
        self.assertNotIn("vm.dirty_ratio", settings)

    def test_journald_keeps_more_than_a_day(self):
        self.assertIn("SystemMaxUse=2G", JOURNALD.read_text().splitlines())
        self.assertIn("journald.conf.d/size.conf", PLAYBOOK.read_text())


if __name__ == "__main__":
    unittest.main()
