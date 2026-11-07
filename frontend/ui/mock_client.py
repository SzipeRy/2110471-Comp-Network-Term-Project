"""Fake backend so the UI can be built and demoed with no server."""
import datetime
import re
import threading
import time
import uuid

from .net_interface import ClientInterface, GroupInfo, NameTakenError, private_peer


class MockClient(ClientInterface):
    supports_bot = True
    supports_group_events = True
    def __init__(self):
        self.me = None
        self.users = ["Bob", "Carol"]
        self.groups = {"study": ["Bob", "Carol"], "project": ["Carol"]}

    def set_handlers(self, on_message, on_users, on_groups, on_error, on_disconnect):
        self.on_message, self.on_users, self.on_groups = on_message, on_users, on_groups
        self.on_error, self.on_disconnect = on_error, on_disconnect

    def connect(self, host, port, username):
        time.sleep(0.3)
        if username in self.users:
            raise NameTakenError(username)
        self.me = username
        self.users.append(username)
        self._push_lists()
        return username

    def _push_lists(self):
        self.on_users(list(self.users))
        self.on_groups({g: GroupInfo(self.me in m, len(m), tuple(m) if self.me in m else None)
                        for g, m in self.groups.items()})

    def _msg(self, room_type, room_id, sender, text, reply_to=None):
        return {"type": "chat_message", "room_type": room_type, "room_id": room_id,
                "message_id": uuid.uuid4().hex[:8], "sender": sender, "text": text,
                "reply_to": reply_to, "mentions": re.findall(r"@(\w+)", text),
                "timestamp": datetime.datetime.now().isoformat(timespec="seconds")}

    def send_message(self, room_type, room_id, text, reply_to=None):
        m = self._msg(room_type, room_id, self.me, text, reply_to)
        self.on_message(m)  # server echo
        threading.Thread(target=self._fake_reply, args=(room_type, room_id, text), daemon=True).start()

    def _fake_reply(self, room_type, room_id, text):
        time.sleep(0.8)
        if room_type == "bot":
            self.on_message(self._msg("bot", "chatbot", "Bot", f"(mock AI) You said: {text}"))
        elif room_type == "private":
            other = private_peer(room_id, self.me)
            self.on_message(self._msg("private", room_id, other, "Got it 👍"))
        else:
            self.on_message(self._msg("group", room_id, "Carol", f"@{self.me} noted!"))

    def create_group(self, name):
        if name in self.groups:
            self.on_error(f'Group "{name}" already exists')
            return
        self.groups[name] = [self.me]
        self._push_lists()

    def join_group(self, name):
        if self.me not in self.groups.get(name, []):
            self.groups[name].append(self.me)
            self._push_lists()
            notice = self._msg("group", name, "server", f"{self.me} joined the group")
            notice.update(type="system_message", event="member_joined", username=self.me)
            self.on_message(notice)
        else:
            self._push_lists()

    def leave_group(self, name):
        members = self.groups.get(name)
        if members and self.me in members:
            members.remove(self.me)
            if not members:  # example rule: an empty group is deleted (Person 1 decides the real rule)
                del self.groups[name]
        self._push_lists()

    def close(self):
        pass
