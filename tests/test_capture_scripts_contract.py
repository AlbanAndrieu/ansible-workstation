"""Hermetic contracts for capture-etc.sh / capture-packages.sh on fixture trees.

No /etc read, no sudo, no network: every run uses temporary directories and
stub commands. Secret-shaped fixtures are built at runtime so repository
scanners never see a literal key or token.
"""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CAPTURE_ETC = ROOT / "scripts/capture-etc.sh"
CAPTURE_PACKAGES = ROOT / "scripts/capture-packages.sh"
COMMON = ROOT / "scripts/capture-common.sh"
MARKER = "@@SECRET@@"
INTERNAL = "@@INTERNAL@@"

PEM_PRIVATE = "-----BEGIN " + "OPENSSH PRIVATE KEY-----\nAAAA\n"
# OpenPGP old-format packet headers: tag 6 = public key, tag 5 = secret key.
PGP_PUBLIC = bytes([0x99, 0x01, 0x0D, 0x04, 0x00, 0x00, 0x00, 0x00])
PGP_SECRET = bytes([0x95, 0x01, 0x0D, 0x04, 0x00, 0x00, 0x00, 0x00])

SECRET_SHAPES = """\
password = fixture-one
db_password: fixture-two
  "client_secret": "fixture-three",
#api_key=fixture-four
Environment="A=1" "SERVICE_TOKEN=fixture-five" "DB_PASSWORD=fixture-six"
url = https://user:fixture-seven@example.invalid/path
netcam_userpass user:fixture-eight
HashedControlPassword 16:fixture-nine
[passwords]
localhost=fixture-ten
[other]
password_file = /etc/keep/path
EnvironmentFile=/etc/keep/env
PasswordAuthentication no
password [success=1 default=ignore] pam_unix.so obscure yescrypt
max_retries = 3
"""
INTERNAL_SHAPES = """\
DNS=172.31.250.1
Server = 10.123.45.67
pool 172.30.0.0/16
local6.* @192.168.77.8:5140
tailnet 100.101.102.103
ula fd12:3456:789a::1/64
search int.albandrieu.com albandrieu.com
nas = nas.lan
Hostname=fixture-host
"""
INTERNAL_KEPT = """\
-A ufw-before-forward -s 10.0.0.0/8 -j DROP
-A ufw-before-forward -s 172.16.0.0/12 -j DROP
-A ufw-before-forward -s 192.168.0.0/16 -j DROP
nameserver 127.0.0.53
FallbackDNS=9.9.9.9 149.112.112.112
ServerName www.albandrieu.com
ServerAlias print.albandrieu.com
iconv.internal_encoding = UTF-8
HostnameItem=system.hostname
version 10.2
"""
KEPT = (
    'Environment="A=1"',
    "[other]",
    "password_file = /etc/keep/path",
    "EnvironmentFile=/etc/keep/env",
    "PasswordAuthentication no",
    "password [success=1 default=ignore] pam_unix.so obscure yescrypt",
    "max_retries = 3",
)


def require_overrides(script, *names):
    """Refuse to run a script that would ignore the fixture paths.

    Without the overrides, capture scripts read the real host and write into
    files/ of this checkout: never execute them from a test in that case.
    """
    text = script.read_text()
    missing = [name for name in names if name not in text]
    if missing:
        raise AssertionError(f"{script.name} ignores fixture overrides: {missing}")


class Fixture:
    """Temporary /etc tree, manifest and capture destination."""

    def __init__(self, tmp):
        self.tmp = Path(tmp)
        self.src = self.tmp / "etc"
        self.dest = self.tmp / "captured"
        self.manifest = self.tmp / "manifest.txt"
        self.src.mkdir()
        self.dest.mkdir()

    def host(self, rel, content):
        path = self.src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content)
        return path

    def capture(self, *entries):
        require_overrides(CAPTURE_ETC, "CAPTURE_ETC_SOURCE", "CAPTURE_ETC_MANIFEST",
                          "CAPTURE_ETC_DEST")
        self.manifest.write_text("# fixture\n" + "".join(f"{e}\n" for e in entries))
        env = {
            **os.environ,
            "CAPTURE_ETC_SOURCE": str(self.src),
            "CAPTURE_ETC_MANIFEST": str(self.manifest),
            "CAPTURE_ETC_DEST": str(self.dest),
        }
        return subprocess.run(
            ["bash", str(CAPTURE_ETC)],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )


