import argparse
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import threading
import unicodedata
import uuid

if __package__:
    from . import chatbot, mentions
else:  # python backend/server.py
    import chatbot
    import mentions

HEADER = 64
PORT = 5050
SERVER = "0.0.0.0"
FORMAT = "utf-8"
DEFAULT_ROOM = "lobby"
MAX_MESSAGE_BYTES = 1024 * 1024
MAX_USERNAME_LENGTH = 20
MAX_GROUP_LENGTH = 40
MAX_REPLY_REFERENCES = 10000

# Membership and private sessions belong to socket connections, not reusable names.
clients = {}
usernames = {}
groups = {DEFAULT_ROOM: {"name": DEFAULT_ROOM, "id": uuid.uuid4().hex, "members": set()}}
active_chats = {}
private_rooms = {}
reply_references = OrderedDict()
group_event_clients = set()
clients_lock = threading.Lock()

# Chatbot state, also per connection. Each user has one bot conversation (text only)
# and at most one unanswered bot request; AI calls run outside the socket handlers.
RESERVED_NAMES = {"server", chatbot.BOT_NAME.casefold()}
bot_sessions = {}
bot_history = {}
bot_pending = set()
bot_slots = threading.BoundedSemaphore(4)  # concurrent AI requests for all users
assistant = chatbot.Chatbot()
BOT_BUSY = "The chatbot is still answering your previous message"


class RequestError(ValueError):
    def __init__(self, code, text):
        super().__init__(text)
        self.code = code


def recv_exact(conn, length):
    data = bytearray()
    while len(data) < length:
        chunk = conn.recv(length - len(data))
        if not chunk:
            raise EOFError("Connection closed")
        data.extend(chunk)
    return bytes(data)


def receive_message(conn):
    length = int(recv_exact(conn, HEADER).decode(FORMAT))
    if not 0 < length <= MAX_MESSAGE_BYTES:
        raise ValueError("Invalid message length")
    message = json.loads(recv_exact(conn, length).decode(FORMAT))
    if not isinstance(message, dict):
        raise ValueError("Message must be a JSON object")
    return message


def encode_message(message):
    payload = json.dumps(message, ensure_ascii=False, allow_nan=False).encode(FORMAT)
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError("JSON message exceeds the 1 MiB limit")
    return str(len(payload)).encode(FORMAT).ljust(HEADER, b" ") + payload


def server_message(kind, sender_id, text, room=DEFAULT_ROOM, reply_to=None):
    return {
        "type": kind, "room": room, "msg_id": uuid.uuid4().hex,
        "sender_id": sender_id, "text": text, "reply_to": reply_to,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    }


def send_to(conn, message):
    frame = encode_message(message)
    with clients_lock:
        send_lock = clients.get(conn)
    if send_lock is not None:
        with send_lock:
            conn.sendall(frame)


def send_error(conn, code, text):
    message = server_message("error", "server", text)
    message["code"] = code
    send_to(conn, message)


def normalized_name(value, limit, code, label):
    if not isinstance(value, str):
        raise RequestError(code, f"{label} must be text")
    name = unicodedata.normalize("NFC", value.strip())
    if not 1 <= len(name) <= limit or not name.isprintable():
        raise RequestError(code, f"{label} must contain 1-{limit} printable characters")
    return name


def register_client(conn, requested_name, group_events=False):
    name = normalized_name(requested_name, MAX_USERNAME_LENGTH, "invalid_username", "Username")
    if name.casefold() in RESERVED_NAMES:
        raise RequestError("invalid_username", f"The username '{name}' is reserved")
    with clients_lock:
        send_lock = clients.get(conn)
    if send_lock is None:
        return
    # Lock order is always the recipient's send lock followed by the registry lock.
    with send_lock:
        with clients_lock:
            if conn not in clients:
                return
            if conn in usernames:
                raise RequestError("already_registered", "Reconnect to choose a different username")
            if any(existing.casefold() == name.casefold() for existing in usernames.values()):
                raise RequestError("username_taken", "That username is already in use; choose another")
            usernames[conn] = name
            groups[DEFAULT_ROOM]["members"].add(conn)
            if group_events:
                group_event_clients.add(conn)
        response = server_message("registered", "server", f"Registered as {name}")
        response["username"] = name
        conn.sendall(encode_message(response))


