import asyncio
import unittest

from app.models.records import ProbeResult
from app.services import vpngate
from app.services.refresh import RefreshWorker
from tests.helpers import IP1, IP2, csv_row, make_csv, make_profile, temp_store

NOW = 3_000_000.0
GOOD = make_csv([csv_row(ip=IP1), csv_row(host="v2", ip=IP2, profile=make_profile(IP2, 443, "tcp"))])


def run(coro):
    return asyncio.run(coro)


class Clock:
    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.cfg, self.store = temp_store()
        self.clock = Clock()

    def worker(self, fetcher, prober=None):
        return RefreshWorker(self.cfg, self.store, fetcher=fetcher, prober=prober, clock=self.clock)

    def test_successful_refresh(self):
        async def f():
            return GOOD
        self.assertTrue(run(self.worker(f).run_refresh()))
        self.assertEqual(len(self.store.all_servers()), 2)
        self.assertEqual(self.store.get_meta_float("last_refresh_ok_ts"), NOW)

    def test_upstream_down_keeps_last_known_good(self):
        async def ok():
            return GOOD

        async def down():
            raise vpngate.FetchError("upstream HTTP 503")
        w = self.worker(ok)
        run(w.run_refresh())
        self.clock.t += 1800
        w.fetcher = down
        self.assertFalse(run(w.run_refresh()))
        self.assertEqual(len(self.store.all_servers()), 2)
        self.assertEqual(self.store.get_meta_float("last_refresh_ok_ts"), NOW)  # unchanged
        self.assertIn("503", self.store.get_meta("last_refresh_error"))
        self.assertEqual(len(self.store.recent_errors()), 1)

    def test_garbage_or_empty_upstream_does_not_wipe(self):
        async def ok():
            return GOOD

        async def html():
            return "<html>Maintenance</html>"

        async def empty():
            return make_csv([csv_row(raw_b64="", profile="")])
        w = self.worker(ok)
        run(w.run_refresh())
        for bad in (html, empty):
            w.fetcher = bad
            self.assertFalse(run(w.run_refresh()))
            self.assertEqual(len(self.store.all_servers()), 2)

    def test_no_overlapping_refresh(self):
        gate = asyncio.Event()
        calls = []

        async def slow():
            calls.append(1)
            await gate.wait()
            return GOOD

        async def main():
            w = self.worker(slow)
            t1 = asyncio.create_task(w.run_refresh())
            await asyncio.sleep(0.05)
            second = await w.run_refresh()  # must return immediately, not start a second fetch
            gate.set()
            return second, await t1
        second, first = run(main())
        self.assertFalse(second)
        self.assertTrue(first)
        self.assertEqual(len(calls), 1)

    def test_probe_round_limits_and_results(self):
        async def f():
            return GOOD
        seen = []

        async def prober(row):
            seen.append(row["id"])
            if row["transport"] == "udp":
                return ProbeResult(True, 33.0, "openvpn_reset")
            return ProbeResult(False, None, "openvpn_reset")
        w = self.worker(f, prober)
        run(w.run_refresh())
        self.assertEqual(run(w.run_probes()), 2)
        by = {r["ip"]: r for r in self.store.all_servers()}
        self.assertEqual(by[IP1]["latency_ms"], 33.0)
        self.assertGreater(by[IP2]["cooldown_until"], NOW)
        # immediately again: nothing is due (recheck interval) -> no extra probes of volunteer servers
        n = len(seen)
        run(w.run_probes())
        self.assertEqual(len(seen), n)

    def test_probe_exception_and_unprobeable_are_handled(self):
        async def f():
            return GOOD

        async def prober(row):
            if row["transport"] == "udp":
                raise RuntimeError("boom")
            return None
        w = self.worker(f, prober)
        run(w.run_refresh())
        self.assertEqual(run(w.run_probes()), 0)

    def test_restart_does_not_refetch_inside_interval(self):
        async def f():
            return GOOD
        w1 = self.worker(f)
        run(w1.tick())
        self.assertEqual(len(self.store.all_servers()), 2)
        fetches = []

        async def counting():
            fetches.append(1)
            return GOOD
        self.clock.t += 60
        w2 = self.worker(counting)  # "restarted" worker, same DB
        run(w2.tick())
        self.assertEqual(fetches, [])
        self.clock.t += self.cfg.refresh_interval_s
        run(w2.tick())
        self.assertEqual(fetches, [1])

    def test_failed_refresh_waits_failure_interval_and_manual_request(self):
        async def down():
            raise vpngate.FetchError("x")
        w = self.worker(down)
        run(w.tick())
        self.assertFalse(w.refresh_due(NOW + self.cfg.refresh_failure_wait_s - 1))
        self.assertTrue(w.refresh_due(NOW + self.cfg.refresh_failure_wait_s))
        self.store.set_meta("refresh_requested", 1)
        self.assertTrue(w.refresh_due(NOW + 1))

    def test_fetch_retry_backoff(self):
        sleeps, attempts = [], []

        async def fake_sleep(s):
            sleeps.append(s)

        async def flaky():
            attempts.append(1)
            if len(attempts) < 3:
                raise vpngate.FetchError("net")
            return "ok"
        out = run(vpngate.fetch_with_retries(flaky, self.cfg, fake_sleep))
        self.assertEqual(out, "ok")
        self.assertEqual(len(sleeps), 2)
        self.assertTrue(2 <= sleeps[0] < 3 and 4 <= sleeps[1] < 5)

        async def always():
            raise vpngate.FetchError("net")
        with self.assertRaises(vpngate.FetchError):
            run(vpngate.fetch_with_retries(always, self.cfg, fake_sleep))

        async def bad_format():
            raise vpngate.UpstreamFormatError("nope")
        sleeps.clear()
        with self.assertRaises(vpngate.UpstreamFormatError):
            run(vpngate.fetch_with_retries(bad_format, self.cfg, fake_sleep))
        self.assertEqual(sleeps, [])  # format errors are not retried

    def test_upstream_url_guard(self):
        self.cfg.upstream_url = "https://evil.example.com/list"
        with self.assertRaises(vpngate.FetchError):
            vpngate.check_upstream_url(self.cfg)


if __name__ == "__main__":
    unittest.main()
