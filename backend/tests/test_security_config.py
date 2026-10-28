import base64
import json
import logging
import os
import tempfile
import unittest

from app.config import Config, ConfigError, load_config
from app.security import auth
from app.security.logging_setup import SanitizingFilter, sanitize
from app.security.ratelimit import RateLimiter


class SecurityTests(unittest.TestCase):
    def test_rate_limiter_window(self):
        t = [0.0]
        rl = RateLimiter(clock=lambda: t[0])
        for _ in range(3):
            self.assertTrue(rl.check("b", "ip", 3)[0])
        ok, retry = rl.check("b", "ip", 3)
        self.assertFalse(ok)
        self.assertGreater(retry, 0)
        self.assertTrue(rl.check("b", "other", 3)[0])
        t[0] = 61
        self.assertTrue(rl.check("b", "ip", 3)[0])

    def test_rate_limiter_bounded(self):
        rl = RateLimiter(max_keys=100)
        for i in range(1000):
            rl.check("b", str(i), 5)
        self.assertLessEqual(len(rl._hits), 100)

    def test_admin_auth(self):
        secret = "s" * 32
        good = "Basic " + base64.b64encode(f"admin:{secret}".encode()).decode()
        bad = "Basic " + base64.b64encode(b"admin:wrong").decode()
        self.assertTrue(auth.check_admin(good, secret))
        self.assertFalse(auth.check_admin(bad, secret))
        self.assertFalse(auth.check_admin(None, secret))
        self.assertFalse(auth.check_admin("Basic !!!", secret))
        self.assertFalse(auth.check_admin("Bearer x", secret))
        self.assertFalse(auth.check_admin(good, ""))  # no secret configured => admin disabled

    def test_app_key(self):
        self.assertTrue(auth.check_app_key(None, ""))
        self.assertTrue(auth.check_app_key("k", "k"))
        self.assertFalse(auth.check_app_key("x", "k"))
        self.assertFalse(auth.check_app_key(None, "k"))

    def test_id_validation(self):
        self.assertTrue(auth.valid_server_id("0123456789abcdef"))
        for bad in ["", "../../etc/passwd", "0123456789ABCDEF", "0123456789abcde", "0123456789abcdef0", "g" * 16, "a;rm -rf"]:
            self.assertFalse(auth.valid_server_id(bad), bad)
        self.assertFalse(auth.valid_connection_id("short"))
        self.assertFalse(auth.valid_connection_id("a" * 30 + "/"))

    def test_log_sanitizer(self):
        text = "err -----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY----- tok SECRETVALUE123 " + "A" * 200
        out = sanitize(text, ["SECRETVALUE123"])
        for leak in ("PRIVATE KEY", "SECRETVALUE123", "A" * 120):
            self.assertNotIn(leak, out)
        rec = logging.LogRecord("x", logging.INFO, "f", 1, "pw=%s", ("SECRETVALUE123",), None)
        SanitizingFilter(["SECRETVALUE123"]).filter(rec)
        self.assertNotIn("SECRETVALUE123", rec.getMessage())


class ConfigTests(unittest.TestCase):
    def test_defaults_valid(self):
        Config().validate()

    def test_rejections(self):
        bad = [dict(refresh_interval_s=60), dict(upstream_url="http://www.vpngate.net/api/iphone/"),
               dict(upstream_url="https://evil.example.com/x"), dict(bind_host="0.0.0.0"),
               dict(probe_concurrency=500), dict(weights={"bogus": 1}), dict(weights={"speed": 0}),
               dict(max_profile_bytes=10), dict(admin_secret="short")]
        for kw in bad:
            with self.assertRaises(ConfigError, msg=str(kw)):
                Config(**kw).validate()
        Config(bind_host="0.0.0.0", allow_public_bind=True).validate()

    def test_load_file_and_env_secrets(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "c.json")
        json.dump({"refresh_interval_s": 900, "weights": {"speed": 0.5}}, open(p, "w"))
        cfg = load_config(p, env={"VPNGATE_ADMIN_SECRET": "x" * 40, "VPNGATE_DB_PATH": "/tmp/z.db"})
        self.assertEqual(cfg.refresh_interval_s, 900)
        self.assertEqual(cfg.weights["speed"], 0.5)
        self.assertIn("latency", cfg.weights)  # merged with defaults
        self.assertEqual(cfg.db_path, "/tmp/z.db")
        self.assertEqual(cfg.admin_secret, "x" * 40)

    def test_unknown_keys_and_secrets_in_file_rejected(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "c.json")
        for payload in ({"refrsh_interval_s": 1}, {"admin_secret": "x" * 40}):
            json.dump(payload, open(p, "w"))
            with self.assertRaises(ConfigError):
                load_config(p, env={})
        with self.assertRaises(ConfigError):
            load_config(os.path.join(d, "missing.json"), env={})


if __name__ == "__main__":
    unittest.main()