def remove_client(conn):
    with clients_lock:
        clients.pop(conn, None)
        group_event_clients.discard(conn)
        usernames.pop(conn, None)
        active_chats.pop(conn, None)
        bot_sessions.pop(conn, None)
        bot_history.pop(conn, None)
        bot_pending.discard(conn)
        for key, group in list(groups.items()):
            group["members"].discard(conn)
            if key != DEFAULT_ROOM and not group["members"]:
                del groups[key]
        for pair in list(private_rooms):
            if conn in pair:
                del private_rooms[pair]
        for other, chat in list(active_chats.items()):
            if chat[0] == "private" and chat[1] is conn:
                del active_chats[other]
    try:
        conn.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    conn.close()


# The following helpers run while clients_lock is held.
def get_group(value):
    name = normalized_name(value, MAX_GROUP_LENGTH, "invalid_group", "Group name")
    group = groups.get(name.casefold())
    if group is None:
        raise RequestError("group_not_found", "That group does not exist")
    return name.casefold(), group


def require_member(conn, group):
    if conn not in group["members"]:
        raise RequestError("not_group_member", "Join this group before accessing it")


def find_peer(conn, value):
    name = normalized_name(value, MAX_USERNAME_LENGTH, "invalid_recipient", "Recipient")
    peer = next((sock for sock, user in usernames.items() if user.casefold() == name.casefold()), None)
    if peer is None:
        raise RequestError("user_not_found", "That user is not connected")
    if peer is conn:
        raise RequestError("invalid_recipient", "Choose another user for a private chat")
    return peer


def private_id(conn, peer):
    return private_rooms.setdefault(frozenset((conn, peer)), uuid.uuid4().hex)


def selected_response(conn, chat, action="select_chat"):
    kind, destination = chat
    if kind == "group":
        group = groups[destination]
        room = group["name"]
        members = sorted((usernames[s] for s in group["members"]), key=str.casefold)
        text = f"Group: {room}"
    else:
        room = private_id(conn, destination)
        members = sorted((usernames[conn], usernames[destination]), key=str.casefold)
        text = f"Private chat with {usernames[destination]}"
    response = server_message("chat_selected", "server", text, room)
    response.update(room_type=kind, members=members, action=action)
    return response


def control_response(conn, message):
    kind = message.get("type")
    if kind == "member_list":
        response = server_message(kind, "server", "Connected members")
        response["members"] = sorted(usernames.values(), key=str.casefold)
        return response
    if kind == "group_list":
        response = server_message(kind, "server", "Available groups")
        response["groups"] = [
            {"name": g["name"], "joined": conn in g["members"], "member_count": len(g["members"])}
            for g in sorted(groups.values(), key=lambda item: item["name"].casefold())
        ]
        return response
    if kind == "create_group":
        name = normalized_name(message.get("room"), MAX_GROUP_LENGTH, "invalid_group", "Group name")
        key = name.casefold()
        if key in groups:
            raise RequestError("group_exists", "A group with that name already exists")
        groups[key] = {"name": name, "id": uuid.uuid4().hex, "members": {conn}}
        active_chats[conn] = ("group", key)
        return selected_response(conn, active_chats[conn], kind)
    if kind in ("join_group", "leave_group", "group_members"):
        key, group = get_group(message.get("room"))
        if kind == "join_group":
            group["members"].add(conn)
            active_chats[conn] = ("group", key)
            return selected_response(conn, active_chats[conn], kind)
        require_member(conn, group)
        if kind == "group_members":
            response = server_message(kind, "server", "Group members", group["name"])
            response["members"] = sorted((usernames[s] for s in group["members"]), key=str.casefold)
            return response
        if key == DEFAULT_ROOM:
            raise RequestError("invalid_group", "The public lobby cannot be left; select another chat instead")
        group["members"].remove(conn)
        if not group["members"]:
            del groups[key]
        if active_chats.get(conn) == ("group", key):
            del active_chats[conn]
        return server_message("group_left", "server", f"Left group {group['name']}", group["name"])
    if kind == "select_chat":
        room_type = message.get("room_type")
        if room_type == "group":
            key, group = get_group(message.get("room"))
            require_member(conn, group)
            chat = ("group", key)
        elif room_type == "private":
            chat = ("private", find_peer(conn, message.get("room")))
        else:
            raise RequestError("unsupported_room_type", "Choose a private or group chat")
        active_chats[conn] = chat
        return selected_response(conn, chat)
    raise RequestError("unsupported_type", "Unsupported request type")


