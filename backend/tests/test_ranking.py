import unittest

from app.config import Config
from app.services import ranking

NOW = 1_000_000.0


def row(**kw):
    base = dict(id="a" * 16, profile="x", last_seen=NOW, speed_bps=50_000_000, ping_ms=30, sessions=20,
                uptime_ms=5 * 86400000, vpngate_score=500000, latency_ms=None, last_ok_ts=None,
                reliability=0.5, cooldown_until=0, consec_fail=0, verified_ts=None)
    base.update(kw)
    return base


class RankingTests(unittest.TestCase):
    cfg = Config()

    def test_status_derivation(self):
        self.assertEqual(ranking.derive_status(row(), self.cfg, NOW), "candidate")
        self.assertEqual(ranking.derive_status(row(last_ok_ts=NOW - 60), self.cfg, NOW), "reachable")
        self.assertEqual(ranking.derive_status(row(last_ok_ts=NOW - 99999), self.cfg, NOW), "candidate")
        self.assertEqual(ranking.derive_status(row(last_ok_ts=NOW - 60, verified_ts=NOW - 10), self.cfg, NOW),
                         "vpn_verified")
        self.assertEqual(ranking.derive_status(row(verified_ts=NOW - 10 * 86400), self.cfg, NOW), "candidate")

    def test_measured_beats_unmeasured_and_faster_beats_slower(self):
        measured = row(id="m" * 16, latency_ms=40, last_ok_ts=NOW - 30, reliability=0.9)
        unmeasured = row(id="u" * 16, speed_bps=90_000_000)
        slow = row(id="s" * 16, latency_ms=40, last_ok_ts=NOW - 30, reliability=0.9, speed_bps=1_000_000)
        order = [r[0]["id"][0] for r in ranking.rank([unmeasured, slow, measured], self.cfg, NOW)]
        self.assertEqual(order, ["m", "s", "u"])  # reachable tier first, then by score

    def test_cooldown_and_stale_not_eligible(self):
        self.assertFalse(ranking.is_eligible(row(cooldown_until=NOW + 10), self.cfg, NOW))
        self.assertTrue(ranking.is_eligible(row(cooldown_until=NOW - 1), self.cfg, NOW))
        self.assertFalse(ranking.is_eligible(row(last_seen=NOW - self.cfg.server_ttl_s - 1), self.cfg, NOW))
        self.assertFalse(ranking.is_eligible(row(profile=None), self.cfg, NOW))

    def test_freshness_decays(self):
        fresh = ranking.compute_score(row(latency_ms=40, last_ok_ts=NOW - 10), self.cfg, NOW)
        old = ranking.compute_score(row(latency_ms=40, last_ok_ts=NOW - 3000), self.cfg, NOW)
        self.assertGreater(fresh, old)

    def test_weights_configurable(self):
        cfg = Config(weights={"speed": 1, "adv_ping": 0, "latency": 0, "load": 0, "uptime": 0,
                              "vg_score": 0, "reliability": 0, "freshness": 0})
        a = ranking.compute_score(row(speed_bps=90_000_000), cfg, NOW)
        b = ranking.compute_score(row(speed_bps=2_000_000), cfg, NOW)
        self.assertGreater(a, b)
        self.assertLessEqual(a, 100)

    def test_spread_stays_in_tier_and_window(self):
        ranked = [(row(id="a" * 16), "reachable", 80.0), (row(id="b" * 16), "reachable", 78.0),
                  (row(id="c" * 16), "reachable", 40.0), (row(id="d" * 16), "candidate", 79.0)]
        seen = {ranking.pick(ranked, self.cfg, True)[0]["id"][0] for _ in range(200)}
        self.assertEqual(seen, {"a", "b"})
        self.assertEqual(ranking.pick(ranked, self.cfg, False)[0]["id"][0], "a")
        self.assertIsNone(ranking.pick([], self.cfg, True))


if __name__ == "__main__":
    unittest.main()
