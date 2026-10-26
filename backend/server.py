import socket
import threading

# Global Variable (Port and IP)
HEADER = 64 # Header Byte Length
PORT = 5050
SERVER = socket.gethostbyname(socket.gethostname())
ADDR = (SERVER, PORT) # Binding has to be in tuple
FORMAT = 'utf-8'
DISCOUNECT_MESSAGE = "!DISCONNECT"

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind(ADDR)


# 1 Client - 1 Server
def handle_client(conn, addr):
    print(f"[NEW CONNECTION] {addr} connected.")

    connected = True
    while connected:
        msg_length = conn.recv(HEADER).decode(FORMAT)
        msg_length = int(msg_length)                     # How long the message will be coming
        msg = conn.recv(msg_length).decode(FORMAT)       # How many bytes are we going to receive in the message
        if msg == DISCOUNECT_MESSAGE:
            connected = False
        
        print(f"[{addr}] {msg}")                         # Print the message
    conn.close()


# Handle new connection + Distribute the connection
def start():
    server.listen()
    print(f"[LISTENING] Server is listening on {SERVER}")
    while (True):
        conn, addr = server.accept()
        thread = threading.Thread(target=handle_client, args=(conn, addr))
        thread.start()      # Start the thread
        print(f"[ACTIVE CONNECTIONS] {threading.active_count() - 1}")


def main():
    print("[STARTING] server is starting...")
    start()


if __name__ == "__main__":
    main()
