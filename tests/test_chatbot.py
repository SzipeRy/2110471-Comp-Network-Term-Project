"""AI chatbot tests (Person 3). Nothing here uses the network or a real API key: the
server runs the offline echo provider, or Gemini or Claude against a local fake API."""
import contextlib
import io
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from backend import chatbot
from frontend import client as wire
import person3_support as p3
import test_chat


class ChatbotUnitTests(unittest.TestCase):
    def test_echo_provider_counts_turns_and_names_the_place(self):
        conversation = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
                        {"role": "user", "content": "c"}]
        self.assertEqual(chatbot.Chatbot("echo").reply(conversation, "Alice", "the room"),
                         ("Echo #2 for Alice in the room: c", True))

    def test_failures_become_explanations_without_logging_the_question(self):
        bot = chatbot.Chatbot("claude")
        no_credentials = TypeError("Could not resolve authentication method. Expected one of api_key, "
                                   "auth_token, or credentials to be set.")
        for error, expected in [(no_credentials, "ANTHROPIC_API_KEY"),
                                (ImportError("No module named 'anthropic'"), "pip install"),
                                (RuntimeError("unexpected"), "Please try again")]:
            with self.subTest(error=type(error).__name__):
                with patch.object(bot, "_ask_claude", side_effect=error), \
                        contextlib.redirect_stdout(io.StringIO()) as log:
                    text, ok = bot.reply([{"role": "user", "content": "secret question"}], "Alice", "x")
                self.assertFalse(ok)
                self.assertIn(expected, text)
                self.assertEqual(log.getvalue(), f"[BOT ERROR] {type(error).__name__}\n")

    def test_configuration_is_validated(self):
        with self.assertRaises(ValueError):
            chatbot.Chatbot("gpt")
        with self.assertRaises(ValueError):
            chatbot.Chatbot("claude", effort="extreme")
        with patch.dict(os.environ, {"CHATBOT_MODEL": "claude-sonnet-5-5", "CHATBOT_EFFORT": "medium"}):
            bot = chatbot.Chatbot()
        self.assertEqual((bot.model, bot.effort), ("claude-sonnet-5-5", "medium"))
        with patch.dict(os.environ):
            os.environ.pop("CHATBOT_MODEL", None)
            os.environ.pop("CHATBOT_EFFORT", None)
            claude, gemini = chatbot.Chatbot("claude"), chatbot.Chatbot()
        self.assertEqual((claude.model, claude.effort), ("claude-opus-5-5", "low"))
        self.assertEqual((gemini.provider, gemini.model), ("gemini", "gemini-3.5-flash-lite"))

    def test_gemini_needs_a_key_and_a_connection(self):
        conversation = [{"role": "user", "content": "secret question"}]
        with patch.dict(os.environ), contextlib.redirect_stdout(io.StringIO()) as log:
            for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "CHATBOT_MODEL"):
                os.environ.pop(name, None)
            bot = chatbot.Chatbot("gemini")
            self.assertIn("GEMINI_API_KEY is not set", bot.describe())
            self.assertEqual(bot.reply(conversation, "Alice", "x"), (chatbot.NOT_CONFIGURED_GEMINI, False))
            with socket.socket() as probe:  # a port with nothing listening on it
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            os.environ.update(GEMINI_API_KEY="test-gemini-key", NO_PROXY="127.0.0.1",
                              GEMINI_BASE_URL=f"http://127.0.0.1:{port}")
            self.assertEqual(bot.describe(), "Gemini gemini-3.5-flash-lite")
            self.assertEqual(bot.reply(conversation, "Alice", "x"), (chatbot.UNREACHABLE, False))
        self.assertNotIn("secret", log.getvalue())

    def test_env_file_only_fills_missing_variables(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"P3_KEEP": "already set"}):
            path = Path(folder) / ".env"
            path.write_text("# comment\nexport P3_NEW='from file'\nP3_KEEP=from file\nnot a setting\n",
                            encoding="utf-8")
            chatbot.load_env_file(path)
            chatbot.load_env_file(Path(folder) / "missing.env")
            self.assertEqual(os.environ["P3_NEW"], "from file")
            self.assertEqual(os.environ["P3_KEEP"], "already set")


