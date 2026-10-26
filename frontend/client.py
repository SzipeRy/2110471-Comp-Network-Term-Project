import socket


HEADER = 64 # Header Byte Length
PORT = 5050
SERVER = socket.gethostbyname(socket.gethostname())
ADDR = (SERVER, PORT) # Binding has to be in tuple
FORMAT = 'utf-8'
DISCOUNECT_MESSAGE = "!DISCONNECT"

client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect(ADDR)

def send(msg):
    message = msg.encode(FORMAT)
    msg_length = len(message)
    send_length = str(msg_length).encode(FORMAT)
    send_length += b' ' * (HEADER - len(send_length))
    client.send(send_length)
    client.send(message)
    print(client.recv(2048).decode(FORMAT))

def main():
    msg = str(input(f"[{ADDR}] "))
    send(msg)
    while (msg != DISCOUNECT_MESSAGE):
        msg = str(input(f"[{ADDR}] "))
        send(msg)

if __name__ == "__main__":
    main()
