from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass

from api_client import API_KEY

DISCOVERY_PORT = 47820
PROTOCOL = 1

DEFAULT_TIMEOUT = 1.5
DEFAULT_ATTEMPTS = 3


@dataclass(frozen=True)
class DiscoveredServer:
    host: str
    port: int
    scheme: str
    name: str
    version: str = ""

    @property
    def url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"


def _proof(nonce: str, port: int) -> str:
    return hmac.new(API_KEY.encode("utf-8"),
                    f"{nonce}|{port}".encode("utf-8"),
                    hashlib.sha256).hexdigest()


class _Listener(asyncio.DatagramProtocol):
    def __init__(self, nonce: str):
        self._nonce = nonce
        self.found: dict[str, DiscoveredServer] = {}

    def datagram_received(self, data: bytes, addr) -> None:
        # Anything may arrive on this socket; only a well-formed reply
        # carrying a valid proof counts.
        try:
            reply = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return
        if not isinstance(reply, dict) or reply.get("saint") != "server":
            return

        port = reply.get("port")
        if not isinstance(port, int) or not 0 < port < 65536:
            return
        if not hmac.compare_digest(_proof(self._nonce, port),
                                   str(reply.get("proof", "")).lower()):
            return

        # The address comes from the packet itself, never from its content:
        # it is the address that actually reached this phone.
        host = addr[0]
        server = DiscoveredServer(
            host=host,
            port=port,
            scheme="https" if reply.get("scheme") == "https" else "http",
            name=str(reply.get("name") or host).strip() or host,
            version=str(reply.get("version") or "").strip())
        # Repeated requests bring repeated replies; keep one per address.
        self.found[server.url] = server

    def error_received(self, exc: Exception) -> None:
        # E.g. ICMP "port unreachable" from a host with nothing listening.
        pass


async def discover(timeout: float = DEFAULT_TIMEOUT,
                   attempts: int = DEFAULT_ATTEMPTS) -> list[DiscoveredServer]:
    """Servers that answered within `timeout` seconds, sorted by name.

    Returns an empty list, never raises, when the phone has no usable
    network (no Wi-Fi, airplane mode, mobile data only).
    """
    loop = asyncio.get_running_loop()
    nonce = secrets.token_hex(16)
    payload = json.dumps({"saint": "discover", "v": PROTOCOL,
                          "nonce": nonce}).encode("utf-8")

    try:
        transport, listener = await loop.create_datagram_endpoint(
            lambda: _Listener(nonce), local_addr=("0.0.0.0", 0),
            allow_broadcast=True)
    except OSError:
        return []

    try:
        interval = timeout / max(attempts, 1)
        for _ in range(max(attempts, 1)):
            try:
                transport.sendto(payload, ("255.255.255.255", DISCOVERY_PORT))
            except OSError:
                # No route for a broadcast: not on a local network.
                break
            await asyncio.sleep(interval)
    finally:
        transport.close()

    return sorted(listener.found.values(), key=lambda s: s.name.lower())