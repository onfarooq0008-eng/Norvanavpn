import unittest

from app.config import Config
from app.services.profile import ProfileError, validate_profile
from tests.helpers import CERT, IP1, IP2, make_profile


def code(text, cfg=None, ip=None):
    try:
        validate_profile(text, cfg or Config(), ip)
    except ProfileError as e:
        return e.code
    return None


class ProfileTests(unittest.TestCase):
    def test_valid_profile(self):
        r = validate_profile(make_profile(), Config(), IP1)
        self.assertEqual((r.host, r.port, r.transport), (IP1, 1195, "udp"))
        self.assertIn("<ca>", r.text)
        self.assertIn("cipher AES-128-CBC", r.text)  # security settings preserved untouched

    def test_tcp_and_tls_auth_detected(self):
        r = validate_profile(make_profile(proto="tcp", port=443, tls_auth=True), Config(), IP1)
        self.assertEqual(r.transport, "tcp")
        self.assertTrue(r.has_tls_auth)

    def test_dangerous_directives_rejected(self):
        for extra in ["script-security 2", "up /bin/sh", "plugin /x.so", "http-proxy 1.2.3.4 80",
                      "auth-user-pass", "tls-verify /bin/true", "route 10.0.0.0 255.0.0.0", "management 127.0.0.1 1",
                      "ca /etc/passwd", "setenv PATH /tmp", "config /etc/x", "dhcp-option DNS 6.6.6.6",
                      "ifconfig-noexec", "client-connect x", "pull-filter ignore x", "down x"]:
            self.assertTrue((code(make_profile(extra=extra)) or "").startswith("directive:"), extra)

    def test_missing_ca_rejected(self):
        self.assertEqual(code(make_profile(ca=False)), "missing_ca")

    def test_remote_checks(self):
        self.assertEqual(code(make_profile(ip="10.0.0.1")), "remote_not_public_ipv4")
        self.assertEqual(code(make_profile(ip="127.0.0.1")), "remote_not_public_ipv4")
        self.assertEqual(code(make_profile().replace(f"remote {IP1} 1195", "remote evil.example.com 1195")),
                         "remote_host_not_ip")
        self.assertEqual(code(make_profile(), ip=IP2), "remote_mismatch")
        self.assertEqual(code(make_profile(extra=f"remote {IP2} 443")), "multiple_remote")
        self.assertEqual(code(make_profile(port=70000)), "remote_malformed")

    def test_weak_crypto_rejected(self):
        self.assertEqual(code(make_profile(cipher="BF-CBC")), "weak_cipher")
        self.assertEqual(code(make_profile(cipher="none")), "weak_cipher")
        self.assertEqual(code(make_profile().replace("auth SHA1", "auth none")), "weak_auth")

    def test_compression_default_off_but_configurable(self):
        p = make_profile(extra="comp-lzo")
        self.assertEqual(code(p), "compression_disabled")
        self.assertIsNone(code(p, Config(allow_compression=True)))

    def test_size_and_control_chars(self):
        self.assertEqual(code(make_profile(extra="#" + "a" * 60000)), "profile_too_large")
        self.assertEqual(code(make_profile().replace("verb 3", "verb\x003")), "control_characters")

    def test_quotes_and_bad_blocks(self):
        self.assertEqual(code(make_profile(extra='verb "3"')), "quote_in_directive")
        bad = make_profile().replace("</ca>", "evil;rm -rf /\n</ca>")
        self.assertEqual(code(bad), "block_content_invalid")
        self.assertEqual(code(make_profile(extra="<connection>\nremote 1.1.1.1 1\n</connection>")), "block_not_allowed")
        self.assertEqual(code(make_profile().replace("</ca>", "")), "block_content_invalid")  # swallows next tag
        self.assertEqual(code("client\ndev tun\nremote %s 1195\n<ca>\n%s\n" % (IP1, CERT)), "block_unterminated")

    def test_proto_mismatch_and_dev_tap(self):
        self.assertEqual(code(make_profile(extra=f"remote {IP1} 1195 tcp").replace(f"remote {IP1} 1195\n", "", 1)),
                         "proto_mismatch")
        self.assertEqual(code(make_profile().replace("dev tun", "dev tap")), "directive:dev")


if __name__ == "__main__":
    unittest.main()
