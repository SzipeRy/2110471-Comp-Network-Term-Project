"""Hidden Tk widgets connected to the real server; requires Python's Tkinter."""
import queue
import time
import tkinter as tk
from types import SimpleNamespace
from unittest.mock import patch

import test_network_client as support
from frontend.network_client import NetworkClient
from frontend.ui.app import App
from frontend.ui.emoji_picker import EmojiPicker
from frontend.ui.mock_client import MockClient
from frontend.ui.net_interface import private_room_id


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class GuiIntegrationTests(support.ServerTestCase):
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

    def login(self, name="Alice-Smith 😀"):
        self.app.login.host.set(self.address[0])
        self.app.login.port.set(str(self.address[1]))
        self.app.login.name.set(name)
        self.app.login.connect()
        self.pump(lambda: self.app.main is not None)

    def test_login_private_reply_emoji_and_server_echo(self):
        bob, events, _ = self.adapter("Bob-Jones 😀")
        self.login("  Alice-Smith 😀  ")
        self.assertEqual(self.app.username, "Alice-Smith 😀")
        self.pump(lambda: "Bob-Jones 😀" in self.app.users)
        rid = private_room_id(self.app.username, "Bob-Jones 😀")
        room = self.app.main._room("private", rid, select=True)
        self.assertEqual(self.app.main._title("private", rid), "Bob-Jones 😀")
        room.entry.insert(0, "สวัสดี ")
        room.open_emoji()
        picker = next(w for w in descendants(self.app) if isinstance(w, EmojiPicker))
        next(w for w in picker.winfo_children() if isinstance(w, tk.Button) and w.cget("text") == "❤️").invoke()
        self.assertIn("❤️", room.entry.get())
        room.send_btn.invoke()
        original = events.wait("message")
        self.pump(lambda: original["message_id"] in room.messages)
        self.assertEqual(len(room.messages), 1)
        room.set_reply(original["message_id"])
        room.entry.insert(0, "Reply 👍")
        room.send_btn.invoke()
        reply = events.wait("message")
        self.pump(lambda: reply["message_id"] in room.messages)
        self.assertEqual(reply["reply_to"], original["message_id"])
        self.assertIsNone(room.reply_to)
        bob.send_message("private", rid, "Incoming while idle")
        self.pump(lambda: len(room.messages) == 3)
        self.assertFalse(self.showerror.called)

    def test_group_privacy_join_missing_quote_and_leave(self):
        bob, events, _ = self.adapter("Bob")
        bob.create_group("Study")
        events.wait("groups", lambda g: "Study" in g and g["Study"].joined)
        bob.send_message("group", "Study", "Before Alice joined")
        original = events.wait("message")
        self.login("Alice")
        self.pump(lambda: "Study" in self.app.groups)
        info = self.app.groups["Study"]
        self.assertIsNone(info.members)
        self.app.main.open_group("Study")
        room = self.app.main.rooms[("group", "Study")]
        self.assertEqual(room.entry.cget("state"), "disabled")
        self.assertNotIn("Bob", room.header.cget("text"))
        room.join_btn.invoke()
        self.pump(lambda: room.joined)
        bob.send_message("group", "Study", "Reply to earlier message", original["message_id"])
        self.pump(lambda: bool(room.messages))
        labels = [w.cget("text") for w in descendants(room) if isinstance(w, tk.Label)]
        self.assertIn("Original message unavailable", labels)
        self.client.leave_group("Study")
        self.pump(lambda: not room.joined)
        self.assertEqual(room.entry.cget("state"), "disabled")
        self.assertFalse(self.showerror.called)

    def test_duplicate_name_can_retry_and_disconnect_returns_to_login(self):
        self.adapter("Alice")
        self.app.login.host.set(self.address[0])
        self.app.login.port.set(str(self.address[1]))
        self.app.login.name.set("alice")
        self.app.login.connect()
        self.pump(lambda: "already taken" in self.app.login.status.cget("text"))
        self.assertIsNone(self.app.main)
        self.login("Bob")
        self.server.terminate()
        self.server.wait(timeout=5)
        self.pump(lambda: self.app.main is None)
        self.assertEqual(self.app.login.btn.cget("state"), "normal")
        self.assertEqual(self.app.groups, {})
        self.assertTrue(self.showwarning.called)
        self.start_server()
        self.login("Bob")
        self.app.main.open_group("lobby")
        room = self.app.main.rooms[("group", "lobby")]
        self.pump(lambda: room.joined)
        room.entry.insert(0, "After server restart")
        room.send_btn.invoke()
        self.pump(lambda: bool(room.messages))
        self.assertEqual(next(iter(room.messages.values()))["text"], "After server restart")

    def test_switching_private_and_group_tabs_keeps_destinations_separate(self):
        bob, b, _ = self.adapter("Bob")
        carol, c, _ = self.adapter("Carol")
        self.login("Alice")
        self.client.create_group("Alice-Carol")
        self.pump(lambda: "Alice-Carol" in self.app.groups)
        carol.join_group("Alice-Carol")
        c.wait("groups", lambda g: "Alice-Carol" in g and g["Alice-Carol"].joined)
        private_id = private_room_id("Alice", "Bob")
        private = self.app.main._room("private", private_id, select=True)
        private.entry.insert(0, "Private first")
        private.send_btn.invoke()
        first = b.wait("message")
        self.app.main.open_group("Alice-Carol")
        group = self.app.main.rooms[("group", "Alice-Carol")]
        group.entry.insert(0, "Group only")
        group.send_btn.invoke()
        grouped = c.wait("message")
        self.app.main._room("private", private_id, select=True)
        private.entry.insert(0, "Private again")
        private.send_btn.invoke()
        last = b.wait("message")
        self.pump(lambda: len(private.messages) == 2 and len(group.messages) == 1)
        self.assertEqual([first["text"], last["text"]], ["Private first", "Private again"])
        self.assertEqual(grouped["text"], "Group only")
        for events in (b, c):
            with self.assertRaises(queue.Empty):
                events.queues["message"].get(timeout=0.15)
        self.assertFalse(self.showerror.called)

    def test_reply_menu_cancel_then_send_and_quote(self):
        bob, b, _ = self.adapter("Bob")
        self.login("Alice")
        rid = private_room_id("Alice", "Bob")
        bob.send_message("private", rid, "Original from Bob")
        original = b.wait("message")
        self.pump(lambda: ("private", rid) in self.app.main.rooms)
        room = self.app.main.rooms[("private", rid)]
        self.pump(lambda: original["message_id"] in room.messages)
        # Invoke the real context menu command without opening a desktop popup.
        with patch.object(tk.Menu, "tk_popup"):
            room._menu(SimpleNamespace(x_root=0, y_root=0), original["message_id"])
        menu = next(w for w in room.winfo_children() if isinstance(w, tk.Menu))
        menu.invoke(0)
        self.assertEqual(room.reply_to, original["message_id"])
        next(w for w in room.reply_bar.winfo_children() if isinstance(w, tk.Button)).invoke()
        self.assertIsNone(room.reply_to)
        room.entry.insert(0, "Cancelled reply becomes ordinary text")
        room.send_btn.invoke()
        self.assertIsNone(b.wait("message")["reply_to"])
        menu.invoke(0)
        room.entry.insert(0, "Actual reply")
        room.send_btn.invoke()
        reply = b.wait("message")
        self.pump(lambda: reply["message_id"] in room.messages)
        self.assertEqual(reply["reply_to"], original["message_id"])
        labels = [w.cget("text") for w in descendants(room) if isinstance(w, tk.Label)]
        self.assertIn("Bob: Original from Bob", labels)
        self.assertFalse(self.showerror.called)

    def test_emoji_only_and_thai_text_round_trip_both_directions(self):
        bob, b, _ = self.adapter("Bob")
        self.login("Alice")
        rid = private_room_id("Alice", "Bob")
        room = self.app.main._room("private", rid, select=True)
        for text in ("😀❤️👍", "ภาษาไทย", "สวัสดี 🎉"):
            room.entry.insert(0, text)
            room.send_btn.invoke()
            sent = b.wait("message")
            self.assertEqual(sent["text"], text)
            bob.send_message("private", rid, text, sent["message_id"])
            reply = b.wait("message")
            self.pump(lambda: reply["message_id"] in room.messages)
            self.assertEqual(room.messages[reply["message_id"]]["text"], text)
            self.assertEqual(reply["reply_to"], sent["message_id"])
        self.assertEqual(len(room.messages), 6)

    def test_close_and_reopen_tab_preserves_long_text_and_receives_new_messages(self):
        bob, b, _ = self.adapter("Bob")
        self.login("Alice")
        rid = private_room_id("Alice", "Bob")
        room = self.app.main._room("private", rid, select=True)
        long_text = "A long message with Thai ภาษาไทย and emoji 😀 " * 40
        bob.send_message("private", rid, long_text)
        original = b.wait("message")
        self.pump(lambda: original["message_id"] in room.messages)
        bodies = [w.get("1.0", "end-1c") for w in descendants(room) if isinstance(w, tk.Text)]
        self.assertIn(long_text, bodies)
        room.set_reply(original["message_id"])
        room.open_emoji()
        picker = room.emoji_picker
        self.app.main.close_current()
        self.assertEqual(self.app.main.tabs.tab(room, "state"), "hidden")
        self.assertIsNone(room.reply_to)
        self.assertFalse(picker.winfo_exists())
        self.app.main._room("private", rid, select=True)
        self.assertEqual(len(room.messages), 1)
        self.app.main.close_current()
        bob.send_message("private", rid, "Arrived while tab was closed")
        last = b.wait("message")
        self.pump(lambda: last["message_id"] in room.messages)
        self.assertEqual(self.app.main.tabs.tab(room, "state"), "normal")
        self.assertEqual(len(room.messages), 2)
        self.assertFalse(self.showerror.called)

    def test_leaving_group_closes_emoji_picker_and_locks_input(self):
        self.login("Alice")
        self.client.create_group("Temporary")
        self.pump(lambda: "Temporary" in self.app.groups)
        self.app.main.open_group("Temporary")
        room = self.app.main.rooms[("group", "Temporary")]
        room.open_emoji()
        first = room.emoji_picker
        room.open_emoji()
        self.assertFalse(first.winfo_exists())
        picker = room.emoji_picker
        self.client.leave_group("Temporary")
        self.pump(lambda: not room.joined)
        self.assertFalse(picker.winfo_exists())
        self.assertEqual(room.entry.cget("state"), "disabled")

    def test_invalid_username_and_port_stay_on_login_without_connecting(self):
        for name in ("x" * 21, "server", "Bad\tName"):
            self.app.login.name.set(name)
            self.app.login.connect()
            self.assertIn("1–20", self.app.login.status.cget("text"))
            self.assertFalse(self.client.connected)
        self.app.login.name.set("Valid User 😀")
        for port in ("abc", "0", "65536"):
            self.app.login.port.set(port)
            self.app.login.connect()
            self.assertIn("Port", self.app.login.status.cget("text"))
            self.assertFalse(self.client.connected)

    def test_mock_demo_still_uses_updated_room_and_group_contract(self):
        self.client.close()
        self.app.close()
        self.app = App(MockClient())
        self.app.withdraw()
        self.app.report_callback_exception = lambda *error: self.tk_errors.append(error)
        # The registered cleanup must reference this replacement app.
        self.addCleanup(self.app.close)
        self.app.login.name.set("Demo-User 😀")
        self.app.login.connect()
        self.pump(lambda: self.app.main is not None)
        self.assertFalse(self.app.groups["study"].joined)
        self.app.client.join_group("study")
        self.pump(lambda: self.app.groups["study"].joined)
        self.app.main.open_group("study")
        self.assertTrue(self.app.main.rooms[("group", "study")].joined)
