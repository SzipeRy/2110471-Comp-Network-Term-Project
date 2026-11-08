"""Real TCP adapter tests. No Tkinter or external service is needed."""
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
import time
import unittest

from frontend import client as wire
from frontend.network_client import NetworkClient
from frontend.ui.net_interface import NameTakenError, private_room_id


ROOT = Path(__file__).resolve().parents[1]


class Events:
    def __init__(self, client):
        self.queues = {name: queue.Queue() for name in ("message", "users", "groups", "error", "disconnect", "notice")}
        client.set_handlers(*(self.handler(name) for name in ("message", "users", "groups", "error", "disconnect")))

    def handler(self, name):
        def receive(*args):
            value = args[0] if args else None
            target = "notice" if name == "message" and value["type"] == "system_message" else name
            self.queues[target].put(value)
        return receive

    def wait(self, name, predicate=lambda value: True, timeout=5):
        deadline = time.monotonic() + timeout
        while True:
            try:
                value = self.queues[name].get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty:
                raise AssertionError(f"Timed out waiting for {name}") from None
            if predicate(value):
                return value


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self.start_server()

    def start_server(self):
        self.server = subprocess.Popen(
            [sys.executable, "-u", "backend/server.py", "--host", "127.0.0.1", "--port", "0"],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", env=dict(os.environ, PYTHONIOENCODING="utf-8"),
        )
        self.addCleanup(self.stop_server, self.server)
        logs = queue.Queue()
        process = self.server
        def collect():
            for line in process.stdout:
                logs.put(line)
        threading.Thread(target=collect, daemon=True).start()
        deadline = time.monotonic() + 5
        while True:
            line = logs.get(timeout=max(0.01, deadline - time.monotonic()))
            if "[LISTENING]" in line:
                self.address = ("127.0.0.1", int(line.rsplit(":", 1)[1]))
                break

    @staticmethod
    def stop_server(process):
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        process.stdout.close()

    def adapter(self, username):
        client = NetworkClient(refresh_interval=0.1)
        events = Events(client)
        self.addCleanup(client.close)
        confirmed = client.connect(*self.address, username)
        return client, events, confirmed