def handle_control(conn, message):
    notice = None
    with clients_lock:
        send_lock = clients.get(conn)
    if send_lock is None:
        return
    # Membership changes and their confirmations serialize with deliveries to this client.
    with send_lock:
        with clients_lock:
            if conn not in usernames:
                return
            if message.get("type") in ("select_chat", "create_group", "join_group"):
                # A failed destination change must never send later text to an old chat.
                active_chats.pop(conn, None)
            new_member = False
            if message.get("type") == "join_group":
                _, group = get_group(message.get("room"))
                new_member = conn not in group["members"]
            response = control_response(conn, message)
            if new_member:
                _, group = get_group(response["room"])
                event = server_message("group_event", "server",
                                       f"{usernames[conn]} joined the group", group["name"])
                event.update(room_type="group", event="member_joined", username=usernames[conn])
                recipients = [(s, clients[s]) for s in group["members"]
                              if s in clients and s in group_event_clients]
                notice = (event, ("group", group["id"]), recipients)
        conn.sendall(encode_message(response))
    # Release the requester's lock before delivering to any other recipient.
    if notice is not None:
        deliver_group_event(*notice)


def deliver_group_event(event, context, recipients):
    frame = encode_message(event)
    for recipient, send_lock in recipients:
        try:
            with send_lock:
                with clients_lock:
                    allowed = recipient in group_event_clients and authorized(recipient, context)
                if allowed:
                    recipient.sendall(frame)
        except OSError:
            remove_client(recipient)


def resolve_chat(conn, message):
    room = message.get("room")
    room_type = message.get("room_type")
    if room is None and room_type is None:
        chat = active_chats.get(conn)
        if chat is None:
            raise RequestError("chat_not_selected", "Choose /private, /create, /join, /group, or /lobby before sending")
        return chat
    # Explicit group destinations remain compatible with the previous lobby protocol.
    if room_type in (None, "group"):
        key, group = get_group(room)
        require_member(conn, group)
        return "group", key
    if room_type == "private":
        return "private", find_peer(conn, room)
    raise RequestError("unsupported_room_type", "Choose a private or group chat")


def authorized(conn, context):
    if conn not in usernames:
        return False
    if context[0] == "group":
        return any(g["id"] == context[1] and conn in g["members"] for g in groups.values())
    if context[0] == "bot":
        return bot_sessions.get(conn) == context[1]
    return any(room_id == context[1] and conn in pair for pair, room_id in private_rooms.items())


def remember_reply(msg_id, context):
    reply_references[msg_id] = context
    while len(reply_references) > MAX_REPLY_REFERENCES:
        reply_references.popitem(last=False)


def mention_names(text):
    # Runs while clients_lock is held. Mentions are metadata; they never add recipients.
    return mentions.find_mentions(text, [*usernames.values(), chatbot.BOT_NAME])


def deliver(frame, context, recipients):
    """Send one frame to each recipient that is still authorized for the conversation."""
    for recipient, send_lock in recipients:
        try:
            with send_lock:
                with clients_lock:
                    allowed = authorized(recipient, context)
                if allowed:
                    recipient.sendall(frame)
        except OSError:
            remove_client(recipient)