class CaptureEtcScript(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fx = Fixture(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_redacts_secret_shapes_and_keeps_configuration(self):
        self.fx.host("app/app.conf", SECRET_SHAPES)
        result = self.fx.capture("/etc/app/app.conf")
        self.assertEqual(result.returncode, 0, result.stderr)
        captured = (self.fx.dest / "app/app.conf").read_text()
        self.assertNotIn("fixture-", captured)
        self.assertEqual(captured.count(MARKER), 10)
        for line in KEPT:
            with self.subTest(line=line):
                self.assertIn(line, captured)
        self.assertIn("redacted secret(s): /etc/app/app.conf", result.stderr)

    def test_removes_internal_addresses_and_names_only(self):
        self.fx.host("net.conf", INTERNAL_SHAPES + INTERNAL_KEPT)
        result = self.fx.capture("/etc/net.conf")
        self.assertEqual(result.returncode, 0, result.stderr)
        captured = (self.fx.dest / "net.conf").read_text()
        for value in ("172.31.", "10.123.", "172.30.", "192.168.77", "100.101.",
                      "fd12:", " int.albandrieu",
                      "nas.lan", "fixture-host"):
            with self.subTest(value=value):
                self.assertNotIn(value, captured)
        self.assertEqual(captured.count(INTERNAL), 9)
        self.assertTrue(captured.endswith(INTERNAL_KEPT), captured)
        self.assertIn("search @@INTERNAL@@ albandrieu.com", captured)
        self.assertIn("internal address(es) or hostname(s) removed: /etc/net.conf",
                      result.stderr)

    def test_refuses_secret_stores_and_paths_outside_etc(self):
        for rel in ("shadow", "ssh/ssh_host_ed25519_key", "server.key",
                    "NetworkManager/system-connections/home.nmconnection"):
            self.fx.host(rel, "fixture-secret\n")
        result = self.fx.capture(
            "/etc/shadow",
            "/etc/ssh/ssh_host_ed25519_key",
            "/etc/server.key",
            "/etc/NetworkManager/system-connections/home.nmconnection",
            "/etc/../outside.conf",
            "/tmp/outside.conf",
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(list(self.fx.dest.rglob("*")), [])
        self.assertEqual(result.stderr.count("refused ("), 6)
        self.assertNotIn("fixture-secret", result.stdout + result.stderr)

    def test_refuses_symlinks_leaving_etc_or_into_secret_stores(self):
        outside = self.fx.tmp / "outside.conf"
        outside.write_text("fixture-outside\n")
        self.fx.host("shadow", "fixture-shadow\n")
        (self.fx.src / "escape.conf").symlink_to(outside)
        (self.fx.src / "alias.conf").symlink_to(self.fx.src / "shadow")
        result = self.fx.capture("/etc/escape.conf", "/etc/alias.conf")
        self.assertEqual(result.returncode, 1)
        self.assertIn("refused (symlink leaves /etc): /etc/escape.conf", result.stderr)
        self.assertIn("refused (symlink to a secret store): /etc/alias.conf",
                      result.stderr)
        self.assertEqual(list(self.fx.dest.rglob("*")), [])

    def test_never_writes_through_symlinks_planted_in_the_repository(self):
        victim = self.fx.tmp / "victim"
        victim.write_text("untouched\n")
        victim_dir = self.fx.tmp / "victim-dir"
        victim_dir.mkdir()
        (self.fx.dest / "app.conf").symlink_to(victim)
        (self.fx.dest / "sub").symlink_to(victim_dir)
        self.fx.host("app.conf", "setting = 1\n")
        self.fx.host("sub/x.conf", "setting = 2\n")
        result = self.fx.capture("/etc/app.conf", "/etc/sub/x.conf")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(victim.read_text(), "untouched\n")
        self.assertEqual(list(victim_dir.iterdir()), [])
        replaced = self.fx.dest / "app.conf"
        self.assertFalse(replaced.is_symlink())
        self.assertEqual(replaced.read_text(), "setting = 1\n")
        self.assertIn("refused (destination escapes", result.stderr)

    def test_secret_signature_is_refused_and_repo_copy_kept(self):
        token = "gh" + "p_" + "A1b2" * 9
        self.fx.host("key.conf", PEM_PRIVATE)
        self.fx.host("token.conf", f"header {token}\n")
        (self.fx.dest / "key.conf").write_text("previous\n")
        result = self.fx.capture("/etc/key.conf", "/etc/token.conf")
        self.assertEqual(result.returncode, 1)
        self.assertEqual((self.fx.dest / "key.conf").read_text(), "previous\n")
        self.assertFalse((self.fx.dest / "token.conf").exists())
        self.assertEqual(
            result.stderr.count("refused (secret signature left after redaction)"), 2
        )
        self.assertNotIn(token, result.stdout + result.stderr)

    def test_binary_only_public_openpgp_keys(self):
        self.fx.host("apt/keyrings/public.gpg", PGP_PUBLIC)
        self.fx.host("apt/keyrings/secret.gpg", PGP_SECRET)
        self.fx.host("blob.bin", b"\x00\x01\x02")
        result = self.fx.capture(
            "/etc/apt/keyrings/public.gpg",
            "/etc/apt/keyrings/secret.gpg",
            "/etc/blob.bin",
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual((self.fx.dest / "apt/keyrings/public.gpg").read_bytes(),
                         PGP_PUBLIC)
        self.assertFalse((self.fx.dest / "apt/keyrings/secret.gpg").exists())
        self.assertFalse((self.fx.dest / "blob.bin").exists())
        self.assertEqual(result.stderr.count("binary other than a public OpenPGP"), 2)

    def test_absent_entries_keep_repo_copy_and_orphans_are_only_reported(self):
        (self.fx.dest / "gone.conf").write_text("kept\n")
        (self.fx.dest / "orphan.conf").write_text("orphan\n")
        result = self.fx.capture("/etc/gone.conf", "/etc/gone.conf")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.fx.dest / "gone.conf").read_text(), "kept\n")
        self.assertTrue((self.fx.dest / "orphan.conf").exists())
        self.assertIn("absent, kept repo copy: /etc/gone.conf", result.stderr)
        self.assertIn("duplicate manifest entry, ignored: /etc/gone.conf",
                      result.stderr)
        self.assertIn("not in manifest, review or delete: /etc/orphan.conf",
                      result.stderr)

    def test_shebang_scripts_keep_exec_bit(self):
        hook = self.fx.host("dispatcher.d/90-hook", "#!/bin/sh\nexit 0\n")
        hook.chmod(0o755)
        self.fx.host("plain.conf", "a = 1\n")
        result = self.fx.capture("/etc/dispatcher.d/90-hook", "/etc/plain.conf")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.fx.dest / "dispatcher.d/90-hook").stat().st_mode & 0o777,
                         0o755)
        self.assertEqual((self.fx.dest / "plain.conf").stat().st_mode & 0o777, 0o644)


