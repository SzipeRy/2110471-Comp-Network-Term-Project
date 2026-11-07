"""Tkinter-free TCP adapter. Socket I/O runs in workers, callbacks may run there too."""
from dataclasses import dataclass, field
import queue
import socket
import threading
import time

if __package__:
    from . import client as wire
    from .ui.net_interface import (BOT_ROOM, ClientInterface, GroupInfo, NameTakenError,
                                   private_peer, private_room_id)
else:  # python -m ui.app --real, from frontend/
    import client as wire
    from ui.net_interface import (BOT_ROOM, ClientInterface, GroupInfo, NameTakenError,
                                  private_peer, private_room_id)


@dataclass
class _Session:
    conn: socket.socket
    username: str
    outgoing: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=256))
    stop: threading.Event = field(default_factory=threading.Event)
    groups: dict = field(default_factory=dict)
    users: list = field(default_factory=list)
    pending: set = field(default_factory=set)
    leaving: set = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock)
    threads: list = field(default_factory=list)


class NetworkClient(ClientInterface):
    supports_group_events = True
    supports_bot = True  # the server answers room_type "bot" and @Bot mentions
    def __init__(self, refresh_interval=2.0, connect_timeout=5.0):
        self.refresh_interval = max(0.05, refresh_interval)
        self.connect_timeout = connect_timeout
        self._lock = threading.RLock()
        self._session = None
        self._generation = 0
        self.set_handlers(*(lambda *args: None for _ in range(5)))

    def set_handlers(self, on_message, on_users, on_groups, on_error, on_disconnect):
        self.on_message, self.on_users, self.on_groups = on_message, on_users, on_groups
        self.on_error, self.on_disconnect = on_error, on_disconnect

    @property
    def connected(self):
        with self._lock:
            return self._session is not None and not self._session.stop.is_set()

    def connect(self, host, port, username):
        self.close()
        with self._lock:
            generation = self._generation
        conn = socket.create_connection((host, port), timeout=self.connect_timeout)
        try:
            wire.send(conn, {"type": "register", "username": username, "group_events": True})
            response = wire.receive_message(conn)
            if response.get("type") == "error":
                error = NameTakenError if response.get("code") == "username_taken" else ConnectionError
                raise error(response.get("text", "Registration rejected"))
            if response.get("type") != "registered" or not isinstance(response.get("username"), str):
                raise ConnectionError("Unexpected registration response; update and restart the server")
            conn.settimeout(None)  # exact-length reads must survive fragmented frames
            session = _Session(conn, response["username"])
            with self._lock:
                if generation != self._generation:
                    raise ConnectionError("Connection attempt cancelled")
                self._session = session
                session.threads = [
                    threading.Thread(target=self._receive, args=(session,), daemon=True),
                    threading.Thread(target=self._write, args=(session,), daemon=True),
                ]
                for worker in session.threads:
                    worker.start()
            return session.username
        except BaseException:
            conn.close()
            raise

    def _emit(self, session, callback, *args):
        with self._lock:
            if self._session is session and not session.stop.is_set():
                callback(*args)

    def _finish(self, session, unexpected=False):
        with self._lock:
            if session.stop.is_set():
                return
            session.stop.set()
            try:
                session.conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            session.conn.close()
            if self._session is session:
                self._session = None
                if unexpected:
                    self.on_disconnect()

    def close(self):
        with self._lock:
            self._generation += 1
            session = self._session
            if session is not None:
                self._finish(session)
        if session is not None:
            for worker in session.threads:
                if worker is not threading.current_thread():
                    worker.join(timeout=0.25)

    def _enqueue(self, request):
        with self._lock:
            session = self._session
            if session is None or session.stop.is_set():
                self.on_error("Not connected to the server")
                return False
            try:
                with session.lock:
                    session.outgoing.put_nowait(request)
                    if request["type"] == "leave_group":
                        session.leaving.add(request["room"].casefold())
                return True
            except queue.Full:
                self.on_error("Too many pending requests; please try again shortly")
                return False

    def send_message(self, room_type, room_id, text, reply_to=None):
        if room_type not in {"private", "group", "bot"}:
            self.on_error(f"Unsupported chat room type: {room_type}")
            return False
        with self._lock:
            session = self._session
            if session is None:
                self.on_error("Not connected to the server")
                return False
            try:
                if room_type == "private":
                    destination = private_peer(room_id, session.username)
                else:
                    destination = BOT_ROOM if room_type == "bot" else room_id
            except (ValueError, TypeError) as exc:
                self.on_error(str(exc))
                return False
        return self._enqueue(wire.create_message(text, destination, reply_to, room_type))

    def create_group(self, name):
        return self._enqueue({"type": "create_group", "room": name})

    def join_group(self, name):
        return self._enqueue({"type": "join_group", "room": name})

    def leave_group(self, name):
        return self._enqueue({"type": "leave_group", "room": name})

    def _request_snapshot(self, session, kind, room=None):
        key = (kind, room)
        with session.lock:
            if key in session.pending:
                return
            session.pending.add(key)
        request = {"type": kind}
        if room is not None:
            request["room"] = room
        # Only the writer calls this: frames never interleave on the socket.
        wire.send(session.conn, request)

    def _write(self, session):
        next_refresh = 0
        try:
            while not session.stop.is_set():
                if time.monotonic() >= next_refresh:
                    self._request_snapshot(session, "member_list")
                    self._request_snapshot(session, "group_list")
                    next_refresh = time.monotonic() + self.refresh_interval
                try:
                    request = session.outgoing.get(timeout=min(0.1, self.refresh_interval))
                except queue.Empty:
                    continue
                try:
                    if request["type"] == "_members":
                        with session.lock:
                            info = session.groups.get(request["room"])
                            leaving = request["room"].casefold() in session.leaving
                        if info is not None and info.joined and not leaving:
                            self._request_snapshot(session, "group_members", request["room"])
                    else:
                        wire.send(session.conn, request)
                except (ValueError, TypeError) as exc:
                    self._emit(session, self.on_error, str(exc))
        except OSError:
            self._finish(session, unexpected=True)

    def _publish_groups(self, session):
        self._emit(session, self.on_groups, dict(session.groups))

    def _handle(self, session, message):
        kind = message["type"]
        with session.lock:
            session.pending.discard((kind, message.get("room") if kind == "group_members" else None))
        if kind == "group_event":
            if message["event"] != "member_joined" or message["room_type"] != "group":
                raise ValueError("Unsupported group event")
            self._emit(session, self.on_message, {
                "type": "system_message", "room_type": "group", "room_id": message["room"],
                "message_id": message["msg_id"], "sender": "server", "text": message["text"],
                "reply_to": None, "timestamp": message["timestamp"], "mentions": [],
                "event": message["event"], "username": message["username"],
            })
        elif kind == "chat_message":
            room_type = message["room_type"]
            room = message["room"]
            if room_type == "private":
                room = private_room_id(*message["participants"])
                private_peer(room, session.username)
            elif room_type == "bot":
                room = BOT_ROOM
            elif room_type != "group":
                raise ValueError("Unsupported chat room type")
            # Server-confirmed canonical names; older servers omit the field.
            mentions = message.get("mentions", [])
            if not isinstance(mentions, list) or not all(isinstance(name, str) for name in mentions):
                raise ValueError("mentions must be a list of usernames")
            self._emit(session, self.on_message, {
                "type": kind, "room_type": room_type, "room_id": room,
                "message_id": message["msg_id"], "sender": message["sender_id"],
                "text": message["text"], "reply_to": message.get("reply_to"),
                "timestamp": message["timestamp"], "mentions": list(mentions),
            })
        elif kind == "member_list":
            users = message["members"]
            if users != session.users:
                session.users = users
                self._emit(session, self.on_users, list(users))
        elif kind == "group_list":
            groups = {}
            for item in message["groups"]:
                old = session.groups.get(item["name"])
                members = old.members if old and old.joined and item["joined"] else None
                groups[item["name"]] = GroupInfo(item["joined"], item["member_count"], members)
                if item["joined"]:
                    self._enqueue({"type": "_members", "room": item["name"]})
            if groups != session.groups:
                session.groups = groups
                self._publish_groups(session)
        elif kind == "group_members":
            name = message["room"]
            # Ignore an old snapshot arriving after a leave response.
            if name in session.groups and session.groups[name].joined:
                members = tuple(message["members"])
                info = GroupInfo(True, len(members), members)
                if session.groups[name] != info:
                    session.groups[name] = info
                    self._publish_groups(session)
        elif kind == "chat_selected":
            if message["room_type"] == "group":
                members = tuple(message["members"])
                session.groups[message["room"]] = GroupInfo(True, len(members), members)
                with session.lock:
                    session.leaving.discard(message["room"].casefold())
                self._publish_groups(session)
        elif kind == "group_left":
            name = message["room"]
            old = session.groups.get(name)
            if old:
                session.groups[name] = GroupInfo(False, max(0, old.member_count - 1))
                self._publish_groups(session)
            with session.lock:
                session.leaving.discard(name.casefold())
        elif kind == "error":
            # Errors have no request ID. Allow failed snapshot requests to refresh again.
            with session.lock:
                session.pending.clear()
                session.leaving.clear()
            self._emit(session, self.on_error, f"{message.get('code', 'error')}: {message['text']}")
        else:
            raise ValueError(f"Unsupported server message: {kind}")

    def _receive(self, session):
        try:
            while not session.stop.is_set():
                self._handle(session, wire.receive_message(session.conn))
        except (EOFError, OSError, ValueError, KeyError, TypeError) as exc:
            if not isinstance(exc, (EOFError, OSError)):
                self._emit(session, self.on_error, f"Invalid server response: {exc}")
            self._finish(session, unexpected=True)