class EchoBotServerTests(p3.BotServerTestCase):
    def test_bot_room_is_private_and_remembers_the_conversation(self):
        alice, bob = self.connect("Alice"), self.connect("Bob")
        wire.send(alice, p3.ask("What is TCP?"))
        question = self.receive(alice)
        self.assertEqual((question["room_type"], question["room"], question["sender_id"]),
                         ("bot", "chatbot", "Alice"))
        answer = self.receive(alice)
        self.assertEqual((answer["room_type"], answer["room"], answer["sender_id"], answer["reply_to"]),
                         ("bot", "chatbot", "Bot", None))
        self.assertEqual(answer["text"], "Echo #1 for Alice in their private chatbot room: What is TCP?")
        wire.send(alice, p3.ask("And UDP?", reply_to=answer["msg_id"]))
        self.assertEqual(self.receive(alice)["reply_to"], answer["msg_id"])
        self.assertTrue(self.receive(alice)["text"].startswith("Echo #2 for Alice"))
        self.assert_quiet(bob)
        wire.send(bob, p3.ask("Hi"))
        self.receive(bob)
        self.assertTrue(self.receive(bob)["text"].startswith("Echo #1 for Bob"))
        self.assert_quiet(alice)
        # Replies stay inside one conversation.
        wire.send(alice, wire.create_message("In the lobby"))
        lobby = self.receive(alice)
        self.receive(bob)
        self.assertEqual(self.request(alice, p3.ask("Quote", lobby["msg_id"]), "error")["code"], "invalid_reply")
        self.assertEqual(self.request(bob, p3.ask("Quote", answer["msg_id"]), "error")["code"], "invalid_reply")

    def test_mentioning_the_bot_answers_every_member_and_nobody_else(self):
        alice, bob, carol = self.connect("Alice"), self.connect("Bob"), self.connect("Carol")
        self.request(alice, {"type": "create_group", "room": "Study"}, "chat_selected")
        self.request(bob, {"type": "join_group", "room": "Study"}, "chat_selected")
        wire.send(bob, wire.create_message("@bot what is a socket?", room="Study", room_type="group"))
        question = self.receive(alice)
        self.assertEqual(question, self.receive(bob))
        self.assertEqual(question["mentions"], ["Bot"])
        answer = self.receive(alice)
        self.assertEqual(answer, self.receive(bob))
        self.assertEqual((answer["sender_id"], answer["room_type"], answer["room"], answer["reply_to"]),
                         ("Bot", "group", "Study", question["msg_id"]))
        self.assertEqual(answer["text"], "Echo #1 for Bob in the group chat #Study, where every member "
                                         "can read your answer: @bot what is a socket?")
        self.assert_quiet(carol)
        wire.send(alice, wire.create_message("Thanks", room="Study", room_type="group", reply_to=answer["msg_id"]))
        self.assertEqual(self.receive(alice)["reply_to"], answer["msg_id"])
        self.receive(bob)
        wire.send(alice, wire.create_message("@Bot hello", room="Bob", room_type="private"))
        self.assertEqual(self.receive(alice), self.receive(bob))
        private = self.receive(alice)
        self.assertEqual(private, self.receive(bob))
        self.assertEqual((private["sender_id"], private["participants"]), ("Bot", ["Alice", "Bob"]))
        self.assertIn("a private chat between Alice and Bob", private["text"])
        self.assert_quiet(carol)

    def test_bot_name_is_reserved_and_questions_are_validated(self):
        pending = self.connect()
        for name in ("bot", "BOT", "  Bot  "):
            error = self.request(pending, {"type": "register", "username": name}, "error")
            self.assertEqual(error["code"], "invalid_username")
        self.assertEqual(self.request(pending, p3.ask("Hi"), "error")["code"], "registration_required")
        wire.register(pending, "Alice")
        for text in ("", "   ", "x" * (chatbot.MAX_QUESTION_CHARS + 1)):
            self.assertEqual(self.request(pending, p3.ask(text), "error")["code"], "invalid_message")

    def test_adapter_bot_room_and_answers_in_the_lobby(self):
        alice, a, _ = self.adapter("Alice")
        bob, b, _ = self.adapter("Bob")
        self.assertTrue(alice.supports_bot)
        self.assertTrue(alice.send_message("bot", "chatbot", "Hello bot"))
        own = a.wait("message")
        self.assertEqual((own["room_type"], own["room_id"], own["sender"]), ("bot", "chatbot", "Alice"))
        answer = a.wait("message", timeout=p3.BOT_TIMEOUT)
        self.assertEqual((answer["room_type"], answer["room_id"], answer["sender"]), ("bot", "chatbot", "Bot"))
        bob.send_message("group", "lobby", "@bot hi from Bob")
        question = a.wait("message", lambda m: m["sender"] == "Bob")
        self.assertEqual(question["mentions"], ["Bot"])
        reply = a.wait("message", lambda m: m["sender"] == "Bot", timeout=p3.BOT_TIMEOUT)
        self.assertEqual((reply["room_type"], reply["room_id"], reply["reply_to"]),
                         ("group", "lobby", question["message_id"]))
        seen = []
        b.wait("message", lambda m: seen.append(m) or m["message_id"] == reply["message_id"],
               timeout=p3.BOT_TIMEOUT)
        self.assertNotIn("bot", {m["room_type"] for m in seen + p3.drain(b.queues["message"])})
        self.assertTrue(a.queues["error"].empty())

    def test_terminal_bot_command(self):
        bob = self.connect("Bob")
        terminal = subprocess.Popen(
            [sys.executable, "-u", "frontend/client.py", "--port", str(self.address[1]), "--username", "Alice"],
            cwd=p3.support.ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", env=dict(os.environ, PYTHONIOENCODING="utf-8"),
        )
        self.addCleanup(test_chat.BroadcastChatTests.stop_process, terminal)
        output = queue.Queue()
        threading.Thread(target=test_chat.collect_lines, args=(terminal.stdout, output), daemon=True).start()
        test_chat.wait_for_line(output, "[REGISTERED] as Alice")
        terminal.stdin.write("/bot\n")
        terminal.stdin.flush()
        test_chat.wait_for_line(output, "[ERROR] Use /bot <question>")
        terminal.stdin.write("/bot What is UDP?\n")
        terminal.stdin.flush()
        test_chat.wait_for_line(output, "[bot] [Alice] What is UDP?")
        test_chat.wait_for_line(output, "[bot] [Bot] Echo #1 for Alice in their private chatbot room: What is UDP?")
        self.assert_quiet(bob)
        terminal.stdin.write(wire.DISCONNECT_MESSAGE + "\n")
        terminal.stdin.flush()
        self.assertEqual(terminal.wait(timeout=5), 0)


