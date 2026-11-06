import argparse
from datetime import datetime, timezone
import json
import socket
import threading
import unicodedata
import uuid

HEADER = 64
PORT = 5050
SERVER = "0.0.0.0"
FORMAT = "utf-8"
DEFAULT_ROOM = "lobby"
MAX_MESSAGE_BYTES = 1024 * 1024
MAX_USERNAME_LENGTH = 20

# Each connection has a send lock so simultaneous broadcasts cannot mix frames.
clients = {}
usernames = {}
clients_lock = threading.Lock()


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
        "type": kind,
        "room": room,
        "msg_id": uuid.uuid4().hex,
        "sender_id": sender_id,
        "text": text,
        "reply_to": reply_to,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    }


def send_error(conn, code, text):
    message = server_message("error", "server", text)
    message["code"] = code
    frame = encode_message(message)
    with clients_lock:
        send_lock = clients.get(conn)
    if send_lock is not None:
        with send_lock:
            conn.sendall(frame)


def register_client(conn, requested_name):
    if not isinstance(requested_name, str):
        send_error(conn, "invalid_username", "Username must be text")
        return
    name = unicodedata.normalize("NFC", requested_name.strip())
    if not 1 <= len(name) <= MAX_USERNAME_LENGTH or not name.isprintable():
        send_error(conn, "invalid_username", "Username must contain 1-20 printable characters")
        return
    if name.casefold() == "server":
        send_error(conn, "invalid_username", "The username 'server' is reserved")
        return
    with clients_lock:
        send_lock = clients.get(conn)
    if send_lock is None:
        return
    # Registration confirmation must arrive before any lobby broadcasts.
    with send_lock:
        with clients_lock:
            if conn not in clients:
                return
            if conn in usernames:
                code, text = "already_registered", "Reconnect to choose a different username"
            elif any(existing.casefold() == name.casefold() for existing in usernames.values()):
                code, text = "username_taken", "That username is already in use; choose another"
            else:
                usernames[conn] = name
                code = None
        if code:
            response = server_message("error", "server", text)
            response["code"] = code
        else:
            response = server_message("registered", "server", f"Joined the lobby as {name}")
            response["username"] = name
        conn.sendall(encode_message(response))


def remove_client(conn):
    with clients_lock:
        clients.pop(conn, None)
        usernames.pop(conn, None)
    # Wake a handler that may still be blocked in recv().
    try:
        conn.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    conn.close()


def broadcast(message):
    frame = encode_message(message)
    with clients_lock:
        recipients = [(conn, lock) for conn, lock in clients.items() if conn in usernames]
    for conn, send_lock in recipients:
        try:
            with send_lock:
                conn.sendall(frame)
        except OSError:
            remove_client(conn)


def handle_client(conn, addr):
    print(f"[NEW CONNECTION] {addr} connected.", flush=True)
    try:
        while True:
            message = receive_message(conn)
            if message.get("type") == "disconnect":
                break
            if message.get("type") == "register":
                register_client(conn, message.get("username"))
                continue
            if message.get("type") != "chat_message":
                send_error(conn, "unsupported_type", "Expected register, chat_message, or disconnect")
                continue
            with clients_lock:
                username = usernames.get(conn)
            if username is None:
                send_error(conn, "registration_required", "Choose a username before joining the chat")
                continue
            room = message.get("room", DEFAULT_ROOM)
            if room != DEFAULT_ROOM:
                send_error(conn, "unsupported_room", "Only the lobby room is available")
                continue
            text = message.get("text")
            reply_to = message.get("reply_to")
            if not isinstance(text, str) or not (
                reply_to is None
                or isinstance(reply_to, str) and 0 < len(reply_to) <= 128
            ):
                send_error(
                    conn, "invalid_message",
                    "text must be a string; reply_to must be null or a message ID (1-128 characters)",
                )
                continue
            # Identity and metadata come from the server, not client claims.
            outgoing = server_message(
                "chat_message", username, text, room, reply_to
            )
            # Include the sender so every client displays the server's echo.
            try:
                broadcast(outgoing)
            except ValueError as exc:
                send_error(conn, "message_too_large", str(exc))
                continue
            print(f"[{outgoing['sender_id']}] {text}", flush=True)
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
                threading.Thread(
                    target=handle_client, args=(conn, addr), daemon=True
                ).start()
                print(f"[ACTIVE CONNECTIONS] {count}", flush=True)
        finally:
            with clients_lock:
                connections = list(clients)
            for conn in connections:
                remove_client(conn)


def main():
    parser = argparse.ArgumentParser(description="TCP broadcast chat server")
    parser.add_argument("--host", default=SERVER)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    try:
        start(args.host, args.port)
    except KeyboardInterrupt:
        print("\n[STOPPED] Server stopped.")


if __name__ == "__main__":
    main()
