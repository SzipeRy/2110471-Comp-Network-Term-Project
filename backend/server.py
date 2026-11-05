import argparse
import socket
import threading

HEADER = 64
PORT = 5050
SERVER = "0.0.0.0"
FORMAT = "utf-8"
DISCONNECT_MESSAGE = "!DISCONNECT"
MAX_MESSAGE_BYTES = 1024 * 1024

# Each connection has a send lock so simultaneous broadcasts cannot mix frames.
clients = {}
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
    if not 0 <= length <= MAX_MESSAGE_BYTES:
        raise ValueError("Invalid message length")
    return recv_exact(conn, length).decode(FORMAT)


def remove_client(conn):
    with clients_lock:
        clients.pop(conn, None)
    # Wake a handler that may still be blocked in recv().
    try:
        conn.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    conn.close()


def broadcast(message):
    payload = message.encode(FORMAT)
    frame = str(len(payload)).encode(FORMAT).ljust(HEADER, b" ") + payload
    with clients_lock:
        recipients = list(clients.items())
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
            if message == DISCONNECT_MESSAGE:
                break
            displayed = f"[{addr[0]}:{addr[1]}] {message}"
            print(displayed, flush=True)
            # Include the sender so every client displays the server's echo.
            broadcast(displayed)
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