class NetworkClientTests(ServerTestCase):
    def test_join_notices_reach_members_once_and_repeat_only_after_rejoining(self):
        alice, a, _ = self.adapter("Alice")
        bob, b, _ = self.adapter("บ๊อบ 😀")
        _, outsider, _ = self.adapter("Carol")
        alice.create_group("Study Team")
        a.wait("groups", lambda g: "Study Team" in g)
        bob.join_group("study team")
        notice = a.wait("notice")
        self.assertEqual(notice, b.wait("notice"))
        self.assertEqual(notice["text"], "บ๊อบ 😀 joined the group")
        self.assertEqual(notice["room_id"], "Study Team")
        self.assertEqual(notice["sender"], "server")
        self.assertTrue(outsider.queues["notice"].empty())
        bob.join_group("Study Team")
        with self.assertRaises(queue.Empty):
            a.queues["notice"].get(timeout=0.2)
        with self.assertRaises(queue.Empty):
            b.queues["notice"].get(timeout=0.1)
        bob.leave_group("Study Team")
        b.wait("groups", lambda g: "Study Team" in g and not g["Study Team"].joined)
        bob.join_group("Study Team")
        again = a.wait("notice")
        self.assertEqual(again, b.wait("notice"))
        self.assertNotEqual(again["message_id"], notice["message_id"])
        self.assertTrue(outsider.queues["notice"].empty())
        # Notices are not chat messages that can be quoted or forged by clients.
        alice.send_message("group", "Study Team", "Reply to a notice", notice["message_id"])
        a.wait("error", lambda e: "invalid_reply" in e)
        alice._enqueue({"type": "group_event", "room": "Study Team", "text": "Forged"})
        a.wait("error", lambda e: "unsupported_type" in e)
        self.assertTrue(b.queues["notice"].empty())

    def test_clients_without_notice_subscription_keep_the_original_response_stream(self):
        alice, a, _ = self.adapter("Alice")
        alice.create_group("Study")
        a.wait("groups", lambda g: "Study" in g)
        legacy = socket.create_connection(self.address, timeout=5)
        self.addCleanup(legacy.close)
        wire.register(legacy, "Legacy")
        wire.send(legacy, {"type": "join_group", "room": "Study"})
        self.assertEqual(wire.receive_message(legacy)["type"], "chat_selected")
        a.wait("notice", lambda n: n["username"] == "Legacy")
        alice.send_message("group", "Study", "Still compatible")
        self.assertEqual(wire.receive_message(legacy)["text"], "Still compatible")

    def test_unicode_private_messages_replies_and_own_echo_exclude_outsider(self):
        alice, a, name = self.adapter("  Alice-Smith  ")
        bob, b, _ = self.adapter("บ๊อบ 😀")
        _, outsider, _ = self.adapter("Carol")
        self.assertEqual(name, "Alice-Smith")
        room = private_room_id(name, "บ๊อบ 😀")
        self.assertTrue(alice.send_message("private", room, "สวัสดี ❤️ @Carol"))
        original = a.wait("message")
        self.assertEqual(original, b.wait("message"))
        self.assertEqual(original["sender"], name)
        self.assertEqual(original["room_id"], room)
        self.assertEqual(len(original["message_id"]), 32)
        self.assertIn("Carol", original["mentions"])
        bob.send_message("private", room, "Reply 👍", original["message_id"])
        reply = a.wait("message")
        self.assertEqual(reply, b.wait("message"))
        self.assertEqual(reply["reply_to"], original["message_id"])
        self.assertNotEqual(reply["message_id"], original["message_id"])
        with self.assertRaises(queue.Empty):
            outsider.queues["message"].get(timeout=0.2)
        with self.assertRaises(queue.Empty):
            a.queues["message"].get(timeout=0.1)  # no duplicate optimistic echo

    def test_group_discovery_shows_members_but_not_messages_and_refreshes_after_leave(self):
        alice, a, _ = self.adapter("Alice")
        bob, b, _ = self.adapter("Bob")
        alice.create_group("Study Team")
        a.wait("groups", lambda g: "Study Team" in g and g["Study Team"].joined)
        groups = b.wait("groups", lambda g: "Study Team" in g)
        self.assertFalse(groups["Study Team"].joined)
        self.assertEqual(groups["Study Team"].member_count, 1)
        self.assertEqual(groups["Study Team"].members, ("Alice",))  # R9: member list before joining
        bob.send_message("group", "Study Team", "Forbidden")
        b.wait("error", lambda e: "not_group_member" in e)
        bob.join_group("Study Team")
        b.wait("groups", lambda g: g.get("Study Team") is not None and g["Study Team"].joined)
        a.wait("groups", lambda g: g.get("Study Team") is not None and g["Study Team"].members == ("Alice", "Bob"))
        alice.send_message("group", "Study Team", "Shared 😀")
        original = a.wait("message")
        self.assertEqual(original, b.wait("message"))
        bob.leave_group("Study Team")
        b.wait("groups", lambda g: "Study Team" in g and not g["Study Team"].joined
               and g["Study Team"].members == ("Alice",))  # still listed, without Bob
        alice.send_message("group", "Study Team", "After leave")
        a.wait("message", lambda m: m["text"] == "After leave")
        with self.assertRaises(queue.Empty):
            b.queues["message"].get(timeout=0.2)
        alice.leave_group("Study Team")
        b.wait("groups", lambda g: "Study Team" not in g)
        self.assertTrue(b.queues["error"].empty())

    def test_online_list_updates_after_connect_and_abrupt_close(self):
        _, a, _ = self.adapter("Alice")
        a.wait("users", lambda names: names == ["Alice"])
        bob, _, _ = self.adapter("Bob")
        a.wait("users", lambda names: names == ["Alice", "Bob"])
        bob.close()
        a.wait("users", lambda names: names == ["Alice"])

    def test_registration_errors_allow_retry_and_preserve_canonical_name(self):
        self.adapter("Élodie")
        client = NetworkClient(refresh_interval=0.1)
        Events(client)
        self.addCleanup(client.close)
        with self.assertRaises(NameTakenError):
            client.connect(*self.address, "e\u0301lodie")
        self.assertFalse(client.connected)
        with self.assertRaisesRegex(ConnectionError, "1-20"):
            client.connect(*self.address, "x" * 21)
        self.assertEqual(client.connect(*self.address, "  Bob Smith  "), "Bob Smith")

    def test_invalid_reply_and_large_message_report_errors_without_breaking_connection(self):
        alice, a, _ = self.adapter("Alice")
        bob, b, _ = self.adapter("Bob")
        alice.send_message("group", "lobby", "Bad reply", "unknown")
        a.wait("error", lambda e: "invalid_reply" in e)
        alice.send_message("group", "lobby", "x" * wire.MAX_MESSAGE_BYTES)
        a.wait("error", lambda e: "1 MiB" in e)
        alice.send_message("group", "lobby", "Recovered")
        self.assertEqual(a.wait("message"), b.wait("message"))
        self.assertTrue(alice.connected)

    def test_concurrent_sends_keep_frames_intact(self):
        alice, a, _ = self.adapter("Alice")
        _, b, _ = self.adapter("Bob")
        def send_many(index):
            for i in range(10):
                alice.send_message("group", "lobby", f"{index}:{i}")
        workers = [threading.Thread(target=send_many, args=(i,)) for i in range(3)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=5)
        own = [a.wait("message") for _ in range(30)]
        received = [b.wait("message") for _ in range(30)]
        self.assertEqual(own, received)
        self.assertEqual({m["text"] for m in own}, {f"{i}:{j}" for i in range(3) for j in range(10)})

    def test_server_shutdown_notifies_once_and_client_can_reconnect(self):
        alice, a, _ = self.adapter("Alice")
        session = alice._session
        self.server.terminate()
        self.server.wait(timeout=5)
        a.wait("disconnect")
        alice.close()
        for worker in session.threads:
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
        with self.assertRaises(queue.Empty):
            a.queues["disconnect"].get(timeout=0.2)
        self.assertFalse(alice.connected)
        # Start a fresh server, then reuse the same adapter and handlers.
        self.start_server()
        self.assertEqual(alice.connect(*self.address, "Alice"), "Alice")
        alice.send_message("group", "lobby", "New session")
        a.wait("message", lambda m: m["text"] == "New session")

    def test_intentional_close_is_silent_and_stops_workers(self):
        alice, a, _ = self.adapter("Alice")
        session = alice._session
        alice.close()
        alice.close()
        for worker in session.threads:
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
        self.assertTrue(a.queues["disconnect"].empty())
        self.assertFalse(alice.send_message("group", "lobby", "Offline"))
        a.wait("error", lambda e: "Not connected" in e)