class GeminiProviderTests(p3.BotServerTestCase):
    def setUp(self):
        self.fake = p3.FakeGemini()
        self.addCleanup(self.fake.close)
        self.server_env = self.fake.server_env()
        super().setUp()

    def test_requests_send_the_prompt_and_text_only_history(self):
        alice = self.connect("Alice")
        self.fake.respond(p3.gemini_reply("TCP is a reliable byte stream."))
        wire.send(alice, p3.ask("What is TCP?"))
        self.receive(alice)
        answer = self.receive(alice)
        self.assertEqual((answer["sender_id"], answer["text"]), ("Bot", "TCP is a reliable byte stream."))
        first = self.fake.requests.get(timeout=5)
        self.assertEqual(first["path"], "/v1beta/models/gemini-3.5-flash-lite:generateContent")
        self.assertEqual(first["headers"]["x-goog-api-key"], "test-gemini-key")
        body = first["body"]
        self.assertEqual(set(body), {"systemInstruction", "contents"})
        system = body["systemInstruction"]["parts"][0]["text"]
        self.assertTrue(system.startswith("You are Bot"))
        self.assertTrue(system.endswith("You are talking with Alice in their private chatbot room."))
        self.assertEqual(body["contents"], [{"role": "user", "parts": [{"text": "What is TCP?"}]}])
        self.fake.respond(p3.gemini_reply("UDP sends datagrams without a connection."))
        wire.send(alice, p3.ask("And UDP?"))
        self.receive(alice)
        self.assertEqual(self.receive(alice)["text"], "UDP sends datagrams without a connection.")
        # The thought summary is never shown or replayed; "assistant" turns become "model".
        self.assertEqual(self.fake.requests.get(timeout=5)["body"]["contents"], [
            {"role": "user", "parts": [{"text": "What is TCP?"}]},
            {"role": "model", "parts": [{"text": "TCP is a reliable byte stream."}]},
            {"role": "user", "parts": [{"text": "And UDP?"}]},
        ])

    def test_errors_blocks_and_busy_retries_reach_only_the_asker(self):
        alice, bob = self.connect("Alice"), self.connect("Bob")
        cases = [
            ([p3.gemini_error(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key.",
                              "API_KEY_INVALID")], "API key was rejected"),
            ([p3.gemini_error(429, "RESOURCE_EXHAUSTED", "Quota exceeded.")], "free quota is used up"),
            ([p3.gemini_error(404, "NOT_FOUND", "models/x is not found.")], "check CHATBOT_MODEL"),
            ([p3.gemini_reply(None, block_reason="SAFETY")], chatbot.REFUSED),
            ([p3.gemini_reply(None, finish_reason="SAFETY")], chatbot.REFUSED),
            ([p3.gemini_error(503, "UNAVAILABLE", "The model is overloaded."),
              p3.gemini_reply("Back again.")], "Back again."),
        ]
        for responses, expected in cases:
            with self.subTest(expected=expected):
                for response in responses:
                    self.fake.respond(response)
                wire.send(alice, p3.ask("A question"))
                self.receive(alice)
                self.assertIn(expected, self.receive(alice)["text"])
        self.assertEqual(self.fake.requests.qsize(), 7)  # the 503 was retried once
        self.assert_quiet(bob)


