"""Offline guardrails for the security scan timers and the root job cleanup."""

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "playbooks/security-scans.yml"
SCAN = ROOT / "files/security-scan.sh"
PUBLISH = ROOT / "files/publish-security-reports.sh"
READ_ONLY = ("ansible.builtin.assert", "ansible.builtin.debug", "ansible.builtin.meta")
# The root crontab as found on 16/11/2026 (secrets-free).
ROOT_CRONTAB = [
    "5 10 * * 0 /etc/webmin/package-updates/update.pl",
    "0 2 * * 0 /usr/local/lynis/lynis audit system | ansi2html -l > /var/www/r.html",
    "0 4 * * 0 oscap xccdf eval --profile x --report /var/www/r.html ssg-ds.xml",
    "0 * * * * /home/albandrieu/w/nabla/env/linux/run-perf-monitoring.sh >> /x.log",
    "0 3 * * * /home/albandrieu/w/nabla/env/linux/run-audit-log-cleanup.sh",
    "0 0 1 * * rm -f /var/log/audit/audit.log.* > /var/log/cron-auditd.log",
    "30 23 * * 1 /home/albandrieu/.linuxbrew/bin/pgbadger -q -o /var/www/r/ p.log",
    "0 1 * * 6 /usr/local/sbin/clamav-scan-local-disks",
]
KEPT = ['MAILTO=""', "0 1 * * * /usr/bin/speedtest --accept-license --accept-gdpr"]


def play():
    return yaml.safe_load(PLAYBOOK.read_text())[0]


def stub_bin(tmp, scripts):
    bin_dir = Path(tmp) / "bin"
    bin_dir.mkdir()
    for name, body in scripts.items():
        path = bin_dir / name
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o755)
    return bin_dir