class FragmentedServerTests(unittest.TestCase):
    def test_fragmented_server_frames_are_decoded(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(3)
        self.addCleanup(listener.close)
        finished = threading.Event()
        failures = queue.Queue()
        def serve():
            try:
                conn, _ = listener.accept()
                with conn:
                    wire.receive_message(conn)
                    wire.send(conn, {"type": "registered", "username": "Alice"})
                    message = {"type": "chat_message", "room_type": "group", "room": "lobby",
                               "msg_id": "test-id", "sender_id": "Bob", "text": "ไทย 😀❤️",
                               "reply_to": None, "timestamp": "2026-11-07T07:00:00+00:00"}
                    import json
                    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
                    frame = str(len(body)).encode().ljust(64, b" ") + body
                    for offset in range(0, len(frame), 3):
                        conn.sendall(frame[offset:offset + 3])
                    # Keep the connection open until the test has received the message.
                    finished.wait(timeout=3)
            except Exception as exc:
                failures.put(exc)
        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        client = NetworkClient()
        events = Events(client)
        self.addCleanup(client.close)
        client.connect(*listener.getsockname(), "Alice")
        self.assertEqual(events.wait("message")["text"], "ไทย 😀❤️")
        finished.set()
        worker.join(timeout=3)
        self.assertTrue(failures.empty())

    def test_unresponsive_registration_times_out_and_can_be_closed(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        self.addCleanup(listener.close)
        client = NetworkClient(connect_timeout=0.15)
        self.addCleanup(client.close)
        with self.assertRaises(TimeoutError):
            client.connect(*listener.getsockname(), "Alice")
        self.assertFalse(client.connected)
        conn, _ = listener.accept()
        conn.close()


if __name__ == "__main__":
    unittest.main()
