"""A message the server rejects goes back in the chat box instead of being lost (Person 2)."""
import unittest

from test_person3_ui import GuiTestCase


class RejectedDraftTests(GuiTestCase):
    def open_bot_room(self):
        self.login("Alice")
        self.app.main.open_bot()
        return self.app.main.rooms[("bot", "chatbot")]

    def test_rejected_chatbot_question_returns_to_the_chat_box(self):
        room = self.open_bot_room()
        too_long = "x" * 4001  # the server accepts chatbot questions of 1-4000 characters
        room.entry.insert(0, too_long)
        room.send_btn.invoke()
        self.assertEqual(room.entry.get(), "")  # cleared at once, as before
        self.pump(lambda: self.showerror.called)
        self.assertEqual(room.entry.get(), too_long)
        self.assertEqual(room.messages, {})

    def test_delivered_message_stays_cleared_and_is_not_restored_later(self):
        room = self.open_bot_room()
        room.entry.insert(0, "What is TCP?")
        room.send_btn.invoke()
        self.pump(lambda: any(m["sender"] == "Bot" for m in room.messages.values()))
        self.assertIsNone(room.unsent)
        room.restore_unsent()  # a later, unrelated error must not bring it back
        self.assertEqual(room.entry.get(), "")

    def test_restore_never_overwrites_new_typing(self):
        room = self.open_bot_room()
        room.unsent = ("old question", None)
        room.entry.insert(0, "new draft")
        room.restore_unsent()
        self.assertEqual(room.entry.get(), "new draft")

    def test_restored_text_is_cleared_if_its_echo_arrives_afterwards(self):
        room = self.open_bot_room()
        room.unsent = ("hello", None)
        room.restore_unsent()  # an unrelated error arrived before the echo
        self.assertEqual(room.entry.get(), "hello")
        room._forget_unsent({"text": "hello"})
        self.assertEqual(room.entry.get(), "")
        self.assertIsNone(room.unsent)


if __name__ == "__main__":
    unittest.main()
