import base64
import os
import tempfile

from app.config import Config
from app.services.store import Store

CERT = "-----BEGIN CERTIFICATE-----\nMIIBFAKEFAKEFAKEFAKE0123456789abcdef==\n-----END CERTIFICATE-----"
KEY = "-----BEGIN RSA PRIVATE KEY-----\nMIIBFAKEKEYFAKEKEY0123456789abcdef==\n-----END RSA PRIVATE KEY-----"
STATIC = "-----BEGIN OpenVPN Static key V1-----\n0123456789abcdef0123456789abcdef\n-----END OpenVPN Static key V1-----"

# TEST FIXTURES ONLY: TEST-NET-3 / documentation addresses are NOT global, so tests use
# globally-routable-looking public IPs from well-known ranges that are never contacted.
IP1, IP2, IP3 = "8.8.4.4", "1.1.1.1", "9.9.9.9"


def make_profile(ip=IP1, port=1195, proto="udp", extra="", tls_auth=False, ca=True, cipher="AES-128-CBC"):
    lines = ["client", "dev tun", f"proto {proto}", f"remote {ip} {port}", "nobind", "persist-key",
             "persist-tun", f"cipher {cipher}", "auth SHA1", "verb 3", extra]
    text = "\n".join(l for l in lines if l) + "\n"
    if ca:
        text += f"<ca>\n{CERT}\n</ca>\n<cert>\n{CERT}\n</cert>\n<key>\n{KEY}\n</key>\n"
    if tls_auth:
        text += f"<tls-auth>\n{STATIC}\n</tls-auth>\nkey-direction 1\n"
    return text


HEADER = ("#HostName,IP,Score,Ping,Speed,CountryLong,CountryShort,NumVpnSessions,Uptime,TotalUsers,"
          "TotalTraffic,LogType,Operator,Message,OpenVPN_ConfigData_Base64")


def csv_row(host="vpn1", ip=IP1, score=1000000, ping=20, speed=50_000_000, country="Japan", cc="JP",
            sessions=10, uptime=86400000, profile=None, raw_b64=None):
    if raw_b64 is None:
        raw_b64 = base64.b64encode((profile if profile is not None else make_profile(ip)).encode()).decode()
    return f"{host},{ip},{score},{ping},{speed},{country},{cc},{sessions},{uptime},100,5000,2weeks,op,,{raw_b64}"


def make_csv(rows, header=HEADER):
    return "*vpn_servers\n" + header + "\n" + "\n".join(rows) + "\n*\n"


def temp_store(**cfg_over):
    d = tempfile.mkdtemp()
    cfg = Config(db_path=os.path.join(d, "t.db"), **cfg_over)
    return cfg, Store(cfg.db_path)
