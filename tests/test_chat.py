"""Loopback integration tests: python -m unittest discover -s tests -v."""

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import queue
import select
import socket
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch
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


class RegistrationCompatibilityTests(unittest.TestCase):
    def test_older_server_reports_restart_instead_of_retrying_username(self):
        # This is the actual response returned by the pre-registration server.
        response = {
            "type": "error", "code": "unsupported_type",
            "text": "Expected chat_message or disconnect",
        }
        with patch.object(client, "receive_message", return_value=response), patch("builtins.input") as prompt:
            with self.assertRaisesRegex(ConnectionError, "restart.*python backend/server.py"):
                client.choose_username(Mock(), "Alice")
        prompt.assert_not_called()


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
        self.names = {}

    @staticmethod
    def stop_process(process):
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        if process.stdin:
            process.stdin.close()
        if process.stdout:
            process.stdout.close()

    def connect(self, username=None, registered=True):
        conn = socket.create_connection(self.address, timeout=5)
        self.addCleanup(conn.close)
        wait_for_line(self.logs, "[ACTIVE CONNECTIONS]")
        if registered:
            self.names[conn] = client.register(conn, username or f"User{len(self.names) + 1}")
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
            self.assertEqual(message["sender_id"], self.names[sender])
            self.assertEqual(message["text"], text)
            self.assertIsNone(message["reply_to"])
            self.assertEqual(uuid.UUID(message["msg_id"]).version, 4)
            self.assertEqual(datetime.fromisoformat(message["timestamp"]).utcoffset(), timedelta(0))
        return received[0]

    def test_every_client_receives_own_and_other_messages(self):
        alice, bob, carol = self.connect("Alice"), self.connect("Bob"), self.connect("Carol")
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
            (self.names[conn], f"{index}:{number}")
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
        reply.update(msg_id="forged-id", sender_id=self.names[alice], timestamp="fake-time")
        client.send(bob, reply)
        received = [client.receive_message(conn) for conn in [alice, bob]]
        self.assertEqual(received[0], received[1])
        message = received[0]
        self.assertEqual(message["reply_to"], original["msg_id"])
        self.assertEqual(message["text"], "Reply")
        self.assertEqual(message["sender_id"], self.names[bob])
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

    def test_registration_required_before_sending_or_receiving_chat(self):
        alice = self.connect("Alice")
        pending = self.connect(registered=False)
        client.send(pending, "Cannot chat yet")
        error = client.receive_message(pending)
        self.assertEqual(error["code"], "registration_required")
        client.send(pending, client.MEMBERLIST_MESSAGE)
        self.assertEqual(client.receive_message(pending)["code"], "registration_required")
        self.assert_broadcast(alice, [alice], "Only registered clients")
        self.assertEqual(select.select([pending], [], [], 0.1)[0], [])
        self.names[pending] = client.register(pending, "Bob")
        self.assert_broadcast(pending, [alice, pending], "Now joined")

    def test_member_list_includes_self_and_unicode_but_excludes_unregistered_clients(self):
        alice = self.connect("Alice")
        bob = self.connect("bob")
        thai = self.connect("\u0e01\u0e32\u0e19\u0e15\u0e4c\U0001f600")
        pending = self.connect(registered=False)
        client.send(alice, client.MEMBERLIST_MESSAGE)
        response = client.receive_message(alice)
        self.assertEqual(response["type"], "member_list")
        self.assertEqual(response["sender_id"], "server")
        self.assertEqual(response["members"], sorted(self.names.values(), key=str.casefold))
        self.assertEqual(len(response["members"]), 3)
        # Neither the request nor its response is broadcast as a chat message.
        self.assertEqual(select.select([bob, thai, pending], [], [], 0.1)[0], [])
        self.assert_broadcast(alice, [alice, bob, thai], "Chat still works")

    def test_member_list_refreshes_after_joins_and_disconnects(self):
        alice = self.connect("Alice")
        client.send(alice, client.MEMBERLIST_MESSAGE)
        self.assertEqual(client.receive_message(alice)["members"], ["Alice"])
        bob, carol = self.connect("Bob"), self.connect("Carol")
        client.send(alice, {"type": "member_list"})
        self.assertEqual(client.receive_message(alice)["members"], ["Alice", "Bob", "Carol"])
        client.send(bob, client.DISCONNECT_MESSAGE)
        self.assertEqual(bob.recv(1), b"")
        wait_for_line(self.logs, "[DISCONNECTED]")
        carol.close()
        wait_for_line(self.logs, "[DISCONNECTED]")
        client.send(alice, client.MEMBERLIST_MESSAGE)
        self.assertEqual(client.receive_message(alice)["members"], ["Alice"])

    def test_member_list_command_text_can_still_be_sent_as_explicit_chat(self):
        alice, bob = self.connect("Alice"), self.connect("Bob")
        client.send(alice, client.create_message("!MEMBERLIST"))
        for conn in [alice, bob]:
            self.assertEqual(client.receive_message(conn)["text"], "!MEMBERLIST")

    def test_username_length_and_unicode_are_preserved_for_every_client(self):
        names = ["a" * 20, "\u0e01" * 20, "\U0001f600" * 20]
        connections = [self.connect(name) for name in names]
        for conn in connections:
            self.assert_broadcast(conn, connections, "My name has 20 characters")

    def test_invalid_username_can_be_corrected_on_same_connection(self):
        pending = self.connect(registered=False)
        for name in ["", "   ", "a" * 21, "\u0e01" * 21, "Bad\nName", "Bad\tName", "server", "SERVER", None, 123, []]:
            client.send(pending, {"type": "register", "username": name})
            error = client.receive_message(pending)
            self.assertEqual(error["type"], "error")
            self.assertEqual(error["code"], "invalid_username")
        self.names[pending] = client.register(pending, "  Alice  ")
        self.assertEqual(self.names[pending], "Alice")
        self.assert_broadcast(pending, [pending], "Corrected")

    def test_username_is_unique_and_cannot_be_changed_by_chat_or_reregistration(self):
        alice = self.connect("Alice")
        pending = self.connect(registered=False)
        client.send(pending, {"type": "register", "username": "alice"})
        self.assertEqual(client.receive_message(pending)["code"], "username_taken")
        self.names[pending] = client.register(pending, "Bob")
        client.send(alice, {"type": "register", "username": "Carol"})
        self.assertEqual(client.receive_message(alice)["code"], "already_registered")
        self.assert_broadcast(alice, [alice, pending], "Still Alice")

    def test_simultaneous_registration_cannot_claim_the_same_name(self):
        first, second = self.connect(registered=False), self.connect(registered=False)
        barrier = threading.Barrier(2)

        def request(conn, name):
            barrier.wait(timeout=5)
            client.send(conn, {"type": "register", "username": name})

        threads = [
            threading.Thread(target=request, args=(first, "Alice")),
            threading.Thread(target=request, args=(second, "alice")),
        ]
        for thread in threads:
            thread.start()
        responses = [client.receive_message(conn) for conn in [first, second]]
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.assertEqual(sorted(r["type"] for r in responses), ["error", "registered"])
        error = next(r for r in responses if r["type"] == "error")
        self.assertEqual(error["code"], "username_taken")

    def test_username_is_released_after_graceful_and_abrupt_disconnect(self):
        for abrupt in [False, True]:
            alice = self.connect("Alice")
            if abrupt:
                alice.close()
            else:
                client.send(alice, client.DISCONNECT_MESSAGE)
                self.assertEqual(alice.recv(1), b"")
            wait_for_line(self.logs, "[DISCONNECTED]")
        replacement = self.connect("Alice")
        self.assert_broadcast(replacement, [replacement], "Reconnected")

    def test_terminal_client_receives_without_typing_and_echoes_own_message(self):
        alice = self.connect()
        terminal = subprocess.Popen(
            [sys.executable, "-u", "frontend/client.py", "--port", str(self.address[1]), "--username", "TerminalUser"],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", env=self.env,
        )
        self.addCleanup(self.stop_process, terminal)
        output = queue.Queue()
        threading.Thread(
            target=collect_lines, args=(terminal.stdout, output), daemon=True
        ).start()
        wait_for_line(output, "[JOINED] lobby as TerminalUser")
        wait_for_line(self.logs, "[ACTIVE CONNECTIONS]")
        terminal.stdin.write(client.MEMBERLIST_MESSAGE + "\n")
        terminal.stdin.flush()
        wait_for_line(output, "[MEMBERS] Connected members (2):")
        wait_for_line(output, " - TerminalUser")
        wait_for_line(output, f" - {self.names[alice]}")
        self.assertEqual(select.select([alice], [], [], 0.1)[0], [])
        client.send(alice, "Incoming while idle")
        wait_for_line(output, "] Incoming while idle")
        self.assertEqual(client.receive_message(alice)["text"], "Incoming while idle")
        terminal.stdin.write("From the terminal\n")
        terminal.stdin.flush()
        wait_for_line(output, "] From the terminal")
        own = client.receive_message(alice)
        self.assertEqual(own["text"], "From the terminal")
        self.assertEqual(own["sender_id"], "TerminalUser")
        terminal.stdin.write(f"/reply {own['msg_id']} A reply\n")
        terminal.stdin.flush()
        wait_for_line(output, f"reply to: {own['msg_id']}")
        reply = client.receive_message(alice)
        self.assertEqual(reply["reply_to"], own["msg_id"])
        self.assertEqual(reply["text"], "A reply")
        terminal.stdin.write(client.DISCONNECT_MESSAGE + "\n")
        terminal.stdin.flush()
        self.assertEqual(terminal.wait(timeout=5), 0)

    def test_terminal_prompts_again_for_invalid_or_taken_username(self):
        alice = self.connect("Alice")
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
        terminal.stdin.write("x" * 21 + "\n")
        terminal.stdin.flush()
        wait_for_line(output, "[ERROR] Username must contain 1-20")
        terminal.stdin.write("alice\n")
        terminal.stdin.flush()
        wait_for_line(output, "[ERROR] That username is already in use")
        terminal.stdin.write("  Bob  \n")
        terminal.stdin.flush()
        wait_for_line(output, "[JOINED] lobby as Bob")
        terminal.stdin.write("Hello from Bob\n")
        terminal.stdin.flush()
        wait_for_line(output, "[Bob] Hello from Bob")
        message = client.receive_message(alice)
        self.assertEqual(message["sender_id"], "Bob")
        terminal.stdin.write(client.DISCONNECT_MESSAGE + "\n")
        terminal.stdin.flush()
        self.assertEqual(terminal.wait(timeout=5), 0)


if __name__ == "__main__":
    unittest.main()