class CommittedCaptures(unittest.TestCase):
    def test_committed_captures_are_a_redaction_fixed_point(self):
        # Every committed text capture must be unchanged by the current rules,
        # so a rule added later forces a reviewed re-redaction.
        script = (
            '. "$1"; shift; for f; do is_text "$f" || continue; '
            'redact <"$f" | scrub_internal | cmp -s - "$f" || echo "unredacted: $f"; '
            'has_secret_signature "$f" && echo "signature: $f"; done; true'
        )
        files = sorted(str(p) for p in (ROOT / "files/etc").rglob("*") if p.is_file())
        result = subprocess.run(
            ["bash", "-c", script, "redact", str(COMMON), *files],
            capture_output=True, text=True, timeout=120, check=True,
        )
        self.assertEqual(result.stdout, "")

    def test_committed_binaries_are_public_keys(self):
        script = (
            '. "$1"; shift; '
            'for f; do is_text "$f" || is_public_pgp "$f" || echo "$f"; done'
        )
        files = [str(p) for p in (ROOT / "files").rglob("*.gpg")]
        self.assertTrue(files)
        result = subprocess.run(
            ["bash", "-c", script, "pgp", str(COMMON), *files],
            capture_output=True, text=True, timeout=60, check=True,
        )
        self.assertEqual(result.stdout, "")


