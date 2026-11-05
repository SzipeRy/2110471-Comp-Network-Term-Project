"""Loopback integration tests: python -m unittest discover -s tests -v."""

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
import time
import unittest
import uuid

from frontend import client


ROOT = Path(__file__).resolve().parents[1]


def collect_lines(stream, lines):
    for line in stream:
        lines.put(line.rstrip())


def wait_for_line(lines, text, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = lines.get(timeout=max(0.01, deadline - time.monotonic()))
        if text in line:
            return line
    raise AssertionError(f"Did not receive output containing {text!r}")


class BroadcastChatTests(unittest.TestCase):
    def setUp(self):
        self.env = dict(os.environ, PYTHONIOENCODING="utf-8")
        self.server = subprocess.Popen(
            [sys.executable, "-u", "backend/server.py", "--host", "127.0.0.1", "--port", "0"],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", env=self.env,
        )
        self.addCleanup(self.stop_process, self.server)
        self.logs = queue.Queue()
        threading.Thread(
            target=collect_lines, args=(self.server.stdout, self.logs), daemon=True
        ).start()
        listening = wait_for_line(self.logs, "[LISTENING]")
        self.address = ("127.0.0.1", int(listening.rsplit(":", 1)[1]))

    @staticmethod
    def stop_process(process):
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        if process.stdin:
            process.stdin.close()
        if process.stdout:
            process.stdout.close()

    def connect(self):
        conn = socket.create_connection(self.address, timeout=5)
        self.addCleanup(conn.close)
        wait_for_line(self.logs, "[ACTIVE CONNECTIONS]")
        return conn

    def assert_broadcast(self, sender, recipients, text):
        client.send(sender, text)
        received = [client.receive_message(recipient) for recipient in recipients]
        for message in received:
            self.assertEqual(message, received[0])
            self.assertEqual(set(message), {
                "type", "room", "msg_id", "sender_id", "text", "reply_to", "timestamp",
            })
            self.assertEqual(message["type"], "chat_message")
            self.assertEqual(message["room"], "lobby")
            self.assertEqual(message["sender_id"], f"127.0.0.1:{sender.getsockname()[1]}")
            self.assertEqual(message["text"], text)
            self.assertIsNone(message["reply_to"])
            self.assertEqual(uuid.UUID(message["msg_id"]).version, 4)
            self.assertEqual(datetime.fromisoformat(message["timestamp"]).utcoffset(), timedelta(0))
        return received[0]

    def test_every_client_receives_own_and_other_messages(self):
        alice, bob, carol = self.connect(), self.connect(), self.connect()
        recipients = [alice, bob, carol]
        for sender, text in [(alice, "Hello"), (bob, "Hi Alice"), (carol, "")]:
            self.assert_broadcast(sender, recipients, text)

    def test_fragmented_utf8_and_back_to_back_messages(self):
        alice, bob = self.connect(), self.connect()
        text = "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35 \U0001f600" * 200
        payload = json.dumps(client.create_message(text), ensure_ascii=False).encode("utf-8")
        frame = str(len(payload)).encode().ljust(client.HEADER, b" ") + payload
        # Split the length header and UTF-8 characters across separate writes.
        for offset in range(0, len(frame), 7):
            alice.sendall(frame[offset:offset + 7])
        client.send(alice, "second")
        for recipient in [alice, bob]:
            self.assertEqual(client.receive_message(recipient)["text"], text)
            self.assertEqual(client.receive_message(recipient)["text"], "second")

    def test_simultaneous_senders_keep_frames_intact(self):
        connections = [self.connect() for _ in range(3)]
        expected = {
            (f"127.0.0.1:{conn.getsockname()[1]}", f"{index}:{number}")
            for index, conn in enumerate(connections) for number in range(10)
        }

        def send_many(index, conn):
            for number in range(10):
                client.send(conn, f"{index}:{number}")

        threads = [
            threading.Thread(target=send_many, args=(index, conn))
            for index, conn in enumerate(connections)
        ]
        for thread in threads:
            thread.start()
        for conn in connections:
            received = [client.receive_message(conn) for _ in range(30)]
            self.assertEqual({(m["sender_id"], m["text"]) for m in received}, expected)
            self.assertEqual(len({m["msg_id"] for m in received}), 30)
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

    def test_disconnect_and_abrupt_close_leave_others_working(self):
        alice, bob, carol = self.connect(), self.connect(), self.connect()
        client.send(carol, client.DISCONNECT_MESSAGE)
        self.assertEqual(carol.recv(1), b"")
        wait_for_line(self.logs, "[DISCONNECTED]")
        bob.close()
        wait_for_line(self.logs, "[DISCONNECTED]")
        self.assert_broadcast(alice, [alice], "Still connected")

    def test_invalid_frames_only_disconnect_the_offending_client(self):
        alice = self.connect()
        for header in [b"invalid", b"0", b"-1", str(client.MAX_MESSAGE_BYTES + 1).encode()]:
            invalid = self.connect()
            invalid.sendall(header.ljust(client.HEADER, b" "))
            self.assertEqual(invalid.recv(1), b"")
            wait_for_line(self.logs, "[DISCONNECTED]")
        truncated = self.connect()
        truncated.sendall(b"5".ljust(client.HEADER, b" ") + b"he")
        truncated.shutdown(socket.SHUT_WR)
        self.assertEqual(truncated.recv(1), b"")
        wait_for_line(self.logs, "[DISCONNECTED]")
        self.assert_broadcast(alice, [alice], "Server survived")

    def test_invalid_json_only_disconnects_the_offending_client(self):
        alice = self.connect()
        for payload in [b"plain text", b"{", b"[]", b"null", b'"text"', b"\xff"]:
            invalid = self.connect()
            invalid.sendall(str(len(payload)).encode().ljust(client.HEADER, b" ") + payload)
            self.assertEqual(invalid.recv(1), b"")
            wait_for_line(self.logs, "[DISCONNECTED]")
        self.assert_broadcast(alice, [alice], "Valid JSON still works")

    def test_server_assigns_metadata_and_preserves_reply_reference(self):
        alice, bob = self.connect(), self.connect()
        original = self.assert_broadcast(alice, [alice, bob], "Original")
        reply = client.create_message("Reply", reply_to=original["msg_id"])
        reply.update(msg_id="forged-id", sender_id="Alice", timestamp="fake-time")
        client.send(bob, reply)
        received = [client.receive_message(conn) for conn in [alice, bob]]
        self.assertEqual(received[0], received[1])
        message = received[0]
        self.assertEqual(message["reply_to"], original["msg_id"])
        self.assertEqual(message["text"], "Reply")
        self.assertEqual(message["sender_id"], f"127.0.0.1:{bob.getsockname()[1]}")
        self.assertEqual(uuid.UUID(message["msg_id"]).version, 4)
        self.assertNotEqual(message["msg_id"], original["msg_id"])
        self.assertEqual(datetime.fromisoformat(message["timestamp"]).utcoffset(), timedelta(0))

    def test_invalid_requests_return_private_errors_and_connection_stays_usable(self):
        alice, bob = self.connect(), self.connect()
        cases = [
            ({"type": "unknown"}, "unsupported_type"),
            ({}, "unsupported_type"),
            (client.create_message("wrong room", room="study"), "unsupported_room"),
            (client.create_message("wrong room", room=None), "unsupported_room"),
            (client.create_message(123), "invalid_message"),
            (client.create_message("bad reply", reply_to=[]), "invalid_message"),
            (client.create_message("bad reply", reply_to=""), "invalid_message"),
        ]
        for request, code in cases:
            client.send(alice, request)
            error = client.receive_message(alice)
            self.assertEqual(error["type"], "error")
            self.assertEqual(error["code"], code)
            self.assertEqual(error["sender_id"], "server")
        # Bob's first queued message must be this chat, never Alice's errors.
        self.assert_broadcast(alice, [alice, bob], "Recovered")

    def test_json_size_limit_includes_server_metadata(self):
        alice = self.connect()
        overhead = len(json.dumps(client.create_message("")).encode("utf-8"))
        client.send(alice, "x" * (client.MAX_MESSAGE_BYTES - overhead))
        error = client.receive_message(alice)
        self.assertEqual(error["type"], "error")
        self.assertEqual(error["code"], "message_too_large")
        with self.assertRaises(ValueError):
            client.send(alice, "x" * client.MAX_MESSAGE_BYTES)
        self.assert_broadcast(alice, [alice], "Small message")

    def test_disconnect_text_inside_chat_is_not_a_control_message(self):
        alice, bob = self.connect(), self.connect()
        client.send(alice, client.create_message("!DISCONNECT"))
        for conn in [alice, bob]:
            self.assertEqual(client.receive_message(conn)["text"], "!DISCONNECT")
        self.assert_broadcast(alice, [alice, bob], "Still here")

    def test_terminal_client_receives_without_typing_and_echoes_own_message(self):
        alice = self.connect()
        terminal = subprocess.Popen(
            [sys.executable, "-u", "frontend/client.py", "--port", str(self.address[1])],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", env=self.env,
        )
        self.addCleanup(self.stop_process, terminal)
        output = queue.Queue()
        threading.Thread(
            target=collect_lines, args=(terminal.stdout, output), daemon=True
        ).start()
        wait_for_line(output, "[CONNECTED]")
        wait_for_line(self.logs, "[ACTIVE CONNECTIONS]")
        client.send(alice, "Incoming while idle")
        wait_for_line(output, "] Incoming while idle")
        self.assertEqual(client.receive_message(alice)["text"], "Incoming while idle")
        terminal.stdin.write("From the terminal\n")
        terminal.stdin.flush()
        wait_for_line(output, "] From the terminal")
        own = client.receive_message(alice)
        self.assertEqual(own["text"], "From the terminal")
        terminal.stdin.write(f"/reply {own['msg_id']} A reply\n")
        terminal.stdin.flush()
        wait_for_line(output, f"reply to: {own['msg_id']}")
        reply = client.receive_message(alice)
        self.assertEqual(reply["reply_to"], own["msg_id"])
        self.assertEqual(reply["text"], "A reply")
        terminal.stdin.write(client.DISCONNECT_MESSAGE + "\n")
        terminal.stdin.flush()
        self.assertEqual(terminal.wait(timeout=5), 0)


if __name__ == "__main__":
    unittest.main()
