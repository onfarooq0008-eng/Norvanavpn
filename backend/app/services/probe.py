"""Lightweight reachability probes.

A probe is NOT a VPN test. For UDP (no tls-auth/tls-crypt) and TCP (no tls-auth/tls-crypt) we send one
OpenVPN P_CONTROL_HARD_RESET_CLIENT_V2 packet and require a well-formed P_CONTROL_HARD_RESET_SERVER_V2
reply that acknowledges our session id: proof an OpenVPN daemon answers on that port. With tls-auth/
tls-crypt we cannot craft a valid packet, so TCP gets a plain connect check (probe_type=tcp_connect)
and UDP is not probed at all (stays 'candidate').
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import struct
import time
from typing import Optional

from app.models.records import ProbeResult

OP_CLIENT_RESET_V2 = 7
OP_SERVER_RESET_V2 = 8


def build_reset_packet(session_id: bytes) -> bytes:
    assert len(session_id) == 8
    return bytes([OP_CLIENT_RESET_V2 << 3]) + session_id + b"\x00" + struct.pack(">I", 0)


def valid_reset_reply(data: bytes, session_id: bytes) -> bool:
    if len(data) < 1 + 8 + 1 + 4 + 8 + 4 or data[0] >> 3 != OP_SERVER_RESET_V2:
        return False
    n_ack = data[9]
    if n_ack < 1 or n_ack > 8:
        return False
    off = 10 + 4 * n_ack
    return data[off:off + 8] == session_id


def _check_target(ip: str, allow_non_global: bool) -> None:
    obj = ipaddress.ip_address(ip)
    if not allow_non_global and (obj.version != 4 or not obj.is_global):
        raise ValueError("refusing to probe non-public address")


class _UdpProto(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.queue: "asyncio.Queue[bytes]" = asyncio.Queue()

    def datagram_received(self, data: bytes, addr) -> None:
        self.queue.put_nowait(data)


async def probe_udp(ip: str, port: int, timeout: float, allow_non_global: bool = False) -> ProbeResult:
    _check_target(ip, allow_non_global)
    sid = os.urandom(8)
    pkt = build_reset_packet(sid)
    loop = asyncio.get_running_loop()
    try:
        transport, proto = await loop.create_datagram_endpoint(_UdpProto, remote_addr=(ip, port))
    except OSError:
        return ProbeResult(False, None, "openvpn_reset")
    try:
        start = time.monotonic()
        deadline = start + timeout
        for attempt in range(2):  # one retry: UDP may drop a packet
            transport.sendto(pkt)
            wait_until = min(deadline, start + (attempt + 1) * timeout / 2)
            while True:
                remaining = wait_until - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    data = await asyncio.wait_for(proto.queue.get(), remaining)
                except asyncio.TimeoutError:
                    break
                if valid_reset_reply(data, sid):
                    return ProbeResult(True, (time.monotonic() - start) * 1000, "openvpn_reset")
        return ProbeResult(False, None, "openvpn_reset")
    finally:
        transport.close()


async def probe_tcp(ip: str, port: int, timeout: float, has_tls_auth: bool,
                    allow_non_global: bool = False) -> ProbeResult:
    _check_target(ip, allow_non_global)
    start = time.monotonic()
    ptype = "tcp_connect" if has_tls_auth else "openvpn_reset"
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout)
    except (OSError, asyncio.TimeoutError):
        return ProbeResult(False, None, ptype)
    try:
        connect_ms = (time.monotonic() - start) * 1000
        if has_tls_auth:
            return ProbeResult(True, connect_ms, "tcp_connect")
        sid = os.urandom(8)
        pkt = build_reset_packet(sid)
        writer.write(struct.pack(">H", len(pkt)) + pkt)
        await writer.drain()
        remaining = max(0.1, timeout - (time.monotonic() - start))
        hdr = await asyncio.wait_for(reader.readexactly(2), remaining)
        length = struct.unpack(">H", hdr)[0]
        if not 20 <= length <= 200:
            return ProbeResult(False, None, ptype)
        remaining = max(0.1, timeout - (time.monotonic() - start))
        body = await asyncio.wait_for(reader.readexactly(length), remaining)
        if valid_reset_reply(body, sid):
            return ProbeResult(True, (time.monotonic() - start) * 1000, "openvpn_reset")
        return ProbeResult(False, None, ptype)
    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
        return ProbeResult(False, None, ptype)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def probe_server(row: dict, timeout: float) -> Optional[ProbeResult]:
    """None means 'cannot be probed' (UDP + tls-auth/tls-crypt)."""
    if row["transport"] == "tcp":
        return await probe_tcp(row["ip"], row["port"], timeout, bool(row["has_tls_auth"]))
    if row["has_tls_auth"]:
        return None
    return await probe_udp(row["ip"], row["port"], timeout)
