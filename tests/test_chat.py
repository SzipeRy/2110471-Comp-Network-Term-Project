"""Loopback integration tests: python -m unittest discover -s tests -v."""

import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
import time
import unittest

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
        expected = f"[127.0.0.1:{sender.getsockname()[1]}] {text}"
        client.send(sender, text)
        for recipient in recipients:
            self.assertEqual(client.receive_message(recipient), expected)

    def test_every_client_receives_own_and_other_messages(self):
        alice, bob, carol = self.connect(), self.connect(), self.connect()
        recipients = [alice, bob, carol]
        for sender, text in [(alice, "Hello"), (bob, "Hi Alice"), (carol, "")]:
            self.assert_broadcast(sender, recipients, text)

    def test_fragmented_utf8_and_back_to_back_messages(self):
        alice, bob = self.connect(), self.connect()
        text = "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35 \U0001f600" * 200
        payload = text.encode("utf-8")
        frame = str(len(payload)).encode().ljust(client.HEADER, b" ") + payload
        # Split the length header and UTF-8 characters across separate writes.
        for offset in range(0, len(frame), 7):
            alice.sendall(frame[offset:offset + 7])
        client.send(alice, "second")
        for recipient in [alice, bob]:
            self.assertEqual(
                client.receive_message(recipient),
                f"[127.0.0.1:{alice.getsockname()[1]}] {text}",
            )
            self.assertTrue(client.receive_message(recipient).endswith("] second"))

    def test_simultaneous_senders_keep_frames_intact(self):
        connections = [self.connect() for _ in range(3)]
        expected = {
            f"[127.0.0.1:{conn.getsockname()[1]}] {index}:{number}"
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
            self.assertEqual(set(received), expected)
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
        for header in [b"invalid", b"-1", str(client.MAX_MESSAGE_BYTES + 1).encode()]:
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
        self.assertTrue(client.receive_message(alice).endswith("] Incoming while idle"))
        terminal.stdin.write("From the terminal\n")
        terminal.stdin.flush()
        wait_for_line(output, "] From the terminal")
        self.assertTrue(client.receive_message(alice).endswith("] From the terminal"))
        terminal.stdin.write(client.DISCONNECT_MESSAGE + "\n")
        terminal.stdin.flush()
        self.assertEqual(terminal.wait(timeout=5), 0)


if __name__ == "__main__":
    unittest.main()
