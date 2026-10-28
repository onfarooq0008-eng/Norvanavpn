import base64
import unittest

from app.config import Config
from app.services.vpngate import UpstreamFormatError, parse_csv, server_id
from tests.helpers import HEADER, IP1, IP2, IP3, csv_row, make_csv, make_profile


class CsvTests(unittest.TestCase):
    cfg = Config()

    def test_parses_valid_rows(self):
        res = parse_csv(make_csv([csv_row(ip=IP1), csv_row(host="vpn2", ip=IP2, cc="US", country="United States",
                                                          profile=make_profile(IP2, 443, "tcp"))]), self.cfg)
        self.assertEqual(len(res.servers), 2)
        s = {x.ip: x for x in res.servers}
        self.assertEqual(s[IP2].transport, "tcp")
        self.assertEqual(s[IP2].port, 443)
        self.assertEqual(s[IP1].country_code, "JP")
        self.assertEqual(s[IP1].speed_bps, 50_000_000)
        self.assertEqual(s[IP1].id, server_id(IP1, "udp", 1195))

    def test_bad_header_or_marker(self):
        with self.assertRaises(UpstreamFormatError):
            parse_csv("<html>Maintenance</html>", self.cfg)
        with self.assertRaises(UpstreamFormatError):
            parse_csv("*vpn_servers\nnot,a,header\n", self.cfg)
        with self.assertRaises(UpstreamFormatError):
            parse_csv("*vpn_servers\n#HostName,IP\nx,1.1.1.1\n", self.cfg)

    def test_malformed_and_missing_fields(self):
        rows = [csv_row(ip=IP1),
                "short,row",
                csv_row(host="nocfg", ip=IP2, raw_b64="", profile=""),
                csv_row(host="badip", ip="not-an-ip"),
                csv_row(host="private", ip="192.168.1.5", profile=make_profile("192.168.1.5")),
                csv_row(host="b64", ip=IP3, raw_b64="!!!notbase64!!!"),
                csv_row(host="evil", ip="4.4.4.4", profile=make_profile("4.4.4.4", extra="script-security 2"))]
        res = parse_csv(make_csv(rows), self.cfg)
        self.assertEqual(len(res.servers), 1)
        self.assertEqual(res.rejected["malformed_row"], 1)
        self.assertEqual(res.rejected["no_openvpn_config"], 1)
        self.assertEqual(res.rejected["invalid_ip"], 2)
        self.assertEqual(res.rejected["profile_decode_error"], 1)
        self.assertEqual(res.rejected["profile:directive:script-security"], 1)

    def test_numeric_fields_optional(self):
        row = csv_row(score="", ping="", speed="abc", sessions="")
        res = parse_csv(make_csv([row]), self.cfg)
        s = res.servers[0]
        self.assertIsNone(s.vpngate_score)
        self.assertIsNone(s.ping_ms)
        self.assertIsNone(s.speed_bps)

    def test_duplicates_keep_higher_score(self):
        res = parse_csv(make_csv([csv_row(score=5), csv_row(host="dup", score=900)]), self.cfg)
        self.assertEqual(len(res.servers), 1)
        self.assertEqual(res.duplicates, 1)
        self.assertEqual(res.servers[0].vpngate_score, 900)

    def test_bom_and_hostname_sanitising(self):
        res = parse_csv("\ufeff" + make_csv([csv_row(host="bad host!<script>")]), self.cfg)
        self.assertEqual(res.servers[0].hostname, IP1)

    def test_oversized_profile_rejected(self):
        big = base64.b64encode(make_profile(extra="#" + "a" * 70000).encode()).decode()
        res = parse_csv(make_csv([csv_row(raw_b64=big)]), self.cfg)
        self.assertEqual(res.rejected.get("profile:profile_too_large"), 1)


if __name__ == "__main__":
    unittest.main()
