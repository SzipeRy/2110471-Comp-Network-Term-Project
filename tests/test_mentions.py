"""@username mention tests (Person 3): the rule, server metadata and privacy, the
network adapter and the terminal notice. Tkinter checks are in test_person3_ui.py."""
import os
import queue
import subprocess
import sys
import threading
import unittest

from backend import mentions as server_rule
from frontend import client as wire
from frontend.ui import mentions as ui_rule
import person3_support as p3
import test_chat

NAMES = ["Bob", "Bob Smith", "บ๊อบ 😀", "Al", "Dr.", "Bot", "a_b", "Élodie"]
CASES = {
    "@Bob hi": ["Bob"],
    "hi @bob": ["Bob"],                         # case-insensitive, canonical spelling back
    "@Bob Smith, lunch?": ["Bob Smith"],        # the longest name wins
    "@Bob Smithers": ["Bob"],                   # "Bob Smith" would run into "ers"
    "@Bobby": [],                               # not a whole name
    "@Bob's slides! @BOB! @Bob😀": ["Bob"],
    "mail@Bob or bob@example.com": [],          # "@" inside a word is not a mention
    "(@Al) and @Al_x or @Alx": ["Al"],
    "@บ๊อบ 😀 สวัสดี": ["บ๊อบ 😀"],               # Thai and emoji names
    "@บ๊อบ 😀สวัสดี": ["บ๊อบ 😀"],                # a name ending in emoji needs no space
    "@บ๊อบสวัสดี": [],
    "@Dr.Who": ["Dr."],
    "@a_b @bot what is TCP?": ["a_b", "Bot"],   # sorted ignoring case
    "@@Bob": ["Bob"],
    "@élodie": ["Élodie"],                # decomposed é matches the NFC name
    "@": [],
    "": [],
}


class MentionRuleTests(unittest.TestCase):
    def test_rule_examples(self):
        for text, expected in CASES.items():
            with self.subTest(text=text):
                self.assertEqual(server_rule.find_mentions(text, NAMES), expected)

    def test_server_and_ui_copies_of_the_rule_agree(self):
        for text in [*CASES, "x@Bob @Bob Smith @bob smithy @Al"]:
            with self.subTest(text=text):
                self.assertEqual(list(ui_rule.mention_spans(text, NAMES)),
                                 list(server_rule.mention_spans(text, NAMES)))
                self.assertEqual(ui_rule.find_mentions(text, NAMES), server_rule.find_mentions(text, NAMES))

    def test_highlighting_and_suggestion_helpers(self):
        self.assertEqual(ui_rule.split_mentions("Hi @bob smith!", ["Bob", "Bob Smith"]),
                         [("Hi ", None), ("@bob smith", "Bob Smith"), ("!", None)])
        self.assertEqual(ui_rule.split_mentions("@Bob", ["Bob"]), [("@Bob", "Bob")])
        self.assertEqual(ui_rule.split_mentions("@Bob", []), [("@Bob", None)])
        self.assertEqual(ui_rule.mention_query("Hi @Bo"), (3, "Bo"))
        self.assertEqual(ui_rule.mention_query("@"), (0, ""))
        self.assertEqual(ui_rule.mention_query("@Bob and @บ๊อ"), (9, "บ๊อ"))
        self.assertIsNone(ui_rule.mention_query("mail@Bo"))
        self.assertIsNone(ui_rule.mention_query("no mention"))
        self.assertIsNone(ui_rule.mention_query("@" + "x" * 21))
        self.assertEqual(ui_rule.suggest("bo", NAMES), ["Bob", "Bob Smith", "Bot"])
        self.assertEqual(ui_rule.suggest("BOB ", NAMES), ["Bob Smith"])
        self.assertEqual(ui_rule.suggest("bob smith", NAMES), [])  # already typed in full
        self.assertEqual(ui_rule.suggest("", ["Carol", "Bob"]), ["Bob", "Carol"])


class MentionServerTests(p3.BotServerTestCase):
    def test_server_derives_canonical_mentions_and_ignores_client_claims(self):
        alice, *others = [self.connect(name) for name in ("Alice", "Bob", "Bob Smith", "บ๊อบ 😀")]
        request = wire.create_message("Hi @bob smith, @บ๊อบ 😀 and @BOB! Not mail@Bob or @Bobby", room="lobby")
        request["mentions"] = ["Alice", "Everyone"]
        wire.send(alice, request)
        received = [self.receive(conn) for conn in [alice, *others]]
        for message in received:
            self.assertEqual(message, received[0])
        self.assertEqual(received[0]["mentions"], ["Bob", "Bob Smith", "บ๊อบ 😀"])

    def test_mentions_never_add_recipients(self):
        alice, bob, carol = self.connect("Alice"), self.connect("Bob"), self.connect("Carol")
        self.request(alice, {"type": "create_group", "room": "Study"}, "chat_selected")
        self.request(bob, {"type": "join_group", "room": "Study"}, "chat_selected")
        wire.send(alice, wire.create_message("@Carol please look", room="Study", room_type="group"))
        grouped = self.receive(alice)
        self.assertEqual(grouped, self.receive(bob))
        self.assertEqual(grouped["mentions"], ["Carol"])
        wire.send(alice, wire.create_message("@carol a secret", room="Bob", room_type="private"))
        private = self.receive(alice)
        self.assertEqual(private, self.receive(bob))
        self.assertEqual(private["mentions"], ["Carol"])
        self.assert_quiet(carol)

    def test_adapter_passes_server_mentions_through(self):
        alice, a, _ = self.adapter("Alice", lobby=True)
        _, b, _ = self.adapter("Bob Smith", lobby=True)
        alice.send_message("group", "lobby", "Hi @bob smith")
        message = b.wait("message", lambda m: m["sender"] == "Alice")
        self.assertEqual(message["mentions"], ["Bob Smith"])
        self.assertEqual(message, a.wait("message", lambda m: m["sender"] == "Alice"))

    def test_terminal_prints_a_notice_when_mentioned(self):
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
        terminal.stdin.write("/join lobby\n")  # R10: Alice joins the group herself
        terminal.stdin.flush()
        test_chat.wait_for_line(output, "[CHAT] Group: lobby")
        wire.send(bob, wire.create_message("@alice stand-up in 5", room="lobby"))
        test_chat.wait_for_line(output, "[Bob] @alice stand-up in 5")
        test_chat.wait_for_line(output, "[MENTION] Bob mentioned you in group: lobby")
        self.assertEqual(self.receive(bob)["mentions"], ["Alice"])

        def lines_until(text):
            seen = []
            while not seen or text not in seen[-1]:
                seen.append(output.get(timeout=p3.BOT_TIMEOUT))
            return seen

        # The echo bot repeats "@alice", but only Bob's own mentions print a notice.
        wire.send(bob, wire.create_message("@Bot say hi to @alice", room="lobby"))
        seen = lines_until("[Bot] Echo #1")
        wire.send(bob, wire.create_message("@alice thanks", room="lobby"))
        seen += lines_until("[Bob] @alice thanks")
        seen += lines_until("[MENTION]")
        self.assertEqual([line.strip("\a\n") for line in seen if "[MENTION]" in line],
                         ["[MENTION] Bob mentioned you in group: lobby"] * 2)
        terminal.stdin.write(wire.DISCONNECT_MESSAGE + "\n")
        terminal.stdin.flush()
        self.assertEqual(terminal.wait(timeout=5), 0)


if __name__ == "__main__":
    unittest.main()
