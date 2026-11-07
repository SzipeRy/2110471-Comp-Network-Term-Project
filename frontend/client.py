import argparse
import json
import socket
import threading

HEADER = 64
PORT = 5050
SERVER = "127.0.0.1"
FORMAT = "utf-8"
DISCONNECT_MESSAGE = "!DISCONNECT"
MEMBERLIST_MESSAGE = "!MEMBERLIST"
GROUPLIST_MESSAGE = "!GROUPLIST"
DEFAULT_ROOM = "lobby"
MAX_MESSAGE_BYTES = 1024 * 1024


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


def create_message(text, room=DEFAULT_ROOM, reply_to=None, room_type="group"):
    """Server-owned fields are filled in when this message is broadcast."""
    return {
        "type": "chat_message",
        "room": room,
        "room_type": room_type,
        "msg_id": None,
        "sender_id": None,
        "text": text,
        "reply_to": reply_to,
        "timestamp": None,
    }


def send(conn, message):
    # Keep terminal input convenient; the wire always carries a JSON object.
    if isinstance(message, str):
        if message == DISCONNECT_MESSAGE:
            message = {"type": "disconnect"}
        elif message == MEMBERLIST_MESSAGE:
            message = {"type": "member_list"}
        elif message == GROUPLIST_MESSAGE:
            message = {"type": "group_list"}
        else:
            message = create_message(message)
    if not isinstance(message, dict):
        raise ValueError("Message must be a JSON object or text")
    payload = json.dumps(message, ensure_ascii=False, allow_nan=False).encode(FORMAT)
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError("JSON message exceeds the 1 MiB limit")
    header = str(len(payload)).encode(FORMAT).ljust(HEADER, b" ")
    conn.sendall(header + payload)


def register(conn, username, *, group_events=False):
    """Return the server-confirmed name, or raise ValueError for a rejected name."""
    request = {"type": "register", "username": username}
    if group_events:
        request["group_events"] = True
    send(conn, request)
    response = receive_message(conn)
    if response.get("type") == "error":
        if response.get("code") in {"invalid_username", "username_taken"}:
            raise ValueError(response["text"])
        if response.get("code") == "unsupported_type":
            raise ConnectionError(
                "The running server does not support username registration. "
                "Stop it with Ctrl+C, restart it with 'python backend/server.py', "
                "then reconnect. If it runs on another device, update and restart it there."
            )
        raise ConnectionError(f"Registration failed: {response.get('text', 'Unknown server error')}")
    if response.get("type") != "registered" or not isinstance(response.get("username"), str):
        raise ConnectionError("Unexpected registration response")
    return response["username"]


def choose_username(conn, username=None):
    while True:
        if username is None:
            username = input("Username (1-20 characters): ")
        try:
            return register(conn, username, group_events=True)
        except ValueError as exc:
            print(f"[ERROR] {exc}", flush=True)
            username = None


HELP = """Choose a destination before sending:
 /private <username>  Enter a private chat with a connected user
 /create <group>      Create, join, and enter a new group
 /join <group>        Join and enter an existing group
 /group <group>       Enter a group you already belong to
 /groups             List available groups and your memberships (!GROUPLIST)
 /members <group>     List members of a group you belong to
 /leave <group>       Leave a group
 /lobby              Enter the public lobby (visible to all registered users)
 /reply <id> <text>   Reply within the currently selected conversation
 !MEMBERLIST         List connected usernames
 !DISCONNECT         Disconnect
 /help               Show these commands
Names can contain spaces; use the full name after the command."""


