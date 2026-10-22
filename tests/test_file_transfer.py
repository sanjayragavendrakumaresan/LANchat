import base64
import json
import select
import socket
import time
import unittest

from app.sockets import ChatServer


class TestFileTransfer(unittest.TestCase):
    def setUp(self):
        self.server = ChatServer("Test room")
        self.server.start()
        self.clients = []
        self.buffers = {}
        self.client_ids = []
        for username in ("Sender", "Recipient", "Other"):
            client = socket.create_connection(("127.0.0.1", self.server.port), timeout=2)
            client.setblocking(False)
            client.sendall((json.dumps({"type": "join", "username": username}) + "\n").encode())
            self.clients.append(client)
            self.buffers[client] = bytearray()
            event = self._read_until(client, lambda item: item.get("type") == "welcome")
            self.client_ids.append(event["client_id"])

    def tearDown(self):
        for client in self.clients:
            client.close()
        self.server.stop()

    def _read_until(self, client, predicate, timeout=3):
        buffer = self.buffers[client]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ready, _, _ = select.select([client], [], [], max(0, deadline - time.monotonic()))
            if not ready:
                break
            chunk = client.recv(4096)
            if not chunk:
                break
            buffer.extend(chunk)
            while b"\n" in buffer:
                newline = buffer.index(b"\n")
                line = bytes(buffer[:newline])
                del buffer[:newline + 1]
                event = json.loads(line)
                if predicate(event):
                    return event
        self.fail("Timed out waiting for chat event")

    def _send(self, client, payload):
        client.sendall((json.dumps(payload) + "\n").encode())

    def test_file_requires_consent_and_is_delivered_only_to_recipient(self):
        transfer_id = "a" * 32
        self._send(self.clients[0], {
            "type": "file_offer", "transfer_id": transfer_id,
            "recipient_id": self.client_ids[1], "filename": "note.txt", "size": 4,
        })
        offer = self._read_until(self.clients[1], lambda item: item.get("type") == "file_offer")
        self.assertEqual(offer["username"], "Sender")

        chunk = base64.b64encode(b"data").decode("ascii")
        self._send(self.clients[0], {
            "type": "file_chunk", "transfer_id": transfer_id, "index": 0, "data": chunk,
        })
        self._read_until(self.clients[0], lambda item: item.get("type") == "error")
        with self.assertRaises(AssertionError):
            self._read_until(
                self.clients[1], lambda item: item.get("type") == "file_chunk", timeout=0.15
            )

        self._send(self.clients[1], {
            "type": "file_response", "transfer_id": transfer_id, "accepted": True,
        })
        self._read_until(self.clients[0], lambda item: item.get("type") == "file_accepted")
        self._send(self.clients[0], {
            "type": "file_chunk", "transfer_id": transfer_id, "index": 0, "data": chunk,
        })
        delivered = self._read_until(
            self.clients[1], lambda item: item.get("type") == "file_chunk"
        )
        self.assertEqual(base64.b64decode(delivered["data"]), b"data")
        with self.assertRaises(AssertionError):
            self._read_until(
                self.clients[2], lambda item: item.get("type") == "file_chunk", timeout=0.15
            )

        self._send(self.clients[0], {"type": "file_complete", "transfer_id": transfer_id})
        self._read_until(
            self.clients[1], lambda item: item.get("type") == "file_complete"
        )
        self._read_until(self.clients[0], lambda item: item.get("type") == "file_sent")

    def test_declined_file_is_not_forwarded(self):
        transfer_id = "b" * 32
        self._send(self.clients[0], {
            "type": "file_offer", "transfer_id": transfer_id,
            "recipient_id": self.client_ids[1], "filename": "note.txt", "size": 4,
        })
        self._read_until(self.clients[1], lambda item: item.get("type") == "file_offer")
        self._send(self.clients[1], {
            "type": "file_response", "transfer_id": transfer_id, "accepted": False,
        })
        self._read_until(self.clients[0], lambda item: item.get("type") == "file_rejected")

        self._send(self.clients[0], {
            "type": "file_chunk", "transfer_id": transfer_id, "index": 0,
            "data": base64.b64encode(b"data").decode("ascii"),
        })
        self._read_until(self.clients[0], lambda item: item.get("type") == "error")
        with self.assertRaises(AssertionError):
            self._read_until(
                self.clients[1], lambda item: item.get("type") == "file_chunk", timeout=0.15
            )


if __name__ == "__main__":
    unittest.main()
