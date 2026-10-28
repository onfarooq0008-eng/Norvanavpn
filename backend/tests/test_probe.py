import asyncio
import os
import struct
import unittest

from app.services import probe


def server_reply(client_pkt: bytes, good=True) -> bytes:
    sid = client_pkt[1:9]
    srv = os.urandom(8)
    acked = sid if good else os.urandom(8)
    return bytes([probe.OP_SERVER_RESET_V2 << 3]) + srv + b"\x01" + struct.pack(">I", 0) + acked + struct.pack(">I", 0)


class UdpServer(asyncio.DatagramProtocol):
    def __init__(self, mode):
        self.mode = mode

    def connection_made(self, transport):
        self.t = transport

    def datagram_received(self, data, addr):
        if self.mode == "good":
            self.t.sendto(server_reply(data), addr)
        elif self.mode == "spoof":
            self.t.sendto(server_reply(data, good=False), addr)


class ProbeTests(unittest.TestCase):
    def test_packet_and_reply_validation(self):
        sid = b"12345678"
        pkt = probe.build_reset_packet(sid)
        self.assertEqual(len(pkt), 14)
        self.assertEqual(pkt[0] >> 3, probe.OP_CLIENT_RESET_V2)
        self.assertTrue(probe.valid_reset_reply(server_reply(pkt), sid))
        self.assertFalse(probe.valid_reset_reply(server_reply(pkt, good=False), sid))
        self.assertFalse(probe.valid_reset_reply(b"\x00" * 30, sid))
        self.assertFalse(probe.valid_reset_reply(b"", sid))

    def test_refuses_private_targets(self):
        for ip in ("127.0.0.1", "10.0.0.1", "192.168.0.1", "169.254.169.254"):
            with self.assertRaises(ValueError):
                asyncio.run(probe.probe_udp(ip, 1194, 1))

    def _udp(self, mode, timeout=1.0):
        async def main():
            loop = asyncio.get_running_loop()
            tr, _ = await loop.create_datagram_endpoint(lambda: UdpServer(mode), local_addr=("127.0.0.1", 0))
            port = tr.get_extra_info("sockname")[1]
            try:
                return await probe.probe_udp("127.0.0.1", port, timeout, allow_non_global=True)
            finally:
                tr.close()
        return asyncio.run(main())

    def test_udp_good_server(self):
        r = self._udp("good")
        self.assertTrue(r.ok)
        self.assertEqual(r.probe_type, "openvpn_reset")
        self.assertIsNotNone(r.latency_ms)

    def test_udp_silent_and_spoofed_servers_fail(self):
        self.assertFalse(self._udp("silent", 0.6).ok)
        self.assertFalse(self._udp("spoof", 0.6).ok)  # reply not acknowledging our session id

    def _tcp(self, handler, has_auth=False):
        async def main():
            server = await asyncio.start_server(handler, "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]
            try:
                return await probe.probe_tcp("127.0.0.1", port, 1.0, has_auth, allow_non_global=True)
            finally:
                server.close()
                await server.wait_closed()
        return asyncio.run(main())

    def test_tcp_openvpn_server_vs_plain_open_port(self):
        async def vpn(reader, writer):
            n = struct.unpack(">H", await reader.readexactly(2))[0]
            pkt = await reader.readexactly(n)
            rep = server_reply(pkt)
            writer.write(struct.pack(">H", len(rep)) + rep)
            await writer.drain()
            writer.close()

        async def http(reader, writer):
            writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            await writer.drain()
            writer.close()
        r = self._tcp(vpn)
        self.assertTrue(r.ok and r.probe_type == "openvpn_reset")
        self.assertFalse(self._tcp(http).ok)  # open TCP port != OpenVPN
        t = self._tcp(http, has_auth=True)  # tls-auth: only a connect check, labelled as such
        self.assertTrue(t.ok)
        self.assertEqual(t.probe_type, "tcp_connect")

    def test_tcp_closed_port(self):
        async def main():
            return await probe.probe_tcp("127.0.0.1", 1, 0.5, False, allow_non_global=True)
        self.assertFalse(asyncio.run(main()).ok)

    def test_udp_with_tls_auth_is_unprobeable(self):
        row = {"transport": "udp", "has_tls_auth": 1, "ip": "8.8.8.8", "port": 1194}
        self.assertIsNone(asyncio.run(probe.probe_server(row, 1)))


if __name__ == "__main__":
    unittest.main()