def handle_input(conn, line):
    """Commands and subsequent text share one ordered server-side selection."""
    if line in (DISCONNECT_MESSAGE, MEMBERLIST_MESSAGE, GROUPLIST_MESSAGE):
        send(conn, line)
        return
    command, _, argument = line.partition(" ")
    argument = argument.strip()
    if command == "/help":
        print(HELP, flush=True)
    elif command == "/groups":
        send(conn, {"type": "group_list"})
    elif command == "/lobby":
        send(conn, {"type": "select_chat", "room_type": "group", "room": DEFAULT_ROOM})
    elif command in ("/private", "/group", "/create", "/join", "/leave", "/members"):
        if not argument:
            raise ValueError(f"Use {command} <name>")
        kinds = {
            "/private": "select_chat", "/group": "select_chat", "/create": "create_group",
            "/join": "join_group", "/leave": "leave_group", "/members": "group_members",
        }
        request = {"type": kinds[command], "room": argument}
        if command in ("/private", "/group"):
            request["room_type"] = "private" if command == "/private" else "group"
        send(conn, request)
    elif command == "/reply":
        parts = argument.split(maxsplit=1)
        if len(parts) != 2:
            raise ValueError("Use /reply <msg_id> <text>")
        send(conn, create_message(parts[1], room=None, room_type=None, reply_to=parts[0]))
    elif command.startswith("/"):
        raise ValueError("Unknown command; use /help")
    else:
        send(conn, create_message(line, room=None, room_type=None))


def receive_messages(conn, disconnected):
    try:
        while True:
            message = receive_message(conn)
            if message.get("type") == "chat_message":
                reply = f", reply to: {message['reply_to']}" if message['reply_to'] else ""
                room = (
                    "private: " + ", ".join(message["participants"])
                    if message.get("room_type") == "private" else "group: " + message["room"]
                )
                print(
                    f"\n[{room}] [{message['sender_id']}] {message['text']}"
                    f" (id: {message['msg_id']}{reply})",
                    flush=True,
                )
            elif message.get("type") == "group_event":
                print(f"\n[group: {message['room']}] [SYSTEM] {message['text']}", flush=True)
            elif message.get("type") == "error":
                print(f"\n[ERROR] {message['code']}: {message['text']}", flush=True)
            elif message.get("type") == "member_list":
                members = message["members"]
                print(
                    f"\n[MEMBERS] Connected members ({len(members)}):\n"
                    + "\n".join(f" - {name}" for name in members),
                    flush=True,
                )
            elif message.get("type") == "group_list":
                print(
                    "\n[GROUPS]\n" + "\n".join(
                        f" - {group['name']} ({group['member_count']} members)"
                        + (" [joined]" if group["joined"] else " [not joined]")
                        for group in message["groups"]
                    ), flush=True,
                )
            elif message.get("type") == "chat_selected":
                print(f"\n[CHAT] {message['text']}", flush=True)
            elif message.get("type") == "group_left":
                print(f"\n[GROUP] {message['text']}. Choose another chat if needed.", flush=True)
            elif message.get("type") == "group_members":
                print(f"\n[GROUP MEMBERS] {message['room']}: " + ", ".join(message["members"]), flush=True)
            else:
                raise ValueError("Unsupported server message type")
    except (EOFError, OSError, ValueError, KeyError):
        if not disconnected.is_set():
            print("\n[DISCONNECTED] Server connection closed. Press Enter to exit.")
    finally:
        disconnected.set()


def main():
    parser = argparse.ArgumentParser(description="TCP private and group chat client")
    parser.add_argument("--host", default=SERVER, help="Server IP address")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--username", help="Chat name (1-20 characters); otherwise prompted")
    args = parser.parse_args()
    disconnected = threading.Event()

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.connect((args.host, args.port))
            print(f"[CONNECTED] {args.host}:{args.port}. Type {DISCONNECT_MESSAGE} to exit.")
            try:
                username = choose_username(client, args.username)
            except (EOFError, KeyboardInterrupt):
                send(client, DISCONNECT_MESSAGE)
                return
            print(f"[REGISTERED] as {username}", flush=True)
            print(HELP, flush=True)
            receiver = threading.Thread(
                target=receive_messages, args=(client, disconnected), daemon=True
            )
            receiver.start()
            try:
                while not disconnected.is_set():
                    message = input("> ")
                    if disconnected.is_set():
                        break
                    try:
                        handle_input(client, message)
                    except ValueError as exc:
                        print(f"[ERROR] {exc}")
                        continue
                    if message == DISCONNECT_MESSAGE:
                        break
            except (EOFError, KeyboardInterrupt):
                if not disconnected.is_set():
                    send(client, DISCONNECT_MESSAGE)
            finally:
                disconnected.set()
                try:
                    client.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                receiver.join(timeout=2)
    except OSError as exc:
        print(f"[ERROR] {exc}")


if __name__ == "__main__":
    main()