@unittest.skipUnless(p3.HAS_SDK, "install requirements.txt to test the Claude provider")
class ClaudeProviderTests(p3.BotServerTestCase):
    def setUp(self):
        self.fake = p3.FakeAnthropic()
        self.addCleanup(self.fake.close)
        self.server_env = self.fake.server_env()
        super().setUp()

    def test_requests_use_fallbacks_low_effort_and_text_only_history(self):
        alice = self.connect("Alice")
        self.fake.respond(p3.claude_reply("TCP is a reliable byte stream."))
        wire.send(alice, p3.ask("What is TCP?"))
        self.receive(alice)
        answer = self.receive(alice)
        self.assertEqual((answer["sender_id"], answer["text"]), ("Bot", "TCP is a reliable byte stream."))
        first = self.fake.requests.get(timeout=5)
        body = first["body"]
        self.assertEqual((body["model"], body["max_tokens"]), ("claude-opus-5-5", 16000))
        self.assertEqual(body["output_config"], {"effort": "low"})
        self.assertEqual(body["fallbacks"], "default")
        self.assertIn("server-side-fallback-2026-07-01", first["headers"]["anthropic-beta"])
        headers = first["headers"]  # SDK versions send the key in one of these headers
        self.assertIn("test-key", headers.get("x-api-key", "") + headers.get("authorization", ""))
        self.assertEqual(body["messages"], [{"role": "user", "content": "What is TCP?"}])
        self.assertTrue(body["system"].startswith("You are Bot"))
        self.assertTrue(body["system"].endswith("You are talking with Alice in their private chatbot room."))
        for absent in ("thinking", "temperature", "top_p", "top_k"):
            self.assertNotIn(absent, body)
        self.fake.respond(p3.claude_reply("UDP sends datagrams without a connection."))
        wire.send(alice, p3.ask("And UDP?"))
        self.receive(alice)
        self.assertEqual(self.receive(alice)["text"], "UDP sends datagrams without a connection.")
        second = self.fake.requests.get(timeout=5)["body"]
        # Only text is kept, so trimming old turns can never invalidate a thinking block.
        self.assertEqual(second["messages"], [
            {"role": "user", "content": "What is TCP?"},
            {"role": "assistant", "content": "TCP is a reliable byte stream."},
            {"role": "user", "content": "And UDP?"},
        ])
        self.assertEqual(second["system"], body["system"])

    def test_api_errors_and_refusals_reach_only_the_asker(self):
        alice, bob = self.connect("Alice"), self.connect("Bob")
        self.fake.respond((401, {"type": "error", "error": {"type": "authentication_error",
                                                            "message": "invalid x-api-key"}}))
        wire.send(alice, p3.ask("Hello?"))
        self.receive(alice)
        self.assertIn("API key was rejected", self.receive(alice)["text"])
        self.fake.respond(p3.claude_reply(None, stop_reason="refusal"))
        wire.send(alice, p3.ask("A declined request"))
        self.receive(alice)
        self.assertEqual(self.receive(alice)["text"], chatbot.REFUSED)
        self.fake.respond(p3.claude_reply("Fine."))
        wire.send(alice, p3.ask("Next"))
        self.receive(alice)
        self.receive(alice)
        requests = [self.fake.requests.get(timeout=5)["body"]["messages"] for _ in range(3)]
        # The failed turn is forgotten; the refusal is part of the conversation.
        self.assertEqual(requests[2], [
            {"role": "user", "content": "A declined request"},
            {"role": "assistant", "content": chatbot.REFUSED},
            {"role": "user", "content": "Next"},
        ])
        self.assert_quiet(bob)

    def test_one_question_at_a_time_per_user(self):
        alice, bob = self.connect("Alice"), self.connect("Bob")
        release = threading.Event()
        self.fake.respond(lambda: (release.wait(10), p3.claude_reply("Done."))[1])
        wire.send(alice, p3.ask("Slow question"))
        self.receive(alice)
        self.fake.requests.get(timeout=p3.BOT_TIMEOUT)  # the AI request is now in progress
        self.assertEqual(self.request(alice, p3.ask("Too soon"), "error")["code"], "bot_busy")
        wire.send(alice, wire.create_message("@Bot also too soon"))  # still delivered to the lobby
        self.assertEqual(self.receive(alice)["text"], "@Bot also too soon")
        self.receive(bob)
        self.assertEqual(self.receive(alice, "error")["code"], "bot_busy")
        self.fake.respond(p3.claude_reply("Hi Bob."))  # other users are not blocked
        wire.send(bob, p3.ask("Hello"))
        self.receive(bob)
        self.assertEqual(self.receive(bob)["text"], "Hi Bob.")
        release.set()
        self.assertEqual(self.receive(alice)["text"], "Done.")
        self.fake.respond(p3.claude_reply("Ready again."))
        wire.send(alice, p3.ask("Next"))
        self.receive(alice)
        self.assertEqual(self.receive(alice)["text"], "Ready again.")


if __name__ == "__main__":
    unittest.main()