STUBS = {
    "apt-mark": 'echo vim; echo redis-server; echo linux-image-7.0.0-27-generic; '
                'echo gnome-shell; echo localtool',
    "apt": 'printf "Listing...\\nlocaltool/now 1.0 amd64 [installed,local]\\n"',
    "apt-cache": 'echo gnome-shell; echo "  Depends: libc6"',
    "snap": 'printf "Name Version Rev Tracking Publisher Notes\\n'
            'core22 1 1 latest canonical base\\ncode 1 1 latest vscode classic\\n'
            'firefox 1 1 latest mozilla -\\n"',
    "flatpak": 'echo org.example.App',
}


class CapturePackagesScript(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        for name, body in STUBS.items():
            stub = bin_dir / name
            stub.write_text(f"#!/bin/bash\n{body}\n")
            stub.chmod(0o755)
        self.sources = self.tmp / "sources"
        self.sources.mkdir()
        self.keyring_root = self.tmp / "keyrings-host"
        self.keyring_root.mkdir()
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "CAPTURE_PACKAGES_OUT": str(self.tmp / "packages"),
            "CAPTURE_KEYRINGS_DEST": str(self.tmp / "keyrings"),
            "CAPTURE_SOURCES_DIR": str(self.sources),
            "CAPTURE_KEYRING_ROOT": str(self.keyring_root),
        }

    def tearDown(self):
        self._tmp.cleanup()

    def run_capture(self):
        require_overrides(CAPTURE_PACKAGES, "CAPTURE_PACKAGES_OUT",
                          "CAPTURE_KEYRINGS_DEST", "CAPTURE_SOURCES_DIR",
                          "CAPTURE_KEYRING_ROOT")
        return subprocess.run(
            ["bash", str(CAPTURE_PACKAGES)],
            env=self.env, capture_output=True, text=True, timeout=60, check=False,
        )

    def read(self, name):
        return (self.tmp / "packages" / name).read_text().split()

    def test_selection_and_snap_split(self):
        result = self.run_capture()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read("apt.txt"), ["vim"])
        self.assertEqual(self.read("apt-no-repo.txt"), ["localtool"])
        self.assertEqual(self.read("snap.txt"), ["firefox"])
        self.assertEqual(self.read("snap-classic.txt"), ["code"])
        self.assertEqual(self.read("flatpak.txt"), ["org.example.App"])

    def test_only_public_keyrings_are_copied(self):
        (self.sources / "a.sources").write_text(
            "Signed-By: /usr/share/keyrings/public.gpg\n"
        )
        (self.sources / "b.list").write_text(
            "deb [signed-by=/usr/share/keyrings/secret.gpg]"
            " https://x.invalid stable main\n"
        )
        (self.keyring_root / "public.gpg").write_bytes(PGP_PUBLIC)
        (self.keyring_root / "secret.gpg").write_bytes(PGP_SECRET)
        result = self.run_capture()
        self.assertEqual(result.returncode, 1)
        self.assertEqual((self.tmp / "keyrings/public.gpg").read_bytes(), PGP_PUBLIC)
        self.assertFalse((self.tmp / "keyrings/secret.gpg").exists())
        self.assertIn("refused (not a public OpenPGP key)", result.stderr)


if __name__ == "__main__":
    unittest.main()
