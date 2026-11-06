import argparse
import json
import socket
import threading

HEADER = 64
PORT = 5050
SERVER = "127.0.0.1"
FORMAT = "utf-8"
DISCONNECT_MESSAGE = "!DISCONNECT"
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


def create_message(text, room=DEFAULT_ROOM, reply_to=None):
    """Server-owned fields are filled in when this message is broadcast."""
    return {
        "type": "chat_message",
        "room": room,
        "msg_id": None,
        "sender_id": None,
        "text": text,
        "reply_to": reply_to,
        "timestamp": None,
    }


def send(conn, message):
    # Keep terminal input convenient; the wire always carries a JSON object.
    if isinstance(message, str):
        message = (
            {"type": "disconnect"}
            if message == DISCONNECT_MESSAGE else create_message(message)
        )
    if not isinstance(message, dict):
        raise ValueError("Message must be a JSON object or text")
    payload = json.dumps(message, ensure_ascii=False, allow_nan=False).encode(FORMAT)
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError("JSON message exceeds the 1 MiB limit")
    header = str(len(payload)).encode(FORMAT).ljust(HEADER, b" ")
    conn.sendall(header + payload)


def register(conn, username):
    """Return the server-confirmed name, or raise ValueError for a rejected name."""
    send(conn, {"type": "register", "username": username})
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
            return register(conn, username)
        except ValueError as exc:
            print(f"[ERROR] {exc}", flush=True)
            username = None


def receive_messages(conn, disconnected):
    try:
        while True:
            message = receive_message(conn)
            if message.get("type") == "chat_message":
                reply = f", reply to: {message['reply_to']}" if message['reply_to'] else ""
                print(
                    f"\n[{message['room']}] [{message['sender_id']}] {message['text']}"
                    f" (id: {message['msg_id']}{reply})",
                    flush=True,
                )
            elif message.get("type") == "error":
                print(f"\n[ERROR] {message['code']}: {message['text']}", flush=True)
            else:
                raise ValueError("Unsupported server message type")
    except (EOFError, OSError, ValueError, KeyError):
        if not disconnected.is_set():
            print("\n[DISCONNECTED] Server connection closed. Press Enter to exit.")
    finally:
        disconnected.set()


def main():
    parser = argparse.ArgumentParser(description="TCP broadcast chat client")
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
            print(f"[JOINED] {DEFAULT_ROOM} as {username}", flush=True)
            print("Reply with /reply <msg_id> <text>.")
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
                        if message == "/reply" or message.startswith("/reply "):
                            parts = message.split(maxsplit=2)
                            if len(parts) != 3:
                                raise ValueError("Use /reply <msg_id> <text>")
                            send(client, create_message(parts[2], reply_to=parts[1]))
                        else:
                            send(client, message)
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
