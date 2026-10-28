import configparser
import os
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class InstallerTests(unittest.TestCase):
    def test_shell_syntax(self):
        for s in ("install.sh", "uninstall.sh", "quick-start.sh", "scripts/healthcheck.sh", "scripts/selftest.sh"):
            r = subprocess.run(["bash", "-n", os.path.join(ROOT, s)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{s}: {r.stderr}")

    def test_scripts_are_safe_by_construction(self):
        inst = open(os.path.join(ROOT, "install.sh")).read()
        self.assertIn("set -euo pipefail", inst)
        self.assertIn("EUID", inst)                          # root check
        self.assertIn("nginx -t", inst)                      # config validated before reload
        self.assertIn("ufw allow", inst)                     # SSH rule is added before enabling
        self.assertLess(inst.index("ufw allow"), inst.index("ufw --force enable"))
        self.assertNotIn("rm -rf /\n", inst)
        self.assertIn("[ ! -f \"$ENV_FILE\" ]", inst)        # secrets never regenerated
        un = open(os.path.join(ROOT, "uninstall.sh")).read()
        self.assertIn("confirm", un.lower())

    def test_systemd_units_parse_and_are_hardened(self):
        for unit in ("vpngate-api.service", "vpngate-worker.service", "vpngate-healthcheck.service",
                     "vpngate-healthcheck.timer"):
            p = configparser.ConfigParser(strict=False, interpolation=None)
            p.optionxform = str
            p.read(os.path.join(ROOT, "systemd", unit))
            self.assertTrue(p.sections(), unit)
        svc = open(os.path.join(ROOT, "systemd", "vpngate-api.service")).read()
        for needed in ("User=vpngate", "NoNewPrivileges=true", "ProtectSystem=strict", "EnvironmentFile=",
                       "app.serve", "Restart=on-failure"):
            self.assertIn(needed, svc)

    def test_env_example_has_no_real_secrets(self):
        env = open(os.path.join(ROOT, ".env.example")).read()
        self.assertIn("VPNGATE_ADMIN_SECRET=", env)
        self.assertNotRegex(env, r"SECRET=[A-Za-z0-9]{20,}")

    def test_requirements_are_pinned(self):
        for line in open(os.path.join(ROOT, "requirements.txt")):
            line = line.strip()
            if line and not line.startswith("#"):
                self.assertIn("==", line)


if __name__ == "__main__":
    unittest.main()
