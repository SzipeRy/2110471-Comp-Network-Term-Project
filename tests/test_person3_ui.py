"""Hidden Tk widgets for the chatbot room and @mentions (Person 3); requires Tkinter."""
import threading
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import person3_support as p3
from frontend.network_client import NetworkClient
from frontend.ui.app import App
from frontend.ui.chat_room import ChatRoom
from frontend.ui.net_interface import private_room_id
from frontend.ui import theme as T


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def labels(widget):
    return [w.cget("text") for w in descendants(widget) if isinstance(w, tk.Label)]


class GuiTestCase(p3.BotServerTestCase):
    def setUp(self):
        super().setUp()
        self.client = NetworkClient(refresh_interval=0.1)
        try:
            self.app = App(self.client)
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        self.app.withdraw()
        self.tk_errors = []
        self.app.report_callback_exception = lambda *error: self.tk_errors.append(error)
        self.addCleanup(lambda: self.assertEqual(self.tk_errors, []))
        self.addCleanup(self.app.close)
        for method in ("showerror", "showwarning"):
            mock = patch(f"frontend.ui.app.messagebox.{method}")
            setattr(self, method, mock.start())
            self.addCleanup(mock.stop)

    def pump(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.update()
            if predicate():
                return
            time.sleep(0.01)
        self.fail("Timed out waiting for Tkinter state")

    def login(self, name):
        self.app.login.host.set(self.address[0])
        self.app.login.port.set(str(self.address[1]))
        self.app.login.name.set(name)
        self.app.login.connect()
        self.pump(lambda: self.app.main is not None)


class MentionGuiTests(GuiTestCase):
    def test_mention_highlight_marker_banner_and_suggestions(self):
        bob, b, _ = self.adapter("Bob")
        _, carol, _ = self.adapter("Carol")
        bob.create_group("Study")
        b.wait("groups", lambda g: "Study" in g)
        self.login("Alice")
        self.client.join_group("Study")
        self.pump(lambda: getattr(self.app.groups.get("Study"), "members", None) == ("Alice", "Bob"))
        main = self.app.main
        main.open_bot()  # another chat is in front when the mention arrives
        bob.send_message("group", "Study", "@alice please review the slides")
        self.pump(lambda: ("group", "Study") in main.rooms and main.rooms[("group", "Study")].messages)
        room = main.rooms[("group", "Study")]
        self.assertEqual(main.tabs.tab(room, "text"), "#Study  @")
        self.assertIn(str(main.mention_dot), str(main.tabs.tab(room, "image")))  # orange dot
        self.assertIn("@", labels(main.groups_box))  # badge on the group's sidebar row
        self.assertTrue(main.mention_bar.winfo_manager())
        self.assertEqual(main.mention_lbl.cget("text"),
                         "🔔 Bob mentioned you in #Study: @alice please review the slides")
        body = next(w for w in descendants(room) if isinstance(w, tk.Text))
        self.assertEqual(body.get(*body.tag_ranges("mention_me")), "@alice")
        bob.send_message("group", "Study", "@Alice and the demo plan")
        self.pump(lambda: len(room.messages) == 2)
        self.assertEqual(main.tabs.tab(room, "text"), "#Study  @2")
        self.assertIn("@2", labels(main.groups_box))
        main.open_mention()
        self.app.update()
        self.assertIs(main.rooms[main._current_key()], room)
        self.assertEqual(main.tabs.tab(room, "text"), "#Study")
        self.assertFalse(main.tabs.tab(room, "image"))
        self.assertFalse([text for text in labels(main.groups_box) if text.startswith("@")])
        self.assertFalse(main.mention_bar.winfo_manager())

        # Typing "@" offers this chat's members and the bot; Up/Down and Enter pick one.
        room.entry.insert("end", "Thanks @b")
        room.entry.icursor("end")
        room.update_mention_suggestions()
        self.assertEqual(room.suggested, ["Bob", "Bot"])
        self.assertTrue(room.suggest_box.winfo_manager())
        self.assertEqual(room._move_suggestion(1), "break")
        self.assertEqual(room._move_suggestion(1), "break")  # wraps back to Bob
        self.assertEqual(room._on_return(), "break")         # Enter completes instead of sending
        self.assertEqual(room.entry.get(), "Thanks @Bob ")
        self.assertFalse(room.suggest_box.winfo_manager())
        room.entry.insert("end", "and @Carol")
        room.send_btn.invoke()
        sent = b.wait("message", lambda m: m["sender"] == "Alice")
        self.assertEqual(sent["mentions"], ["Bob", "Carol"])
        self.pump(lambda: sent["message_id"] in room.messages)
        self.assertIn("Carol is not in this chat, so they will not see this message", labels(room))
        self.assertNotIn("Study", {m["room_id"] for m in p3.drain(carol.queues["message"])})
        self.assertFalse(self.showerror.called)

    def test_bot_answers_highlight_names_but_never_notify(self):
        bob, b, _ = self.adapter("Bob")
        bob.create_group("Study")
        b.wait("groups", lambda g: "Study" in g)
        self.login("Alice")
        self.client.join_group("Study")
        self.pump(lambda: getattr(self.app.groups.get("Study"), "members", None) == ("Alice", "Bob"))
        main = self.app.main
        main.open_bot()  # another chat is in front
        bob.send_message("group", "Study", "@Bot please greet @Alice")
        self.pump(lambda: len(getattr(main.rooms.get(("group", "Study")), "messages", ())) == 2,
                  timeout=p3.BOT_TIMEOUT)
        room = main.rooms[("group", "Study")]
        answer = next(m for m in room.messages.values() if m["sender"] == "Bot")
        self.assertEqual(answer["mentions"], ["Alice"])  # the echo bot repeats the question
        self.assertEqual(room.unread_mentions, 1)  # only Bob's message counts
        self.assertEqual(main.tabs.tab(room, "text"), "#Study  @")
        self.assertTrue(main.mention_lbl.cget("text").startswith("🔔 Bob mentioned you in #Study"))
        bob_text, bot_text = [w for w in descendants(room) if isinstance(w, tk.Text)]
        self.assertEqual((bob_text.cget("bg"), bot_text.cget("bg")), (T.MENTION, T.BOT))
        self.assertEqual(bot_text.get(*bot_text.tag_ranges("mention_me")), "@Alice")

    def test_suggestions_handle_thai_and_emoji_before_the_cursor(self):
        _, peer, _ = self.adapter("บ๊อบ 😀")
        self.login("Alice")
        room = self.app.main._room("private", private_room_id("Alice", "บ๊อบ 😀"), select=True)
        room.entry.insert("end", "😀🎉 @บ")
        room.entry.icursor("end")
        room.update_mention_suggestions()
        self.assertEqual(room.suggested, ["บ๊อบ 😀"])
        room.accept_suggestion()
        self.assertEqual(room.entry.get(), "😀🎉 @บ๊อบ 😀 ")
        room.entry.insert("insert", "hi")
        self.assertEqual(room.entry.get(), "😀🎉 @บ๊อบ 😀 hi")  # the cursor followed the name
        room.send_btn.invoke()
        self.assertEqual(peer.wait("message")["mentions"], ["บ๊อบ 😀"])

    def test_bot_name_is_reserved_on_the_login_screen(self):
        self.app.login.name.set("BOT")
        self.app.login.connect()
        self.assertIn("'Bot' are reserved", self.app.login.status.cget("text"))
        self.assertFalse(self.client.connected)


class Tk86IndexTests(unittest.TestCase):
    def test_cursor_positions_convert_when_tk_counts_emoji_twice(self):
        text = "😀🎉 @บ"

        class Tk86Entry:  # Tk 8.6 counts each character beyond U+FFFF as two
            def get(self):
                return text

            def index(self, where):
                return len(text.encode("utf-16-le")) // 2  # "end" and a cursor at the end

        room = SimpleNamespace(entry=Tk86Entry())
        self.assertEqual(ChatRoom._entry_text(room), (text, 5))
        self.assertEqual(ChatRoom._tk_index(room, text, 3), 5)  # "@" follows two emoji
        self.assertEqual(ChatRoom._tk_index(room, text, 5), 7)


@unittest.skipUnless(p3.HAS_SDK, "install requirements.txt to test the Claude provider")
class ChatbotGuiTests(GuiTestCase):
    def setUp(self):
        self.fake = p3.FakeAnthropic()
        self.addCleanup(self.fake.close)
        self.server_env = self.fake.server_env()
        super().setUp()

    def test_bot_room_shows_typing_and_waits_for_each_answer(self):
        self.login("Alice")
        main = self.app.main
        self.assertIn("🤖 Chatbot", labels(main.ai_box))
        main.open_bot()
        room = main.rooms[("bot", "chatbot")]
        release = threading.Event()
        self.fake.respond(lambda: (release.wait(10), p3.claude_reply("A socket is one end of a connection."))[1])
        room.entry.insert(0, "What is a socket?")
        room.send_btn.invoke()
        self.pump(lambda: len(room.messages) == 1 and room.typing_row is not None)
        self.assertEqual(labels(room.typing_row), ["Bot is typing…"])
        room.entry.insert(0, "Second question")
        room.send_btn.invoke()
        self.assertEqual(room.entry.get(), "Second question")  # kept until the answer arrives
        release.set()
        self.pump(lambda: len(room.messages) == 2, timeout=p3.BOT_TIMEOUT)
        self.assertIsNone(room.typing_row)
        answer = next(m for m in room.messages.values() if m["sender"] == "Bot")
        self.assertEqual(answer["text"], "A socket is one end of a connection.")
        self.assertTrue(any(text.startswith("🤖 Bot  ") for text in labels(room)))
        self.assertEqual(self.fake.requests.qsize(), 1)
        self.assertFalse(self.showerror.called)


if __name__ == "__main__":
    unittest.main()
