"""Offline UDP room discovery for the native Local Chat desktop app."""
from __future__ import annotations

import json
import logging
import socket
import threading
import time
import uuid
from typing import Any

DISCOVERY_PORT = 37020
PROTOCOL_VERSION = 1
APP_ID = "local-chat-app"
logger = logging.getLogger(__name__)


def get_local_ipv4() -> str:
    """Find the IPv4 interface selected by the local routing table, without sending data."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))
        address = sock.getsockname()[0]
        if address and not address.startswith("127."):
            return address
    except OSError:
        pass
    finally:
        sock.close()
    try:
        for address in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not address.startswith(("127.", "169.254.")):
                return address
    except OSError:
        pass
    return "127.0.0.1"


def _broadcast_targets(local_ip: str) -> set[str]:
    targets = {"255.255.255.255"}
    parts = local_ip.split(".")
    if len(parts) == 4 and all(part.isdigit() and 0 <= int(part) <= 255 for part in parts):
        targets.add(".".join(parts[:3] + ["255"]))
    return targets


def discover_servers(timeout: float = 1.5) -> list[dict[str, Any]]:
    """Broadcast a probe and return chat servers that reply before timeout."""
    nonce = uuid.uuid4().hex
    probe = json.dumps({"type": "chat_discovery_probe", "app": APP_ID,
                        "protocol": PROTOCOL_VERSION, "nonce": nonce}).encode("utf-8")
    results: dict[tuple[str, int], dict[str, Any]] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.15)
    try:
        sock.bind(("", 0))
        for target in _broadcast_targets(get_local_ipv4()):
            try:
                sock.sendto(probe, (target, DISCOVERY_PORT))
            except OSError as exc:
                logger.debug("Could not broadcast discovery to %s: %s", target, exc)
        deadline = time.monotonic() + max(0.1, timeout)
        while time.monotonic() < deadline:
            try:
                payload, sender = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                message = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(message, dict):
                continue
            if (message.get("type") != "chat_discovery_response"
                    or message.get("app") != APP_ID
                    or message.get("protocol") != PROTOCOL_VERSION
                    or message.get("nonce") != nonce):
                continue
            port = message.get("tcp_port")
            if not isinstance(port, int) or not 1 <= port <= 65535:
                continue
            results[(sender[0], port)] = {
                "host": sender[0], "port": port,
                "room": str(message.get("room", "LAN Chat Room"))[:80],
                "hostname": str(message.get("hostname", "Chat host"))[:80],
            }
    finally:
        sock.close()
    return sorted(results.values(), key=lambda room: (room["room"].casefold(), room["host"], room["port"]))


class DiscoveryResponder:
    """Answer local UDP probes with the room's TCP socket address."""
    def __init__(self, tcp_port: int, room_name: str) -> None:
        self.tcp_port = tcp_port
        self.room_name = room_name[:80]
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._serve, name="chat-discovery", daemon=True)
        self._startup_error: OSError | None = None

    def start(self) -> None:
        self._thread.start()
        if not self._ready.wait(2.0):
            raise RuntimeError("UDP discovery listener did not start within 2 seconds")
        if self._startup_error is not None:
            raise RuntimeError(f"Could not open UDP discovery port {DISCOVERY_PORT}: {self._startup_error}")

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.5)

    def _serve(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", DISCOVERY_PORT))
            sock.settimeout(0.5)
            self._ready.set()
            while not self._stop.is_set():
                try:
                    payload, sender = sock.recvfrom(2048)
                except socket.timeout:
                    continue
                except OSError:
                    if self._stop.is_set():
                        break
                    logger.exception("UDP discovery receive failed")
                    continue
                try:
                    request = json.loads(payload.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(request, dict):
                    continue
                if (request.get("type") != "chat_discovery_probe"
                        or request.get("app") != APP_ID
                        or request.get("protocol") != PROTOCOL_VERSION):
                    continue
                response = {
                    "type": "chat_discovery_response", "app": APP_ID,
                    "protocol": PROTOCOL_VERSION,
                    "nonce": str(request.get("nonce", ""))[:64],
                    "tcp_port": self.tcp_port, "room": self.room_name,
                    "hostname": socket.gethostname()[:80],
                }
                try:
                    sock.sendto(json.dumps(response).encode("utf-8"), sender)
                except OSError:
                    logger.debug("Could not reply to discovery probe from %s", sender)
        except OSError as exc:
            self._startup_error = exc
            self._ready.set()
        finally:
            sock.close()
