"""Contract between the Tkinter UI (Person 2) and the client networking module (Person 4).

Person 4's real client should subclass ClientInterface. The UI never touches sockets.
Handlers may be called from ANY thread (e.g. the receive loop); the UI queues them safely.

Message dict (shared contract):
  {type, room_type: "private"|"group"|"bot", room_id, message_id, sender,
   text, reply_to, mentions, timestamp}
The server echoes a user's own messages back, so the UI only draws what on_message delivers.
mentions lists the canonical usernames the server found as @name in text (Person 3).
The chatbot room is ("bot", BOT_ROOM); the AI's messages come from sender BOT_NAME,
also when someone writes @Bot in a private or group chat.
on_message also delivers type="system_message" for group join announcements,
using the same room_id/message_id/text fields. These rows cannot be replied to.
"""
from dataclasses import dataclass
import json

BOT_NAME = "Bot"       # the server's AI chatbot; a reserved username
BOT_ROOM = "chatbot"   # room_id of each user's private chatbot room


class NameTakenError(Exception):
    pass


def private_room_id(a, b):
    # JSON preserves spaces, hyphens and every other valid username character.
    return json.dumps(sorted([a, b]), ensure_ascii=False)


def private_peer(room_id, me):
    names = json.loads(room_id)
    if (not isinstance(names, list) or len(names) != 2
            or not all(isinstance(n, str) for n in names)
            or names.count(me) != 1):
        raise ValueError("Invalid private conversation")
    return next(name for name in names if name != me)


@dataclass(frozen=True)
class GroupInfo:
    joined: bool
    member_count: int
    # None means names are unavailable, rather than an empty group.
    members: tuple[str, ...] | None = None


class ClientInterface:
    supports_bot = False
    supports_group_events = False

    def set_handlers(self, on_message, on_users, on_groups, on_error, on_disconnect):
        """on_message(msg) · on_users([names]) · on_groups({group: GroupInfo})
        on_error(text) · on_disconnect()"""
        raise NotImplementedError

    def connect(self, host, port, username):
        """Blocking; return the server-confirmed name. Raise NameTakenError or ConnectionError."""
        raise NotImplementedError

    def send_message(self, room_type, room_id, text, reply_to=None):
        raise NotImplementedError

    def create_group(self, name):  # R8
        raise NotImplementedError

    def join_group(self, name):  # R10
        raise NotImplementedError

    def leave_group(self, name):
        """Leave a joined group; you stop receiving its messages. Server then sends on_groups."""
        raise NotImplementedError

    def close(self):
        raise NotImplementedError