class SecurityScansContracts(unittest.TestCase):
    def test_plan_only_by_default(self):
        doc = play()
        self.assertFalse(doc["become"])
        self.assertFalse(doc["vars"]["security_scans_apply"])
        self.assertFalse(doc["vars"]["security_scans_apply_approved"])

    def test_every_change_is_gated(self):
        for task in play()["tasks"]:
            if any(k in task for k in READ_ONLY):
                continue
            with self.subTest(task=task["name"]):
                self.assertEqual(task["when"], "security_scans_write")

    def test_root_cron_drops_every_dangerous_line_and_keeps_the_rest(self):
        drop = play()["vars"]["security_scans_root_cron_drop"]
        for line in ROOT_CRONTAB:
            with self.subTest(line=line):
                self.assertTrue(any(re.search(r, line) for r in drop))
        for line in KEPT:
            with self.subTest(line=line):
                self.assertFalse(any(re.search(r, line) for r in drop))

    def test_boot_keeps_recent_motion_and_rearms_dead_automounts(self):
        text = (ROOT / "templates/boot-update.sh-Ubuntu.j2").read_text()
        self.assertIn("-mtime +10 -delete", text)
        self.assertNotIn("rm -f /workspace/Dropbox/motion/*", text)
        self.assertIn("systemctl list-units --failed --type=mount", text)
        self.assertIn('systemctl reset-failed "${mount}"', text)
        self.assertIn('systemctl start "${automount}"', text)

    def test_no_root_unit_runs_a_user_editable_file(self):
        text = (ROOT / "templates/boot-update.sh-Ubuntu.j2").read_text()
        boot = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        )
        for needle in (
            "/home/",
            "albandrieu30",
            "mr update",
            "brew",
            "docker compose",
            "startconky",
        ):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, boot)
        units = PLAYBOOK.read_text()
        self.assertIn("User={{ security_scans_user }}", units)

    def test_one_timer_per_scanner_without_overlap(self):
        schedule = play()["vars"]["security_scans_schedule"]
        self.assertEqual(set(schedule), {"lynis", "rkhunter", "clamav", "openscap"})
        self.assertEqual(len(set(schedule.values())), len(schedule))

    def test_clamav_scans_local_disks_only_through_clamd(self):
        mounts = "\n".join(
            [
                "/ /",
                "/var/snap/firefox/common/host-hunspell /usr/share/hunspell",
                "/data /",
                "/workspace /",
                "/run/media/albandrieu/NABLA_ESCROW /",
                "/var/lib/containerd /containerd",
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            calls = Path(tmp) / "calls"
            bin_dir = stub_bin(
                tmp,
                {
                    "findmnt": f"printf '%s\\n' '{mounts}'",
                    "systemctl": (
                        f'echo "systemctl $*" >>{calls}; '
                        '[ "$1" != is-active ] || exit 3'
                    ),
                    "clamdscan": f'echo "clamdscan $*" >>{calls}',
                    "chgrp": "true",
                },
            )
            conf = Path(tmp) / "clamd.conf"
            conf.write_text("LocalSocket /var/run/clamav/clamd.ctl\n")
            env = {
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "SECURITY_REPORTS_DIR": f"{tmp}/reports",
                "SECURITY_METRICS_DIR": tmp,
                "CLAMD_CONF": str(conf),
            }
            subprocess.run(
                ["bash", SCAN, "clamav"],
                env=env,
                check=True,
                capture_output=True,
            )
            log = calls.read_text().splitlines()
            metrics = (Path(tmp) / "security_clamav.prom").read_text()
        scan = next(line for line in log if "--multiscan" in line).split()
        self.assertEqual(scan[-3:], ["/", "/data", "/workspace"])
        self.assertIn("systemctl start clamav-daemon", log)
        self.assertEqual(log[-1], "systemctl stop clamav-daemon")
        self.assertIn("security_clamav_infected_files 0", metrics)

    def test_clamav_refuses_a_tcp_only_clamd(self):
        # Over TCP --fdpass is ignored and clamd, as user clamav, reads nothing.
        with tempfile.TemporaryDirectory() as tmp:
            calls = Path(tmp) / "calls"
            bin_dir = stub_bin(
                tmp,
                {
                    "findmnt": "echo '/ /'",
                    "systemctl": f'echo "systemctl $*" >>{calls}',
                    "clamdscan": f'echo "clamdscan $*" >>{calls}',
                    "chgrp": "true",
                },
            )
            conf = Path(tmp) / "clamd.conf"
            conf.write_text("TCPSocket 3310\nTCPAddr 127.0.0.1\n")
            env = {
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "SECURITY_REPORTS_DIR": f"{tmp}/reports",
                "SECURITY_METRICS_DIR": tmp,
                "CLAMD_CONF": str(conf),
            }
            result = subprocess.run(
                ["bash", SCAN, "clamav"],
                env=env,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 78)
            self.assertFalse(calls.exists() and "clamdscan" in calls.read_text())
            receipts = list(Path(tmp, "reports").glob("*/.scan-clamav.json"))
            self.assertEqual(
                json.loads(receipts[0].read_text()),
                {"tool": "clamav", "state": "INCOMPLETE"},
            )

    def test_audit_rules_are_keyed_watches_and_never_lock(self):
        rules = [
            line
            for line in (ROOT / "files/audit-workstation.rules")
            .read_text()
            .splitlines()
            if line.strip() and not line.startswith("#")
        ]
        self.assertTrue(rules)
        for line in rules:
            self.assertRegex(
                line,
                r"^(-w /\S+ -p wa|-a always,exit -F arch=b64 -S \S+) -k \w+$",
            )
        self.assertIn("-w /etc/sudoers.d/ -p wa -k privilege", rules)
        copies = [
            task["ansible.builtin.copy"]
            for task in play()["tasks"]
            if "ansible.builtin.copy" in task
        ]
        self.assertIn(
            "/etc/audit/rules.d/50-workstation.rules",
            [copy["dest"] for copy in copies],
        )
        retention = play()["vars"]["security_scans_auditd"]
        self.assertEqual(retention["max_log_file_action"], "ROTATE")
        self.assertGreaterEqual(retention["max_log_file"] * retention["num_logs"], 200)

    def test_harden_os_keeps_the_same_auditd_retention(self):
        # devsec os_hardening templates auditd.conf: its defaults would undo this play.
        harden = yaml.safe_load((ROOT / "playbooks/harden-os.yml").read_text())[0]
        retention = play()["vars"]["security_scans_auditd"]
        for key, value in retention.items():
            with self.subTest(key=key):
                self.assertEqual(harden["vars"][f"os_auditd_{key}"], value)

    def test_openscap_uses_the_packaged_binary(self):
        # /usr/local/bin/oscap (hand-built, broken) shadows the package in PATH.
        self.assertIn('"${OSCAP:-/usr/bin/oscap}" xccdf eval', SCAN.read_text())

    def test_captured_clamd_listens_on_a_unix_socket(self):
        conf = (ROOT / "files/etc/clamav/clamd.conf").read_text()
        self.assertIn("LocalSocket /var/run/clamav/clamd.ctl", conf.splitlines())
        self.assertNotRegex(conf, r"(?m)^TCPSocket ")

    def test_failed_scanner_publishes_incomplete_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = stub_bin(
                tmp,
                {
                    "lynis": 'echo "scan aborted" >&2; exit 9',
                    "chgrp": "true",
                },
            )
            env = {
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "SECURITY_REPORTS_DIR": str(root / "reports"),
                "SECURITY_METRICS_DIR": tmp,
            }
            result = subprocess.run(
                ["bash", SCAN, "lynis"],
                env=env,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 9)
            receipts = list((root / "reports").glob("*/.scan-lynis.json"))
            self.assertEqual(len(receipts), 1)
            self.assertEqual(
                json.loads(receipts[0].read_text()),
                {"tool": "lynis", "state": "INCOMPLETE"},
            )
            self.assertIn(
                "OnFailure=security-reports-publish.service",
                PLAYBOOK.read_text(),
            )

    def test_openscap_content_is_retargeted_to_the_running_release(self):
        text = SCAN.read_text()
        sed = re.search(r'sed "(s/[^"]+)"', text).group(1)
        sed = sed.replace("$(lsb_release -cs)", "resolute").replace("\\\\\\$", "\\$")
        out = subprocess.run(
            ["sed", sed],
            input="<ind:pattern>^DISTRIB_CODENAME=noble$</ind:pattern>",
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertIn("^DISTRIB_CODENAME=resolute$", out)

    def test_publish_copies_reports_and_lists_them_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dest = Path(tmp) / "src", Path(tmp) / "dest"
            for day in ("2026-11-15", "2026-11-16"):
                (src / day).mkdir(parents=True)
                (src / day / "lynis.txt").write_text("ok\n")
            (src / "ssg-ubuntu2404-resolute-ds.xml").write_text("big\n")
            env = {
                **os.environ,
                "SECURITY_REPORTS_DIR": str(src),
                "SECURITY_PUBLISH_DIR": str(dest),
            }
            subprocess.run(["bash", PUBLISH], env=env, check=True, capture_output=True)
            index = (dest / "index.html").read_text()
            self.assertTrue((dest / "2026-11-16/lynis.txt").exists())
            self.assertFalse((dest / "ssg-ubuntu2404-resolute-ds.xml").exists())
        self.assertLess(index.index("2026-11-16"), index.index("2026-11-15"))
        self.assertIn('href="2026-11-16/lynis.txt"', index)

    def test_invalid_scan_receipt_never_claims_a_complete_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "source"
            dest = root / "dest"
            day = src / "2026-11-22"
            day.mkdir(parents=True)
            dest.mkdir()
            (day / "rkhunter-warnings.txt").write_text(
                "Warning: private-hostname.local\n",
            )
            (day / ".scan-rkhunter.json").write_text(
                '{"tool":"unexpected","state":"COMPLETE"}\n',
            )
            subprocess.run(
                [
                    "python3",
                    str(ROOT / "files/render-security-reports.py"),
                    "--source",
                    str(src),
                    "--destination",
                    str(dest),
                ],
                capture_output=True,
                check=True,
            )
            data = json.loads((dest / "summary.json").read_text())
            self.assertEqual(
                data["days"][0]["scans"]["rkhunter"]["state"],
                "INCOMPLETE",
            )
            self.assertNotIn(
                "private-hostname.local",
                (dest / "index.html").read_text(),
            )

    def test_sanitized_dashboard_never_publishes_scanner_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            target = root / "target"
            day = source / "2026-11-16"
            day.mkdir(parents=True)
            target.mkdir()
            (day / "lynis-report.dat").write_text(
                "hardening_index=73\nwarning[]=PRIVATE-URL internal.local\n",
            )
            (day / ".scan-lynis.json").write_text(
                '{"tool":"lynis","state":"COMPLETE"}\n',
            )
            (day / "clamav.txt").write_text(
                "Sensitive /home/secret.key: FOUND\nInfected files: 2\n",
            )
            (day / ".scan-clamav.json").write_text(
                '{"tool":"clamav","state":"INCOMPLETE"}\n',
            )
            renderer = ROOT / "files/render-security-reports.py"
            subprocess.run(
                [
                    "python3",
                    str(renderer),
                    "--source",
                    str(source),
                    "--destination",
                    str(target),
                ],
                check=True,
                capture_output=True,
            )
            report = json.loads((target / "summary.json").read_text())
            page = (target / "index.html").read_text()
            self.assertEqual(report["schema"], "workstation-security-summary/v1")
            lynis = report["days"][0]["scans"]["lynis"]
            clamav = report["days"][0]["scans"]["clamav"]
            self.assertEqual(lynis["metrics"]["hardening_index"], 73)
            self.assertEqual(clamav["state"], "INCOMPLETE")
            self.assertEqual(clamav["metrics"]["infected_files_reported"], 2)
            self.assertIn("Posture de sécurité", page)
            self.assertIn("INCOMPLETE", page)
            self.assertNotIn("internal.local", page + json.dumps(report))
            self.assertNotIn("/home/secret.key", page + json.dumps(report))

    def test_reports_are_local_and_open_only_to_lan_or_cloudflare_access(self):
        conf = (
            ROOT / "files/etc/apache2/conf-available/nabla-lan-only.conf"
        ).read_text()
        self.assertIn("Alias /reports /var/www/reports\n", conf)
        self.assertIn(
            'dest="${SECURITY_PUBLISH_DIR:-/var/www/reports/',
            PUBLISH.read_text(),
        )
        block = conf.split("<Directory /var/www/reports>")[1].split("</Directory>")[0]
        requires = [
            line.strip()
            for line in block.splitlines()
            if line.strip().startswith("Require")
        ]
        self.assertEqual(requires, ["Require ip @@INTERNAL@@"])
        # Header presence is not cryptographic Access authentication.
        self.assertNotIn("Cf-Access-Jwt-Assertion", block)


if __name__ == "__main__":
    unittest.main()
