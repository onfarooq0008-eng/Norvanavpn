import random
import unittest

from app.services import connect
from app.services.store import Store
from app.services.vpngate import parse_csv
from tests.helpers import IP1, IP2, IP3, csv_row, make_csv, make_profile, temp_store

NOW = 2_000_000.0


def load(store, cfg, rows, now=NOW):
    res = parse_csv(make_csv(rows), cfg)
    store.upsert_inventory(res.servers, now)
    return res.servers


class StoreConnectTests(unittest.TestCase):
    def setUp(self):
        self.cfg, self.store = temp_store()
        self.servers = load(self.store, self.cfg, [
            csv_row(ip=IP1, speed=80_000_000),
            csv_row(host="v2", ip=IP2, cc="US", country="United States", speed=10_000_000,
                    profile=make_profile(IP2, 443, "tcp"))])
        self.by_ip = {s.ip: s for s in self.servers}

    def test_connect_response_schema_and_real_values(self):
        r = connect.issue_connection(self.store, self.cfg, NOW + 5, rng=random.Random(1))
        self.assertTrue(r["success"])
        self.assertEqual(set(r), {"success", "connection_id", "server", "openvpn_profile", "expires_at", "notice"})
        s = r["server"]
        self.assertEqual(set(s) >= {"id", "country", "hostname", "protocol", "latency_ms", "quality_score",
                                     "verification_status"}, True)
        self.assertEqual(s["protocol"], "openvpn")
        self.assertEqual(s["verification_status"], "candidate")  # never probed => not claimed reachable
        self.assertIsNone(s["latency_ms"])
        self.assertIn(f"remote {s['ip']}", r["openvpn_profile"])
        self.assertTrue(r["expires_at"].endswith("Z"))
        self.assertGreaterEqual(len(r["connection_id"]), 30)

    def test_filters_and_exclude(self):
        r = connect.issue_connection(self.store, self.cfg, NOW, country="us")
        self.assertEqual(r["server"]["country_code"], "US")
        r = connect.issue_connection(self.store, self.cfg, NOW, protocol="udp")
        self.assertEqual(r["server"]["transport"], "udp")
        with self.assertRaises(connect.ServiceError) as cm:
            connect.issue_connection(self.store, self.cfg, NOW, exclude=[s.id for s in self.servers])
        self.assertEqual(cm.exception.code, "no_server_available")

    def test_failure_report_cooldown_and_single_use(self):
        r = connect.issue_connection(self.store, self.cfg, NOW, protocol="udp")
        sid, cid = r["server"]["id"], r["connection_id"]
        connect.record_report(self.store, self.cfg, NOW + 1, sid, cid, "failure")
        with self.assertRaises(connect.ServiceError) as cm:
            connect.record_report(self.store, self.cfg, NOW + 2, sid, cid, "failure")
        self.assertEqual(cm.exception.status, 409)
        with self.assertRaises(connect.ServiceError):  # now in cooldown: only the tcp server left for udp filter? none
            connect.issue_connection(self.store, self.cfg, NOW + 3, protocol="udp")
        # cooldown expires
        r2 = connect.issue_connection(self.store, self.cfg, NOW + 1 + self.cfg.failure_cooldown_s + 1, protocol="udp")
        self.assertEqual(r2["server"]["id"], sid)

    def test_repeated_failures_back_off_exponentially(self):
        sid = self.by_ip[IP1].id
        for i, expect in enumerate([600, 1200, 2400]):
            cid = f"conn-{i}-" + "x" * 24
            self.store.create_connection(cid, sid, NOW, 600)
            self.store.report(cid, sid, "failure", NOW, self.cfg)
            self.assertEqual(self.store.get_server(sid)["cooldown_until"], NOW + expect)

    def test_report_validation(self):
        r = connect.issue_connection(self.store, self.cfg, NOW)
        other = [s.id for s in self.servers if s.id != r["server"]["id"]][0]
        for sid, cid in [(other, r["connection_id"]), (r["server"]["id"], "nonexistent-" + "y" * 20)]:
            with self.assertRaises(connect.ServiceError) as cm:
                connect.record_report(self.store, self.cfg, NOW, sid, cid, "success")
            self.assertEqual(cm.exception.status, 404)
        with self.assertRaises(connect.ServiceError):  # expired connection id
            connect.record_report(self.store, self.cfg, NOW + 10_000, r["server"]["id"], r["connection_id"], "success")

    def test_cancel_and_disconnect_do_not_penalise(self):
        r = connect.issue_connection(self.store, self.cfg, NOW)
        sid = r["server"]["id"]
        connect.record_report(self.store, self.cfg, NOW, sid, r["connection_id"], "cancelled")
        self.assertEqual(self.store.get_server(sid)["cooldown_until"], 0)
        self.assertEqual(self.store.report(r["connection_id"], "", "disconnect", NOW, self.cfg), "recorded")
        self.assertEqual(self.store.report(r["connection_id"], "", "disconnect", NOW, self.cfg), "unknown")

    def test_success_report_is_only_an_untrusted_signal(self):
        r = connect.issue_connection(self.store, self.cfg, NOW)
        connect.record_report(self.store, self.cfg, NOW, r["server"]["id"], r["connection_id"], "success")
        row = self.store.get_server(r["server"]["id"])
        self.assertEqual(row["client_ok"], 1)
        again = connect.issue_connection(self.store, self.cfg, NOW + 1, exclude=[x.id for x in self.servers
                                                                                if x.id != r["server"]["id"]])
        self.assertEqual(again["server"]["verification_status"], "candidate")

    def test_stale_inventory_and_expiry(self):
        stats = connect.build_stats(self.store, self.cfg, NOW + self.cfg.inventory_stale_after_s + 1)
        self.assertTrue(stats["inventory_stale"])
        connect.issue_connection(self.store, self.cfg, NOW + self.cfg.inventory_stale_after_s + 1)  # still served
        with self.assertRaises(connect.ServiceError) as cm:
            connect.issue_connection(self.store, self.cfg, NOW + self.cfg.inventory_max_age_s + 1)
        self.assertEqual(cm.exception.code, "inventory_unavailable")

    def test_empty_inventory(self):
        _, empty = temp_store()
        with self.assertRaises(connect.ServiceError):
            connect.issue_connection(empty, self.cfg, NOW)

    def test_refresh_preserves_probe_history_and_handles_disappearing_ip(self):
        a = self.by_ip[IP1]
        self.store.record_probe(a.id, True, "openvpn_reset", 42.0, NOW, self.cfg)
        # next refresh: IP1 still there, IP2 gone, IP3 new
        load(self.store, self.cfg, [csv_row(ip=IP1), csv_row(host="v3", ip=IP3, profile=make_profile(IP3))], NOW + 1800)
        row = self.store.get_server(a.id)
        self.assertEqual(row["latency_ms"], 42.0)
        self.assertEqual(row["last_seen"], NOW + 1800)
        ids = {r["id"] for r in self.store.all_servers()}
        self.assertEqual(len(ids), 3)  # IP2 kept (grace period) but becomes ineligible after server_ttl
        later = NOW + 1800 + self.cfg.server_ttl_s - 1  # IP2 last seen at NOW
        stats = connect.build_stats(self.store, self.cfg, later)
        self.assertEqual(stats["eligible"], 2)
        self.store.set_meta("last_refresh_ok_ts", later)

    def test_probe_failure_and_success_update_state(self):
        a = self.by_ip[IP1]
        self.store.record_probe(a.id, False, "openvpn_reset", None, NOW, self.cfg)
        row = self.store.get_server(a.id)
        self.assertEqual(row["consec_fail"], 1)
        self.assertGreater(row["cooldown_until"], NOW)
        self.store.record_probe(a.id, True, "openvpn_reset", 55.0, NOW + 700, self.cfg)
        row = self.store.get_server(a.id)
        self.assertEqual((row["consec_fail"], row["cooldown_until"]), (0, 0))

    def test_restart_persistence(self):
        again = Store(self.cfg.db_path)  # simulates process restart
        self.assertEqual(len(again.all_servers()), 2)
        self.assertEqual(again.get_meta_float("last_refresh_ok_ts"), NOW)

    def test_purge_retention(self):
        self.store.record_probe(self.by_ip[IP1].id, False, "x", None, NOW, self.cfg)
        self.store.purge(NOW + 8 * 86400, self.cfg)
        self.assertEqual(self.store.recent_failures(NOW + 8 * 86400, 10 * 86400), 0)

    def test_connection_ids_not_stored_in_clear(self):
        r = connect.issue_connection(self.store, self.cfg, NOW)
        with self.store._conn() as c:
            dump = " ".join(str(tuple(row)) for row in c.execute("SELECT * FROM connections"))
        self.assertNotIn(r["connection_id"], dump)


if __name__ == "__main__":
    unittest.main()
