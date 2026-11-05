import argparse
import socket
import threading

HEADER = 64
PORT = 5050
SERVER = "127.0.0.1"
FORMAT = "utf-8"
DISCONNECT_MESSAGE = "!DISCONNECT"
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
    # Allow space for the sender's address added by the server.
    if not 0 <= length <= MAX_MESSAGE_BYTES + 128:
        raise ValueError("Invalid message length")
    return recv_exact(conn, length).decode(FORMAT)


def send(conn, message):
    payload = message.encode(FORMAT)
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError("Message exceeds the 1 MiB limit")
    header = str(len(payload)).encode(FORMAT).ljust(HEADER, b" ")
    conn.sendall(header + payload)


def receive_messages(conn, disconnected):
    try:
        while True:
            message = receive_message(conn)
            print(f"\n{message}", flush=True)
    except (EOFError, OSError, ValueError):
        if not disconnected.is_set():
            print("\n[DISCONNECTED] Server connection closed. Press Enter to exit.")
    finally:
        disconnected.set()


def main():
    parser = argparse.ArgumentParser(description="TCP broadcast chat client")
    parser.add_argument("--host", default=SERVER, help="Server IP address")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    disconnected = threading.Event()

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.connect((args.host, args.port))
            print(f"[CONNECTED] {args.host}:{args.port}. Type {DISCONNECT_MESSAGE} to exit.")
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