def route_message(conn, message):
    text, reply_to = message.get("text"), message.get("reply_to")
    if not isinstance(text, str) or not (
        reply_to is None or isinstance(reply_to, str) and 0 < len(reply_to) <= 128
    ):
        raise RequestError("invalid_message", "text must be a string; reply_to must be null or a message ID (1-128 characters)")
    if message.get("room_type") == "bot":
        route_bot_message(conn, text, reply_to)
        return
    with clients_lock:
        if conn not in usernames:
            raise RequestError("registration_required", "Register before sending messages")
        kind, destination = resolve_chat(conn, message)
        if kind == "group":
            group = groups.get(destination)
            if group is None:
                raise RequestError("group_not_found", "That group no longer exists")
            require_member(conn, group)
            context = (kind, group["id"])
            room, recipients = group["name"], set(group["members"])
        else:
            if destination not in usernames:
                raise RequestError("user_not_found", "That user is no longer connected")
            context = (kind, private_id(conn, destination))
            room, recipients = context[1], {conn, destination}
        if reply_to is not None and reply_references.get(reply_to) != context:
            raise RequestError("invalid_reply", "Reply must reference a recent message in this conversation")
        outgoing = server_message("chat_message", usernames[conn], text, room, reply_to)
        outgoing["room_type"] = kind
        if kind == "private":
            outgoing["participants"] = sorted((usernames[s] for s in recipients), key=str.casefold)
        outgoing["mentions"] = mention_names(text)
        try:
            frame = encode_message(outgoing)
        except ValueError as exc:
            raise RequestError("message_too_large", str(exc)) from exc
        remember_reply(outgoing["msg_id"], context)
        recipient_locks = [(s, clients[s]) for s in recipients if s in clients]
        # "@Bot" asks the chatbot; it answers everyone in this conversation.
        wants_bot = chatbot.BOT_NAME in outgoing["mentions"]
        bot_free = wants_bot and conn not in bot_pending
        if bot_free:
            bot_pending.add(conn)
            request = BotRequest(conn, context, usernames[conn], bot_place(kind, room, recipients),
                                 [{"role": "user", "content": text}], outgoing["msg_id"], remember=False)
    deliver(frame, context, recipient_locks)
    # Do not put private/group message contents in the server's shared console log.
    if bot_free:
        start_bot(request)
    elif wants_bot:
        send_error(conn, "bot_busy", BOT_BUSY)


@dataclass(frozen=True)
class BotRequest:
    requester: socket.socket
    context: tuple
    asker: str
    place: str
    conversation: list
    reply_to: str | None
    remember: bool  # keep the exchange as context (only in the private chatbot room)


def bot_place(kind, room, recipients):
    # Runs while clients_lock is held. Tells the AI who can read its answer.
    if kind == "group":
        return f"the group chat #{room}, where every member can read your answer"
    names = sorted((usernames[s] for s in recipients), key=str.casefold)
    return f"a private chat between {' and '.join(names)}, where both of them can read your answer"


def route_bot_message(conn, text, reply_to):
    """A message in the requester's private chatbot room: echo it, then ask the AI."""
    if not text.strip() or len(text) > chatbot.MAX_QUESTION_CHARS:
        raise RequestError("invalid_message", f"Ask the chatbot in 1-{chatbot.MAX_QUESTION_CHARS} characters")
    with clients_lock:
        if conn not in usernames:
            raise RequestError("registration_required", "Register before sending messages")
        if conn in bot_pending:
            raise RequestError("bot_busy", BOT_BUSY)
        context = ("bot", bot_sessions.setdefault(conn, uuid.uuid4().hex))
        if reply_to is not None and reply_references.get(reply_to) != context:
            raise RequestError("invalid_reply", "Reply must reference a recent message in this conversation")
        outgoing = server_message("chat_message", usernames[conn], text, chatbot.BOT_ROOM, reply_to)
        outgoing["room_type"] = "bot"
        outgoing["mentions"] = mention_names(text)
        frame = encode_message(outgoing)  # the question limit keeps this far below 1 MiB
        remember_reply(outgoing["msg_id"], context)
        bot_pending.add(conn)
        conversation = [*bot_history.get(conn, ()), {"role": "user", "content": text}]
        request = BotRequest(conn, context, usernames[conn], "their private chatbot room",
                             conversation, None, remember=True)
        recipients = [(conn, clients[conn])]
    deliver(frame, context, recipients)
    start_bot(request)


def start_bot(request):
    # One daemon thread per question, like one per client: the AI call never blocks I/O.
    threading.Thread(target=answer_bot, args=(request,), daemon=True).start()


