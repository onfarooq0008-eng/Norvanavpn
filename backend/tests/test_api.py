"""REST layer tests. Require fastapi + httpx (pip install -r requirements.txt); skipped otherwise."""
import base64
import unittest

try:
    from fastapi.testclient import TestClient
    from app.main import create_app
    HAVE = True
except Exception:  # pragma: no cover
    HAVE = False

from app.services.vpngate import parse_csv
from tests.helpers import IP1, IP2, csv_row, make_csv, make_profile, temp_store

NOW = 5_000_000.0
ADMIN = "a" * 40


@unittest.skipUnless(HAVE, "fastapi/httpx not installed in this environment")
class ApiTests(unittest.TestCase):
    def setUp(self):
        self.cfg, self.store = temp_store(admin_secret=ADMIN, app_api_key="", rate_limit_connect_per_min=3)
        res = parse_csv(make_csv([csv_row(ip=IP1), csv_row(host="v2", ip=IP2, profile=make_profile(IP2, 443, "tcp"))]), self.cfg)
        self.store.upsert_inventory(res.servers, NOW)
        self.store.heartbeat(NOW)
        self.c = TestClient(create_app(self.cfg, self.store, clock=lambda: NOW + 10), raise_server_exceptions=False)

    def test_health(self):
        r = self.c.get("/health")
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertEqual(j["status"], "ok")
        self.assertNotIn("db_path", str(j))

    def test_servers_listing_filters_and_pagination(self):
        j = self.c.get("/api/v1/servers?limit=1").json()
        self.assertEqual((j["total"], len(j["servers"])), (2, 1))
        self.assertNotIn("openvpn_profile", str(j))
        self.assertEqual(self.c.get("/api/v1/servers?protocol=tcp").json()["total"], 1)
        self.assertEqual(self.c.get("/api/v1/servers?protocol=icmp").status_code, 400)
        self.assertEqual(self.c.get("/api/v1/servers?limit=9999").status_code, 400)

    def test_fastest_and_connect_flow(self):
        self.assertTrue(self.c.get("/api/v1/servers/fastest").json()["success"])
        r = self.c.post("/api/v1/connect", json={"protocol": "udp"})
        self.assertEqual(r.status_code, 200)
        j = r.json()
        sid, cid = j["server"]["id"], j["connection_id"]
        self.assertIn("<ca>", j["openvpn_profile"])
        self.assertEqual(self.c.post(f"/api/v1/servers/{sid}/success", json={"connection_id": cid}).status_code, 200)
        self.assertEqual(self.c.post(f"/api/v1/servers/{sid}/success", json={"connection_id": cid}).status_code, 409)
        self.assertEqual(self.c.post("/api/v1/disconnect", json={"connection_id": cid}).status_code, 200)

    def test_connect_without_body_and_rate_limit(self):
        for _ in range(3):
            self.assertEqual(self.c.post("/api/v1/connect").status_code, 200)
        r = self.c.post("/api/v1/connect")
        self.assertEqual(r.status_code, 429)
        self.assertIn("Retry-After", r.headers)

    def test_failure_validation(self):
        cid = "x" * 30
        self.assertEqual(self.c.post("/api/v1/servers/NOT-AN-ID/failure", json={"connection_id": cid}).status_code, 400)
        self.assertEqual(self.c.post("/api/v1/servers/0123456789abcdef/failure", json={"connection_id": cid}).status_code, 404)
        self.assertEqual(self.c.post("/api/v1/servers/0123456789abcdef/failure", json={"connection_id": "x"}).status_code, 400)
        self.assertEqual(self.c.post("/api/v1/servers/0123456789abcdef/failure", json={"connection_id": cid, "evil": 1}).status_code, 400)

    def test_error_bodies_do_not_leak(self):
        r = self.c.post("/api/v1/connect", json={"protocol": "<script>"})
        self.assertEqual(r.status_code, 400)
        self.assertNotIn("<script>", r.text)
        self.assertNotIn("Traceback", self.c.get("/nope").text)
        self.assertEqual(self.c.get("/nope").json()["error"]["code"], "not_found")

    def test_oversized_body(self):
        r = self.c.post("/api/v1/connect", content=b"{" + b" " * 20000 + b"}", headers={"content-type": "application/json"})
        self.assertEqual(r.status_code, 413)

    def test_admin_requires_auth(self):
        for path in ("/admin/", "/admin/api/status"):
            self.assertEqual(self.c.get(path).status_code, 401)
        tok = "Basic " + base64.b64encode(f"admin:{ADMIN}".encode()).decode()
        self.assertEqual(self.c.get("/admin/", headers={"Authorization": tok}).status_code, 200)
        self.assertEqual(self.c.post("/admin/refresh").status_code, 401)
        self.assertEqual(self.c.post("/admin/refresh", headers={"Authorization": tok}).status_code, 200)

    def test_docs_disabled(self):
        self.assertEqual(self.c.get("/docs").status_code, 404)
        self.assertEqual(self.c.get("/openapi.json").status_code, 404)

    def test_app_key_enforced_when_configured(self):
        self.cfg.app_api_key = "k" * 32
        self.assertEqual(self.c.get("/api/v1/stats").status_code, 401)
        self.assertEqual(self.c.get("/api/v1/stats", headers={"X-API-Key": "k" * 32}).status_code, 200)
        self.assertEqual(self.c.get("/health").status_code, 200)


if __name__ == "__main__":
    unittest.main()
