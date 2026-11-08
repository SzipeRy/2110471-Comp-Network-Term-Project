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


def join_shared_group(conn, name="lobby"):
    """R10: there is no automatic group, so a test user creates or joins one by choice."""
    client.send(conn, {"type": "join_group", "room": name})
    response = client.receive_message(conn)
    if response.get("code") == "group_not_found":
        client.send(conn, {"type": "create_group", "room": name})
        response = client.receive_message(conn)
    assert response["type"] == "chat_selected", response
    return response


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

    def connect(self, username=None, registered=True, lobby=True):
        conn = socket.create_connection(self.address, timeout=5)
        self.addCleanup(conn.close)
        wait_for_line(self.logs, "[ACTIVE CONNECTIONS]")
        if registered:
            self.names[conn] = client.register(conn, username or f"User{len(self.names) + 1}")
            if lobby:
                join_shared_group(conn)
        return conn

    def assert_broadcast(self, sender, recipients, text):
        client.send(sender, text)
        received = [client.receive_message(recipient) for recipient in recipients]
        for message in received:
            self.assertEqual(message, received[0])
            self.assertEqual(set(message), {
                "type", "room", "room_type", "msg_id", "sender_id", "text", "reply_to", "timestamp",
                "mentions",
            })
            self.assertEqual(message["mentions"], [])
            self.assertEqual(message["type"], "chat_message")
            self.assertEqual(message["room"], "lobby")
            self.assertEqual(message["sender_id"], self.names[sender])
            self.assertEqual(message["text"], text)
            self.assertIsNone(message["reply_to"])
            self.assertEqual(uuid.UUID(message["msg_id"]).version, 4)
            self.assertEqual(datetime.fromisoformat(message["timestamp"]).utcoffset(), timedelta(0))
        return received[0]

    def request(self, conn, message, expected_type):
        client.send(conn, message)
        response = client.receive_message(conn)
        self.assertEqual(response["type"], expected_type, response)
        return response

    def assert_quiet(self, *connections):
        self.assertEqual(select.select(list(connections), [], [], 0.1)[0], [])

    def test_groups_start_with_their_creator_and_are_joined_only_by_choice(self):
        # R8, R9, R10: no automatic group; a creator starts alone; others join by themselves.
        alice = self.connect("Alice", lobby=False)
        bob = self.connect("Bob", lobby=False)
        self.assertEqual(self.request(alice, {"type": "group_list"}, "group_list")["groups"], [])
        created = self.request(alice, {"type": "create_group", "room": "Study"}, "chat_selected")
        self.assertEqual(created["members"], ["Alice"])
        study = self.request(bob, {"type": "group_list"}, "group_list")["groups"]
        self.assertEqual(study, [{"name": "Study", "joined": False, "member_count": 1, "members": ["Alice"]}])
        denied = self.request(bob, client.create_message("Let me in", room="Study"), "error")
        self.assertEqual(denied["code"], "not_group_member")
        joined = self.request(bob, {"type": "join_group", "room": "Study"}, "chat_selected")
        self.assertEqual(joined["members"], ["Alice", "Bob"])
        self.request(alice, {"type": "leave_group", "room": "Study"}, "group_left")
        self.request(bob, {"type": "leave_group", "room": "Study"}, "group_left")
        self.assertEqual(self.request(bob, {"type": "group_list"}, "group_list")["groups"], [])

    def test_private_chat_only_reaches_its_two_participants(self):
        alice, bob, carol = self.connect("Alice"), self.connect("Bob"), self.connect("Carol")
        pending = self.connect(registered=False)
        selected = self.request(alice, {
            "type": "select_chat", "room_type": "private", "room": "bob",
        }, "chat_selected")
        self.assertEqual(selected["members"], ["Alice", "Bob"])
        client.handle_input(alice, "Private secret")
        original = client.receive_message(alice)
        self.assertEqual(original, client.receive_message(bob))
        self.assertEqual(original["room"], selected["room"])
        self.assertEqual(original["participants"], ["Alice", "Bob"])
        self.assertEqual(original["text"], "Private secret")
        self.assert_quiet(carol, pending)
        # The reverse direction resolves to the same conversation.
        client.send(bob, client.create_message("Reply", room="Alice", room_type="private", reply_to=original["msg_id"]))
        reply = client.receive_message(alice)
        self.assertEqual(reply, client.receive_message(bob))
        self.assertEqual(reply["room"], original["room"])
        self.assertEqual(reply["sender_id"], "Bob")
        # Guessing a conversation ID cannot subscribe an outsider to it.
        error = self.request(carol, {
            "type": "select_chat", "room_type": "private", "room": original["room"],
        }, "error")
        self.assertEqual(error["code"], "invalid_recipient")
        self.assert_quiet(alice, bob, pending)

    def test_groups_require_membership_for_messages_selection_and_member_lists(self):
        alice, bob, carol = self.connect("Alice"), self.connect("Bob"), self.connect("Carol")
        created = self.request(alice, {"type": "create_group", "room": "Study"}, "chat_selected")
        self.assertEqual(created["members"], ["Alice"])
        joined = self.request(bob, {"type": "join_group", "room": "study"}, "chat_selected")
        self.assertEqual(joined["room"], "Study")
        for request in [
            client.create_message("Intrusion", room="Study"),
            {"type": "select_chat", "room_type": "group", "room": "Study"},
            {"type": "group_members", "room": "Study"},
            {"type": "leave_group", "room": "Study"},
        ]:
            self.assertEqual(self.request(carol, request, "error")["code"], "not_group_member")
        client.handle_input(alice, "Study secret")
        message = client.receive_message(alice)
        self.assertEqual(message, client.receive_message(bob))
        self.assertEqual((message["room_type"], message["room"]), ("group", "Study"))
        self.assert_quiet(carol)
        listing = self.request(carol, {"type": "group_list"}, "group_list")
        study = next(g for g in listing["groups"] if g["name"] == "Study")
        self.assertEqual(study, {"name": "Study", "joined": False, "member_count": 2,
                                 "members": ["Alice", "Bob"]})  # R9: names, but never messages
        self.request(carol, {"type": "join_group", "room": "Study"}, "chat_selected")
        members = self.request(carol, {"type": "group_members", "room": "Study"}, "group_members")
        self.assertEqual(members["members"], ["Alice", "Bob", "Carol"])
        client.handle_input(carol, "Now authorized")
        for conn in [alice, bob, carol]:
            self.assertEqual(client.receive_message(conn)["sender_id"], "Carol")

    def test_failed_destination_change_cannot_fall_back_to_previous_chat(self):
        alice, bob = self.connect("Alice"), self.connect("Bob")
        self.request(alice, {"type": "select_chat", "room_type": "group", "room": "lobby"}, "chat_selected")
        for request in [
            {"type": "select_chat", "room_type": "private", "room": "Missing"},
            {"type": "join_group", "room": "Missing"},
            {"type": "create_group", "room": "lobby"},
        ]:
            self.request(alice, request, "error")
            client.handle_input(alice, "Must not reach the old public chat")
            self.assertEqual(client.receive_message(alice)["code"], "chat_not_selected")
            self.assert_quiet(bob)

    def test_client_cannot_forge_participants_recipients_or_sender(self):
        alice, bob, carol = self.connect("Alice"), self.connect("Bob"), self.connect("Carol")
        request = client.create_message("Only Alice and Bob", room="Bob", room_type="private")
        request.update(sender_id="Carol", participants=["Alice", "Bob", "Carol"], recipients=["Carol"])
        client.send(alice, request)
        delivered = client.receive_message(alice)
        self.assertEqual(delivered, client.receive_message(bob))
        self.assertEqual(delivered["sender_id"], "Alice")
        self.assertEqual(delivered["participants"], ["Alice", "Bob"])
        self.assertNotIn("recipients", delivered)
        self.assert_quiet(carol)

    def test_group_and_user_with_same_name_are_separate_destinations(self):
        alice, bob, carol = self.connect("Alice"), self.connect("Bob"), self.connect("Carol")
        self.request(alice, {"type": "create_group", "room": "Bob"}, "chat_selected")
        self.request(carol, {"type": "join_group", "room": "Bob"}, "chat_selected")
        client.send(alice, client.create_message("For the group", room="Bob", room_type="group"))
        self.assertEqual(client.receive_message(alice)["room_type"], "group")
        self.assertEqual(client.receive_message(carol)["text"], "For the group")
        self.assert_quiet(bob)
        client.send(alice, client.create_message("For the user", room="Bob", room_type="private"))
        self.assertEqual(client.receive_message(alice)["room_type"], "private")
        self.assertEqual(client.receive_message(bob)["text"], "For the user")
        self.assert_quiet(carol)

    def test_switching_destinations_preserves_group_and_private_privacy(self):
        alice, bob, carol = self.connect("Alice"), self.connect("Bob"), self.connect("Carol")
        self.request(alice, {"type": "create_group", "room": "AB"}, "chat_selected")
        self.request(bob, {"type": "join_group", "room": "AB"}, "chat_selected")
        self.request(carol, {"type": "create_group", "room": "AC"}, "chat_selected")
        self.request(alice, {"type": "join_group", "room": "AC"}, "chat_selected")
        client.handle_input(alice, "Only AC")
        self.assertEqual(client.receive_message(alice)["text"], "Only AC")
        self.assertEqual(client.receive_message(carol)["text"], "Only AC")
        self.assert_quiet(bob)
        self.request(alice, {"type": "select_chat", "room_type": "private", "room": "Bob"}, "chat_selected")
        client.handle_input(alice, "Only private AB")
        for conn in [alice, bob]:
            self.assertEqual(client.receive_message(conn)["room_type"], "private")
        self.assert_quiet(carol)
        self.request(alice, {"type": "select_chat", "room_type": "group", "room": "AB"}, "chat_selected")
        client.handle_input(alice, "Only group AB")
        for conn in [alice, bob]:
            self.assertEqual(client.receive_message(conn)["room"], "AB")
        self.assert_quiet(carol)

    def test_leaving_and_disconnecting_remove_group_access_and_delete_empty_groups(self):
        alice, bob = self.connect("Alice"), self.connect("Bob")
        self.request(alice, {"type": "create_group", "room": "Study"}, "chat_selected")
        self.request(bob, {"type": "join_group", "room": "Study"}, "chat_selected")
        self.request(alice, {"type": "leave_group", "room": "Study"}, "group_left")
        client.handle_input(bob, "After Alice left")
        self.assertEqual(client.receive_message(bob)["text"], "After Alice left")
        self.assert_quiet(alice)
        error = self.request(alice, client.create_message("Denied", room="Study"), "error")
        self.assertEqual(error["code"], "not_group_member")
        bob.close()
        wait_for_line(self.logs, "[DISCONNECTED]")
        listing = self.request(alice, {"type": "group_list"}, "group_list")
        self.assertEqual([g["name"] for g in listing["groups"]], ["lobby"])

    def test_reused_username_does_not_inherit_old_private_session(self):
        alice, bob = self.connect("Alice"), self.connect("Bob")
        selected = self.request(alice, {"type": "select_chat", "room_type": "private", "room": "Bob"}, "chat_selected")
        client.handle_input(alice, "Old private session")
        original = client.receive_message(alice)
        client.receive_message(bob)
        bob.close()
        wait_for_line(self.logs, "[DISCONNECTED]")
        replacement = self.connect("Bob")
        client.handle_input(alice, "Do not send to a replacement user")
        self.assertEqual(client.receive_message(alice)["code"], "chat_not_selected")
        self.assert_quiet(replacement)
        fresh = self.request(alice, {"type": "select_chat", "room_type": "private", "room": "Bob"}, "chat_selected")
        self.assertNotEqual(fresh["room"], selected["room"])
        client.handle_input(alice, f"/reply {original['msg_id']} Not this conversation")
        self.assertEqual(client.receive_message(alice)["code"], "invalid_reply")
        self.assert_quiet(replacement)

    def test_cross_conversation_reply_is_rejected_without_leaking_text(self):
        alice, bob, carol = self.connect("Alice"), self.connect("Bob"), self.connect("Carol")
        self.request(alice, {"type": "select_chat", "room_type": "private", "room": "Bob"}, "chat_selected")
        client.handle_input(alice, "Private original")
        original = client.receive_message(alice)
        client.receive_message(bob)
        self.request(alice, {"type": "create_group", "room": "AC"}, "chat_selected")
        self.request(carol, {"type": "join_group", "room": "AC"}, "chat_selected")
        client.handle_input(alice, f"/reply {original['msg_id']} Private content must not be quoted here")
        self.assertEqual(client.receive_message(alice)["code"], "invalid_reply")
        self.assert_quiet(bob, carol)

    def test_group_operations_reject_unregistered_clients_and_invalid_destinations(self):
        pending = self.connect(registered=False)
        for request in [
            {"type": "group_list"}, {"type": "create_group", "room": "Study"},
            {"type": "join_group", "room": "lobby"}, {"type": "group_members", "room": "lobby"},
            {"type": "select_chat", "room_type": "private", "room": "Alice"},
        ]:
            self.assertEqual(self.request(pending, request, "error")["code"], "registration_required")
        alice = self.connect("Alice")
        for request, code in [
            ({"type": "create_group", "room": ""}, "invalid_group"),
            ({"type": "create_group", "room": "x" * 41}, "invalid_group"),
            ({"type": "create_group", "room": "lobby"}, "group_exists"),
            ({"type": "select_chat", "room_type": "private", "room": "Alice"}, "invalid_recipient"),
            ({"type": "select_chat", "room_type": "private", "room": "Missing"}, "user_not_found"),
            ({"type": "select_chat", "room_type": "broadcast", "room": "lobby"}, "unsupported_room_type"),
        ]:
            self.assertEqual(self.request(alice, request, "error")["code"], code)

    def test_terminal_commands_route_private_and_group_messages(self):
        bob, carol = self.connect("Bob Smith"), self.connect("Carol")
        terminal = subprocess.Popen(
            [sys.executable, "-u", "frontend/client.py", "--port", str(self.address[1]), "--username", "Alice"],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", env=self.env,
        )
        self.addCleanup(self.stop_process, terminal)
        output = queue.Queue()
        threading.Thread(target=collect_lines, args=(terminal.stdout, output), daemon=True).start()
        wait_for_line(output, "[REGISTERED] as Alice")
        terminal.stdin.write("/private Bob Smith\nA private hello\n")
        terminal.stdin.flush()
        wait_for_line(output, "[CHAT] Private chat with Bob Smith")
        wait_for_line(output, "[Alice] A private hello")
        private = client.receive_message(bob)
        self.assertEqual(private["room_type"], "private")
        self.assert_quiet(carol)
        terminal.stdin.write("/create Study Team\n")
        terminal.stdin.flush()
        wait_for_line(output, "[CHAT] Group: Study Team")
        self.request(bob, {"type": "join_group", "room": "Study Team"}, "chat_selected")
        terminal.stdin.write("A group hello\n/members Study Team\n/groups\n")
        terminal.stdin.flush()
        wait_for_line(output, "[Alice] A group hello")
        wait_for_line(output, "[GROUP MEMBERS] Study Team: Alice, Bob Smith")
        wait_for_line(output, "Study Team (2 members) [joined]")
        self.assertEqual(client.receive_message(bob)["room"], "Study Team")
        self.assert_quiet(carol)
        terminal.stdin.write("/leave Study Team\nMust choose again\n")
        terminal.stdin.flush()
        wait_for_line(output, "[GROUP] Left group Study Team")
        wait_for_line(output, "[ERROR] chat_not_selected")
        self.assert_quiet(bob, carol)
        terminal.stdin.write(client.DISCONNECT_MESSAGE + "\n")
        terminal.stdin.flush()
        self.assertEqual(terminal.wait(timeout=5), 0)

    def test_every_client_receives_own_and_other_messages(self):
        alice, bob, carol = self.connect("Alice"), self.connect("Bob"), self.connect("Carol")
        recipients = [alice, bob, carol]
        for sender, text in [(alice, "Hello"), (bob, "Hi Alice"), (carol, "")]:
            self.assert_broadcast(sender, recipients, text)

    def test_fragmented_utf8_and_back_to_back_messages(self):
        alice, bob = self.connect(), self.connect()
        text = "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35 \U0001f600" * 200
        payload = json.dumps(client.create_message(text, room="lobby"), ensure_ascii=False).encode("utf-8")
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
        reply = client.create_message("Reply", room="lobby", reply_to=original["msg_id"])
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
            (client.create_message("wrong room", room="study"), "group_not_found"),
            (client.create_message("wrong room", room=None), "invalid_group"),
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
        overhead = len(json.dumps(client.create_message("", room="lobby")).encode("utf-8"))
        client.send(alice, "x" * (client.MAX_MESSAGE_BYTES - overhead))
        error = client.receive_message(alice)
        self.assertEqual(error["type"], "error")
        self.assertEqual(error["code"], "message_too_large")
        with self.assertRaises(ValueError):
            client.send(alice, "x" * client.MAX_MESSAGE_BYTES)
        self.assert_broadcast(alice, [alice], "Small message")

    def test_disconnect_text_inside_chat_is_not_a_control_message(self):
        alice, bob = self.connect(), self.connect()
        client.send(alice, client.create_message("!DISCONNECT", room="lobby"))
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
        join_shared_group(pending)
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
        client.send(alice, client.create_message("!MEMBERLIST", room="lobby"))
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
        join_shared_group(pending)
        self.assertEqual(self.names[pending], "Alice")
        self.assert_broadcast(pending, [pending], "Corrected")

    def test_username_is_unique_and_cannot_be_changed_by_chat_or_reregistration(self):
        alice = self.connect("Alice")
        pending = self.connect(registered=False)
        client.send(pending, {"type": "register", "username": "alice"})
        self.assertEqual(client.receive_message(pending)["code"], "username_taken")
        self.names[pending] = client.register(pending, "Bob")
        join_shared_group(pending)
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
        wait_for_line(output, "[REGISTERED] as TerminalUser")
        wait_for_line(self.logs, "[ACTIVE CONNECTIONS]")
        terminal.stdin.write("/join lobby\n")
        terminal.stdin.flush()
        wait_for_line(output, "[CHAT] Group: lobby")
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
        wait_for_line(output, "[REGISTERED] as Bob")
        terminal.stdin.write("/join lobby\n")
        terminal.stdin.flush()
        wait_for_line(output, "[CHAT] Group: lobby")
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