def answer_bot(request):
    try:
        with bot_slots:
            text, ok = assistant.reply(request.conversation, request.asker, request.place)
    except Exception as exc:  # reply() reports AI errors itself; never leave a user waiting
        print(f"[BOT ERROR] {type(exc).__name__}", flush=True)
        text, ok = chatbot.FAILED, False
    text = text[:chatbot.MAX_ANSWER_CHARS]
    with clients_lock:
        # Ready for the next question before the answer is sent, so a fast reply cannot be refused.
        bot_pending.discard(request.requester)
        if request.remember and ok and bot_sessions.get(request.requester) == request.context[1]:
            history = [*request.conversation, {"role": "assistant", "content": text}]
            bot_history[request.requester] = history[-chatbot.MAX_HISTORY_MESSAGES:]
        prepared = bot_answer(request.context, text, request.reply_to)
    if prepared is not None:
        deliver(*prepared)


def bot_answer(context, text, reply_to):
    """Runs while clients_lock is held: the bot's chat message and its current recipients."""
    kind, ident = context
    if kind == "group":
        group = next((g for g in groups.values() if g["id"] == ident), None)
        members, room = (set(group["members"]), group["name"]) if group else (set(), None)
    elif kind == "private":
        members = next((set(pair) for pair, room_id in private_rooms.items() if room_id == ident), set())
        room = ident
    else:
        members = {conn for conn, session in bot_sessions.items() if session == ident}
        room = chatbot.BOT_ROOM
    if not members:
        return None  # the asker disconnected, or the conversation no longer exists
    answer = server_message("chat_message", chatbot.BOT_NAME, text, room, reply_to)
    answer["room_type"] = kind
    if kind == "private":
        answer["participants"] = sorted((usernames[s] for s in members), key=str.casefold)
    answer["mentions"] = mentions.find_mentions(text, list(usernames.values()))
    remember_reply(answer["msg_id"], context)
    return encode_message(answer), context, [(s, clients[s]) for s in members if s in clients]


def handle_client(conn, addr):
    print(f"[NEW CONNECTION] {addr} connected.", flush=True)
    try:
        while True:
            message = receive_message(conn)
            try:
                kind = message.get("type")
                if kind == "disconnect":
                    break
                if kind == "register":
                    register_client(conn, message.get("username"), message.get("group_events") is True)
                    continue
                with clients_lock:
                    registered = conn in usernames
                if not registered:
                    raise RequestError("registration_required", "Choose a username before joining the chat")
                if kind == "chat_message":
                    route_message(conn, message)
                else:
                    handle_control(conn, message)
            except RequestError as exc:
                send_error(conn, exc.code, str(exc))
    except (EOFError, OSError, ValueError) as exc:
        print(f"[CONNECTION CLOSED] {addr}: {exc}", flush=True)
    finally:
        remove_client(conn)
        print(f"[DISCONNECTED] {addr}", flush=True)


def start(host=SERVER, port=PORT):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen()
        print(f"[LISTENING] {host}:{server.getsockname()[1]}", flush=True)
        try:
            while True:
                conn, addr = server.accept()
                with clients_lock:
                    clients[conn] = threading.Lock()
                    count = len(clients)
                threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
                print(f"[ACTIVE CONNECTIONS] {count}", flush=True)
        finally:
            with clients_lock:
                connections = list(clients)
            for conn in connections:
                remove_client(conn)


def main():
    global assistant
    # An optional .env file in the project folder can hold ANTHROPIC_API_KEY.
    chatbot.load_env_file(Path(__file__).resolve().parent.parent / ".env")
    parser = argparse.ArgumentParser(description="TCP private and group chat server")
    parser.add_argument("--host", default=SERVER)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--bot", default=os.environ.get("CHATBOT_PROVIDER", "claude"),
                        help="chatbot provider: claude (default, needs ANTHROPIC_API_KEY) "
                             "or echo (offline test replies)")
    args = parser.parse_args()
    try:
        assistant = chatbot.Chatbot(args.bot)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"[CHATBOT] {assistant.describe()}", flush=True)
    try:
        start(args.host, args.port)
    except KeyboardInterrupt:
        print("\n[STOPPED] Server stopped.")


if __name__ == "__main__":
    main()
