"""Helpers for the chatbot and mention tests (Person 3). Not a test module itself."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
import queue
import select
import socket
import threading
from unittest.mock import patch

import test_network_client as support
from frontend import client as wire

BOT_TIMEOUT = 15  # the first AI request also imports the anthropic package
HAS_SDK = importlib.util.find_spec("anthropic") is not None


def ask(text, reply_to=None):
    """A message for the sender's private chatbot room."""
    return wire.create_message(text, room="chatbot", reply_to=reply_to, room_type="bot")


def claude_reply(text, stop_reason="end_turn"):
    """A Messages API response: an empty (omitted) thinking block, then the answer.

    text=None gives the empty content of a request declined before any output.
    """
    content = [] if text is None else [
        {"type": "thinking", "thinking": "", "signature": "test-signature"},
        {"type": "text", "text": text},
    ]
    return 200, {
        "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": content, "stop_reason": stop_reason, "stop_sequence": None,
        "stop_details": ({"type": "refusal", "category": None, "explanation": None}
                         if stop_reason == "refusal" else None),
        "usage": {"input_tokens": 12, "output_tokens": 6},
    }


class FakeAnthropic:
    """A local stand-in for the Claude Messages API: tests need no network or real key.

    Queue responses with respond(); each one is (status, body) or a callable
    returning that. Received requests appear in .requests with lowercase headers.
    """

    def __init__(self):
        self.requests = queue.Queue()
        self._responses = queue.Queue()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                headers = {key.lower(): value for key, value in self.headers.items()}
                fake.requests.put({"path": self.path, "headers": headers, "body": body})
                try:
                    response = fake._responses.get(timeout=10)
                except queue.Empty:
                    response = (500, {"type": "error", "error": {"type": "api_error", "message": "unexpected"}})
                status, payload = response() if callable(response) else response
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def respond(self, response):
        self._responses.put(response)

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def server_env(self):
        return {"CHATBOT_PROVIDER": "claude", "ANTHROPIC_API_KEY": "test-key",
                "ANTHROPIC_BASE_URL": self.url, "NO_PROXY": "127.0.0.1,localhost"}


class FakeGemini(FakeAnthropic):
    """The same local stand-in, configured as the Gemini API (generateContent)."""

    def server_env(self):
        return {"CHATBOT_PROVIDER": "gemini", "GEMINI_API_KEY": "test-gemini-key",
                "GEMINI_BASE_URL": self.url, "NO_PROXY": "127.0.0.1,localhost"}


def gemini_reply(text, finish_reason="STOP", block_reason=None):
    """A generateContent response: a thought summary part, then the answer.

    block_reason gives the response to a question that was blocked before any answer.
    """
    usage = {"promptTokenCount": 12, "candidatesTokenCount": 6, "totalTokenCount": 18}
    if block_reason:
        return 200, {"promptFeedback": {"blockReason": block_reason}, "usageMetadata": usage}
    parts = [{"text": "Thinking about the question.", "thought": True}]
    if text is not None:
        parts.append({"text": text, "thoughtSignature": "c2lnbmF0dXJl"})
    return 200, {"candidates": [{"content": {"role": "model", "parts": parts},
                                 "finishReason": finish_reason, "index": 0}],
                 "usageMetadata": usage, "modelVersion": "gemini-3.5-flash-lite"}


def gemini_error(code, status, message, reason=None):
    """A Google API error body, as the Gemini API sends it."""
    details = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason}] if reason else []
    return code, {"error": {"code": code, "message": message, "status": status, "details": details}}


class BotServerTestCase(support.ServerTestCase):
    """Starts the real server with server_env; the default is the offline echo bot."""

    server_env = {"CHATBOT_PROVIDER": "echo"}

    def setUp(self):
        environment = patch.dict(os.environ, self.server_env)
        environment.start()
        self.addCleanup(environment.stop)
        super().setUp()

    def connect(self, username=None):
        conn = socket.create_connection(self.address, timeout=BOT_TIMEOUT)
        self.addCleanup(conn.close)
        if username is not None:
            wire.register(conn, username)
        return conn

    def receive(self, conn, expected_type="chat_message"):
        message = wire.receive_message(conn)
        self.assertEqual(message["type"], expected_type, message)
        return message

    def request(self, conn, message, expected_type):
        wire.send(conn, message)
        return self.receive(conn, expected_type)

    def assert_quiet(self, *connections):
        self.assertEqual(select.select(list(connections), [], [], 0.1)[0], [])


def drain(events_queue):
    items = []
    while True:
        try:
            items.append(events_queue.get_nowait())
        except queue.Empty:
            return items
