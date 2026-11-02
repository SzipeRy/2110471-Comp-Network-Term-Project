"""Contract between the Tkinter UI (Person 2) and the client networking module (Person 4).

Person 4's real client should subclass ClientInterface. The UI never touches sockets.
Handlers may be called from ANY thread (e.g. the receive loop); the UI queues them safely.

Message dict (shared contract):
  {type, room_type: "private"|"group"|"bot", room_id, message_id, sender,
   text, reply_to, mentions, timestamp}
The server echoes a user's own messages back, so the UI only draws what on_message delivers.
"""


class NameTakenError(Exception):
    pass


def private_room_id(a, b):
    return "-".join(sorted([a, b]))


class ClientInterface:
    def set_handlers(self, on_message, on_users, on_groups, on_error, on_disconnect):
        """on_message(msg) · on_users([names]) · on_groups({group: [members]})
        on_error(text) · on_disconnect()"""
        raise NotImplementedError

    def connect(self, host, port, username):
        """Blocking. Raise NameTakenError (R3) or ConnectionError."""
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
