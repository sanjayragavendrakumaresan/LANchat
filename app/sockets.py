"""Threaded, newline-delimited JSON chat transport using only Python sockets."""
from __future__ import annotations

import base64
import binascii
import json
import re
import socket
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

MAX_MESSAGE_LENGTH = 2000
MAX_LINE_BYTES = 16384
MAX_HISTORY = 200
MAX_FILE_SIZE = 25 * 1024 * 1024
FILE_CHUNK_SIZE = 8192
USERNAME_PATTERN = re.compile(r"[^\w .'-]", re.UNICODE)
TRANSFER_ID_PATTERN = re.compile(r"[a-f0-9]{32}")


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_username(value: str) -> str:
    value = USERNAME_PATTERN.sub("", value.strip())
    return " ".join(value.split())[:24] or "Guest"


def _encode(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _iter_json_messages(sock: socket.socket):
    buffer = bytearray()
    while True:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            continue
        if not chunk:
            return
        buffer.extend(chunk)
        while True:
            newline = buffer.find(b"\n")
            if newline < 0:
                if len(buffer) > MAX_LINE_BYTES:
                    raise ValueError("Incoming chat packet is too large")
                break
            line = bytes(buffer[:newline])
            del buffer[:newline + 1]
            if len(line) > MAX_LINE_BYTES:
                raise ValueError("Incoming chat packet is too large")
            if not line:
                continue
            try:
                value = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                yield value


@dataclass(eq=False)
class Peer:
    connection: socket.socket
    username: str
    client_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    send_lock: threading.Lock = field(default_factory=threading.Lock)

    def send(self, payload: dict) -> None:
        data = _encode(payload)
        with self.send_lock:
            self.connection.sendall(data)

    def send_many(self, payloads: list[dict]) -> None:
        data = b"".join(_encode(payload) for payload in payloads)
        with self.send_lock:
            self.connection.sendall(data)


@dataclass
class FileTransfer:
    sender: Peer
    recipient: Peer
    filename: str
    size: int
    accepted: bool = False
    next_index: int = 0
    bytes_received: int = 0


class ChatServer:
    """LAN room host. Bind to an ephemeral port and start listening immediately."""
    def __init__(self, room_name: str) -> None:
        self.room_name = " ".join(room_name.strip().split())[:80] or "LAN Chat Room"
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("0.0.0.0", 0))
        self._listener.listen(32)
        self._listener.settimeout(0.5)
        self.port = self._listener.getsockname()[1]
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._peers: dict[socket.socket, Peer] = {}
        self._transfers: dict[str, FileTransfer] = {}
        self._history: deque[dict] = deque(maxlen=MAX_HISTORY)
        self._thread = threading.Thread(target=self._accept_loop, name="chat-tcp-server", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._listener.close()
        except OSError:
            pass
        with self._lock:
            peers = list(self._peers.values())
            self._peers.clear()
        for peer in peers:
            try:
                peer.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                peer.connection.close()
            except OSError:
                pass
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                connection, _address = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    break
                continue
            connection.settimeout(30.0)
            threading.Thread(target=self._client_loop, args=(connection,), daemon=True,
                             name="chat-client").start()

    def _client_loop(self, connection: socket.socket) -> None:
        peer: Peer | None = None
        try:
            iterator = iter(_iter_json_messages(connection))
            first = next(iterator, None)
            if not first or first.get("type") != "join":
                return
            peer = Peer(connection, clean_username(str(first.get("username", "Guest"))[:80]))
            with self._lock:
                self._peers[connection] = peer
                users = self._users_locked()
                history = list(self._history)
            peer.send({"type": "welcome", "client_id": peer.client_id, "username": peer.username})
            history_events = [{"type": "history_start", "count": len(history)}]
            history_events.extend({"type": "history_item", "message": message} for message in history)
            history_events.append({"type": "history_end"})
            peer.send_many(history_events)
            peer.send({"type": "users", "users": users})
            self._broadcast({"type": "system", "text": f"{peer.username} joined the room.", "time": _timestamp()})
            self._broadcast_users()
            for data in iterator:
                kind = data.get("type")
                if kind == "message":
                    text = data.get("text")
                    if not isinstance(text, str):
                        self._send_error(peer, "Message text must be a string.")
                        continue
                    self._handle_message(peer, text)
                elif kind == "file_offer":
                    self._handle_file_offer(peer, data)
                elif kind == "file_response":
                    self._handle_file_response(peer, data)
                elif kind == "file_chunk":
                    self._handle_file_chunk(peer, data)
                elif kind == "file_complete":
                    self._handle_file_complete(peer, data)
                elif kind == "file_cancel":
                    self._handle_file_cancel(peer, data)
                else:
                    self._send_error(peer, "Unsupported event.")
        except (OSError, ValueError, StopIteration):
            pass
        finally:
            if peer is not None:
                self._remove_peer(peer)
            else:
                try:
                    connection.close()
                except OSError:
                    pass

    def _handle_message(self, peer: Peer, text: str) -> None:
        text = " ".join(text.strip().split())
        if not text:
            return
        if len(text) > MAX_MESSAGE_LENGTH:
            self._send_error(peer, f"Messages must be {MAX_MESSAGE_LENGTH} characters or fewer.")
            return
        message = {
            "type": "message", "id": uuid.uuid4().hex,
            "sender_id": peer.client_id, "username": peer.username,
            "text": text, "time": _timestamp(),
        }
        with self._lock:
            self._history.append(message)
        self._broadcast(message)

    def _handle_file_offer(self, sender: Peer, data: dict) -> None:
        transfer_id = data.get("transfer_id")
        recipient_id = data.get("recipient_id")
        filename = data.get("filename")
        size = data.get("size")
        if not isinstance(transfer_id, str) or not TRANSFER_ID_PATTERN.fullmatch(transfer_id):
            self._send_error(sender, "Invalid file transfer request.")
            return
        if (not isinstance(filename, str) or not filename.strip()
                or len(filename) > 255 or any(ord(char) < 32 for char in filename)):
            self._send_error(sender, "Invalid file name.")
            return
        filename = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
        if filename in ("", ".", ".."):
            self._send_error(sender, "Invalid file name.")
            return
        if (not isinstance(size, int) or isinstance(size, bool)
                or size < 0 or size > MAX_FILE_SIZE):
            self._send_error(sender, f"Files must be {MAX_FILE_SIZE // (1024 * 1024)} MB or smaller.")
            return
        with self._lock:
            recipient = next(
                (peer for peer in self._peers.values() if peer.client_id == recipient_id),
                None,
            )
            if (recipient is None or recipient is sender
                    or transfer_id in self._transfers):
                recipient = None
            else:
                self._transfers[transfer_id] = FileTransfer(sender, recipient, filename, size)
        if recipient is None:
            self._send_error(sender, "That recipient is unavailable.")
            return
        try:
            recipient.send({
                "type": "file_offer", "transfer_id": transfer_id,
                "sender_id": sender.client_id, "username": sender.username,
                "filename": filename, "size": size,
            })
        except OSError:
            self._remove_peer(recipient)
            self._send_error(sender, "The recipient disconnected before the offer arrived.")

    def _handle_file_response(self, recipient: Peer, data: dict) -> None:
        transfer_id = data.get("transfer_id")
        accepted = data.get("accepted")
        with self._lock:
            transfer = self._transfers.get(transfer_id) if isinstance(transfer_id, str) else None
            if transfer is None or transfer.recipient is not recipient:
                transfer = None
            elif isinstance(accepted, bool):
                if accepted:
                    transfer.accepted = True
                else:
                    del self._transfers[transfer_id]
        if transfer is None or not isinstance(accepted, bool):
            self._send_error(recipient, "Invalid or expired file offer.")
            return
        try:
            if accepted:
                transfer.sender.send({
                    "type": "file_accepted", "transfer_id": transfer_id,
                    "username": recipient.username,
                })
            else:
                transfer.sender.send({
                    "type": "file_rejected", "transfer_id": transfer_id,
                    "username": recipient.username,
                })
        except OSError:
            self._remove_peer(transfer.sender)

    def _handle_file_chunk(self, sender: Peer, data: dict) -> None:
        transfer_id = data.get("transfer_id")
        index = data.get("index")
        encoded = data.get("data")
        with self._lock:
            transfer = self._transfers.get(transfer_id) if isinstance(transfer_id, str) else None
            if transfer is None or transfer.sender is not sender:
                transfer = None
            if (transfer is not None and transfer.accepted
                    and isinstance(index, int) and not isinstance(index, bool)
                    and index == transfer.next_index and isinstance(encoded, str)):
                try:
                    chunk = base64.b64decode(encoded, validate=True)
                except (binascii.Error, ValueError):
                    chunk = b""
                    valid_chunk = False
                else:
                    valid_chunk = bool(chunk) and len(chunk) <= FILE_CHUNK_SIZE
                if (valid_chunk and transfer.bytes_received + len(chunk) <= transfer.size):
                    transfer.next_index += 1
                    transfer.bytes_received += len(chunk)
                else:
                    transfer = None
            else:
                transfer = None
        if transfer is None:
            self._send_error(sender, "File chunk is invalid or the recipient has not accepted.")
            return
        try:
            transfer.recipient.send({
                "type": "file_chunk", "transfer_id": transfer_id,
                "index": index, "data": encoded,
            })
        except OSError:
            self._remove_peer(transfer.recipient)
            self._send_error(sender, "The recipient disconnected during the transfer.")

    def _handle_file_complete(self, sender: Peer, data: dict) -> None:
        transfer_id = data.get("transfer_id")
        with self._lock:
            transfer = self._transfers.get(transfer_id) if isinstance(transfer_id, str) else None
            if (transfer is None or transfer.sender is not sender
                    or not transfer.accepted or transfer.bytes_received != transfer.size):
                transfer = None
            else:
                del self._transfers[transfer_id]
        if transfer is None:
            self._send_error(sender, "File transfer is incomplete or invalid.")
            return
        try:
            transfer.recipient.send({
                "type": "file_complete", "transfer_id": transfer_id,
                "filename": transfer.filename, "size": transfer.size,
            })
        except OSError:
            self._remove_peer(transfer.recipient)
            return
        try:
            sender.send({
                "type": "file_sent", "transfer_id": transfer_id,
                "username": transfer.recipient.username,
            })
        except OSError:
            self._remove_peer(sender)

    def _handle_file_cancel(self, peer: Peer, data: dict) -> None:
        transfer_id = data.get("transfer_id")
        with self._lock:
            transfer = self._transfers.get(transfer_id) if isinstance(transfer_id, str) else None
            if transfer is None or peer not in (transfer.sender, transfer.recipient):
                transfer = None
            else:
                del self._transfers[transfer_id]
        if transfer is None:
            return
        other = transfer.recipient if peer is transfer.sender else transfer.sender
        try:
            other.send({"type": "file_cancelled", "transfer_id": transfer_id})
        except OSError:
            self._remove_peer(other)

    def _send_error(self, peer: Peer, text: str) -> None:
        try:
            peer.send({"type": "error", "text": text})
        except OSError:
            self._remove_peer(peer)

    def _users_locked(self) -> list[dict[str, str]]:
        return [{"id": p.client_id, "username": p.username} for p in self._peers.values()]

    def _broadcast_users(self) -> None:
        with self._lock:
            users = self._users_locked()
        self._broadcast({"type": "users", "users": users})

    def _broadcast(self, payload: dict) -> None:
        with self._lock:
            peers = list(self._peers.values())
        stale: list[Peer] = []
        for peer in peers:
            try:
                peer.send(payload)
            except OSError:
                stale.append(peer)
        for peer in stale:
            self._remove_peer(peer)

    def _remove_peer(self, peer: Peer) -> None:
        with self._lock:
            existed = self._peers.pop(peer.connection, None) is not None
            cancelled = [
                (transfer_id, transfer)
                for transfer_id, transfer in self._transfers.items()
                if transfer.sender is peer or transfer.recipient is peer
            ]
            for transfer_id, _transfer in cancelled:
                del self._transfers[transfer_id]
        try:
            peer.connection.close()
        except OSError:
            pass
        if existed and not self._stop.is_set():
            for transfer_id, transfer in cancelled:
                other = transfer.recipient if transfer.sender is peer else transfer.sender
                try:
                    other.send({
                        "type": "file_cancelled", "transfer_id": transfer_id,
                        "text": f"{peer.username} disconnected.",
                    })
                except OSError:
                    self._remove_peer(other)
            self._broadcast({"type": "system", "text": f"{peer.username} left the room.", "time": _timestamp()})
            self._broadcast_users()


class ChatClient:
    """Reconnect-capable TCP client. All callbacks are invoked on its worker thread."""
    def __init__(self, host: str, port: int, username: str,
                 on_event: Callable[[dict], None], on_state: Callable[[str], None]) -> None:
        self.host = host
        self.port = port
        self.username = clean_username(username)
        self.on_event = on_event
        self.on_state = on_state
        self._stop = threading.Event()
        self._socket_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._socket: socket.socket | None = None
        self._thread = threading.Thread(target=self._run, name="chat-tcp-client", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def send_message(self, text: str) -> bool:
        return self.send_event({"type": "message", "text": text})

    def send_event(self, payload: dict) -> bool:
        with self._socket_lock:
            connection = self._socket
        if connection is None:
            return False
        try:
            with self._send_lock:
                connection.sendall(_encode(payload))
            return True
        except OSError:
            return False

    def stop(self) -> None:
        self._stop.set()
        with self._socket_lock:
            connection = self._socket
            self._socket = None
        if connection:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                connection.close()
            except OSError:
                pass
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        first_attempt = True
        while not self._stop.is_set():
            try:
                connection = socket.create_connection((self.host, self.port), timeout=5.0)
                connection.settimeout(0.5)
                with self._socket_lock:
                    self._socket = connection
                connection.sendall(_encode({"type": "join", "username": self.username}))
                self.on_state("Connected")
                first_attempt = False
                for payload in _iter_json_messages(connection):
                    if self._stop.is_set():
                        break
                    self.on_event(payload)
                if self._stop.is_set():
                    break
            except socket.timeout:
                # The receive loop uses short socket timeouts so stop() is responsive.
                continue
            except (OSError, ValueError) as exc:
                if first_attempt:
                    self.on_event({"type": "error", "text": f"Could not connect yet: {exc}"})
                    first_attempt = False
            finally:
                with self._socket_lock:
                    current = self._socket
                    self._socket = None
                if current:
                    try:
                        current.close()
                    except OSError:
                        pass
            if not self._stop.is_set():
                self.on_state("Reconnecting…")
                self._stop.wait(1.5)
        self.on_state("Disconnected")
