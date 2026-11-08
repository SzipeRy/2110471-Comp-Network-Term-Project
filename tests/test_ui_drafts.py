"""A sent message stays in the chat box until the server answers, so a rejection never loses it (Person 2)."""
import unittest

from test_person3_ui import GuiTestCase


class PendingSendTests(GuiTestCase):
    def open_bot_room(self):
        self.login("Alice")
        self.app.main.open_bot()
        return self.app.main.rooms[("bot", "chatbot")]

    def bot_answers(self, room):
        return [m for m in room.messages.values() if m["sender"] == "Bot"]

    def test_delivered_message_is_cleared_and_new_typing_is_kept(self):
        # Review finding 1: typing the same text again must not be deleted by the first echo.
        room = self.open_bot_room()
        room.entry.insert(0, "hello")
        room.send_btn.invoke()
        self.assertIs(self.app.pending_send, room)
        self.assertEqual(room.entry.cget("state"), "readonly")  # waiting for the server
        room.entry.insert("end", " hello")                       # ignored while read-only
        self.assertEqual(room.entry.get(), "hello")
        self.pump(lambda: self.app.pending_send is None)
        self.assertEqual((room.entry.get(), room.entry.cget("state")), ("", "normal"))
        room.entry.insert(0, "hello")  # the same text again, after the echo
        self.pump(lambda: self.bot_answers(room))
        self.app.update()
        self.assertEqual(room.entry.get(), "hello")
        self.assertFalse(self.showerror.called)

    def test_rejected_first_send_is_kept_and_a_second_send_waits(self):
        # Review finding 2: a second Send must not replace the first message before it is answered.
        room = self.open_bot_room()
        too_long = "x" * 4001  # the server accepts chatbot questions of 1-4000 characters
        room.entry.insert(0, too_long)
        room.send_btn.invoke()
        room.send_btn.invoke()  # pressed again before the server answers: nothing more is sent
        self.pump(lambda: self.showerror.called)
        self.assertIsNone(self.app.pending_send)
        self.assertEqual((room.entry.get(), room.entry.cget("state")), (too_long, "normal"))
        self.assertEqual(room.messages, {})
        self.assertEqual(self.showerror.call_count, 1)
        # The kept draft can be edited and sent.
        room.entry.delete(0, "end")
        room.entry.insert(0, "short question")
        room.send_btn.invoke()
        self.pump(lambda: self.bot_answers(room))
        self.assertEqual(room.entry.get(), "")
        self.assertEqual([m["text"] for m in room.messages.values() if m["sender"] == "Alice"],
                         ["short question"])

    def test_client_side_size_limit_keeps_the_draft(self):
        # Review finding 3: the network client's own 1 MiB rejection has no server error code.
        room = self.open_bot_room()
        huge = "y" * (1024 * 1024 + 1)
        room.entry.insert(0, huge)
        room.send_btn.invoke()
        self.pump(lambda: self.showerror.called)
        self.assertIn("1 MiB", self.showerror.call_args.args[1])
        self.assertEqual(room.entry.cget("state"), "normal")
        self.assertEqual(len(room.entry.get()), len(huge))

    def test_late_echo_after_an_unrelated_error_clears_only_unedited_text(self):
        room = self.open_bot_room()
        room.entry.insert(0, "first")
        room.send_finished(delivered=False)  # as if an unrelated error arrived before the echo
        room._confirm_late_echo({"text": "first"})
        self.assertEqual(room.entry.get(), "")  # it was delivered: not left in the box
        room.entry.insert(0, "second")
        room.send_finished(delivered=False)
        room.entry.insert("end", " (edited)")
        room._confirm_late_echo({"text": "second"})
        self.assertEqual(room.entry.get(), "second (edited)")  # the user's edits are kept


if __name__ == "__main__":
    unittest.main()
