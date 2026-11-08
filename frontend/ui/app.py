"""Entry point (from the repository root): python -m frontend.ui.app --real
Also supported from the frontend folder:
    python -m ui.app          -> mock backend (no server needed)
    python -m ui.app --real   -> real client from Person 4 (frontend/network_client.py, class NetworkClient)"""
import gc
import queue
import sys
import tkinter as tk
from tkinter import messagebox

from . import theme
from .login import LoginFrame
from .main_window import MainWindow


class App(tk.Tk):
    def __init__(self, client):
        super().__init__()
        self.title("Chat")
        self.geometry("900x580")
        self.minsize(700, 450)
        theme.setup_style(self)
        self.client = client
        self.username, self.users, self.groups = None, [], {}
        self.main = None
        self.pending_messages = []
        self.pending_send = None  # the ChatRoom whose sent message awaits its echo or an error
        self.closing = False
        self.q = queue.Queue()  # network threads -> UI thread (Tkinter is not thread-safe)
        client.set_handlers(
            on_message=lambda m: self.q.put(("msg", m)),
            on_users=lambda u: self.q.put(("users", u)),
            on_groups=lambda g: self.q.put(("groups", g)),
            on_error=lambda e: self.q.put(("error", e)),
            on_disconnect=lambda: self.q.put(("bye", None)))
        self.login = LoginFrame(self, self)
        self.login.pack(expand=True)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = self.after(100, self._poll)

    def show_main(self, username):
        self.username = username
        self.login.pack_forget()
        self.main = MainWindow(self, self)
        self.main.pack(fill="both", expand=True)
        self.title(f"Chat – {username}")
        self.bind("<Control-w>", lambda _e: self.main.close_current() if self.main else None)
        for msg in self.pending_messages:
            self.main.on_message(msg)
        self.pending_messages.clear()

    def _poll(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "connected":
                    if getattr(self.client, "connected", True):
                        self.show_main(data)
                    continue
                if kind == "connect_failed":
                    self.login._fail(data)
                    continue
                if kind == "users":
                    self.users = data
                elif kind == "groups":
                    self.groups = data
                if kind == "error":
                    # Errors carry no request ID: any error ends the wait for the pending message,
                    # which stays in its chat box (now editable) instead of being lost.
                    room, self.pending_send = self.pending_send, None
                    if room is not None and room.winfo_exists():
                        room.send_finished(delivered=False)
                    messagebox.showerror("Error", data)
                elif kind == "bye":
                    if self.main:
                        self.main.destroy()
                        self.main = None
                    self.username, self.users, self.groups = None, [], {}
                    self.pending_send = None
                    self.pending_messages.clear()
                    self.title("Chat – Login")
                    self.login.pack(expand=True)
                    self.login._fail("Disconnected. You can connect again.")
                    messagebox.showwarning("Disconnected", "Lost connection to the server")
                elif self.main:
                    {"msg": self.main.on_message, "users": self.main.update_users,
                     "groups": self.main.update_groups}[kind](data)
                elif kind == "msg":
                    self.pending_messages.append(data)
        except queue.Empty:
            pass
        if not self.closing:
            self.poll_id = self.after(100, self._poll)

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.after_cancel(self.poll_id)
        self.client.close()
        self.client.set_handlers(*(lambda *args: None for _ in range(5)))
        self.destroy()
        self.main = self.login = None
        self._close_imgs = ()
        # Dispose of destroyed widget cycles on Tk's thread, not a socket worker.
        gc.collect()


if __name__ == "__main__":
    if "--real" in sys.argv:
        if __package__ == "frontend.ui":
            from ..network_client import NetworkClient
        else:
            from network_client import NetworkClient
        client = NetworkClient()
    else:
        from .mock_client import MockClient
        client = MockClient()
    App(client).mainloop()
