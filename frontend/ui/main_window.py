import tkinter as tk
from tkinter import ttk

from .net_interface import private_room_id
from . import theme as T
from .chat_room import ChatRoom
from .groups_dialog import GroupsDialog


class MainWindow(tk.Frame):
    """Sketch 2 · sidebar (R4 online users, R9 groups, AI bot) + tabbed chat rooms (R5)."""

    def __init__(self, master, app):
        super().__init__(master, bg=T.BG)
        self.app = app
        self.rooms = {}       # (room_type, room_id) -> ChatRoom
        self.titles = {}      # ChatRoom -> tab title
        self.groups_dlg = None

        side = tk.Frame(self, bg=T.CARD, width=190)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Frame(self, bg=T.LINE, width=1).pack(side="left", fill="y")

        T.section(side, "Online users").pack(fill="x", padx=12, pady=(12, 2))
        self.users_box = tk.Frame(side, bg=T.CARD)
        self.users_box.pack(fill="x", padx=6)
        T.section(side, "Groups").pack(fill="x", padx=12, pady=(12, 2))
        self.groups_box = tk.Frame(side, bg=T.CARD)
        self.groups_box.pack(fill="x", padx=6)
        T.button(side, "+ New / join group", self.show_groups).pack(anchor="w", padx=12, pady=8)
        T.section(side, "AI").pack(fill="x", padx=12, pady=(8, 2))
        self.ai_box = tk.Frame(side, bg=T.CARD)
        self.ai_box.pack(fill="x", padx=6)
        tk.Label(side, text="Click a name to chat", font=T.F_SMALL, fg=T.MUTE,
                 bg=T.CARD).pack(side="bottom", pady=8)

        right = tk.Frame(self, bg=T.BG)
        right.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        self.placeholder = tk.Label(right, text="Select a user, group or the chatbot to start chatting",
                                    font=T.F, fg=T.MUTE, bg=T.BG)
        self.placeholder.pack(expand=True)
        self.tabs = ttk.Notebook(right, style="Chat.TNotebook")
        self.tabs.bind("<<NotebookTabChanged>>", self._tab_changed)
        self.render_sidebar()

    # ---------- sidebar ----------
    def _row(self, parent, text, on_click, selected=False, dot=False):
        bg = T.ME if selected else T.CARD
        row = tk.Frame(parent, bg=bg, padx=6, pady=3, cursor="hand2")
        row.pack(fill="x", pady=1)
        if dot:
            c = tk.Canvas(row, width=8, height=8, bg=bg, highlightthickness=0)
            c.create_oval(0, 0, 7, 7, fill=T.ONLINE, outline="")
            c.pack(side="left", padx=(0, 6))
        tk.Label(row, text=text, font=T.F, fg=T.INK, bg=bg, anchor="w").pack(side="left", fill="x")

        def hover(on):
            if not selected and row.winfo_exists():
                for w in [row, *row.winfo_children()]:
                    w.config(bg=T.THEM if on else T.CARD)
        T.bind_tree(row, "<Enter>", lambda _e: hover(True))
        T.bind_tree(row, "<Leave>", lambda _e: hover(False))
        T.bind_tree(row, "<Button-1>", lambda _e: on_click())

    def render_sidebar(self):
        cur = self._current_key()
        for box in (self.users_box, self.groups_box, self.ai_box):
            for w in box.winfo_children():
                w.destroy()
        me = self.app.username
        for u in self.app.users:  # R4: includes yourself
            if u == me:
                self._row(self.users_box, f"{u} (you)", lambda: None, dot=True)
            else:
                rid = private_room_id(me, u)
                self._row(self.users_box, u, lambda rid=rid: self._room("private", rid, select=True),
                          selected=cur == ("private", rid), dot=True)
        if not self.app.groups:
            tk.Label(self.groups_box, text="No groups yet", font=T.F_SMALL, fg=T.MUTE,
                     bg=T.CARD).pack(anchor="w", padx=6)
        for g, members in sorted(self.app.groups.items()):  # R9
            mark = " ✓" if me in members else ""
            self._row(self.groups_box, f"#{g} ({len(members)}){mark}", lambda g=g: self.open_group(g),
                      selected=cur == ("group", g))
        self._row(self.ai_box, "🤖 Chatbot", self.open_bot, selected=cur == ("bot", "chatbot"))

    # ---------- updates pushed from the client ----------
    def update_users(self, _users):
        self.render_sidebar()

    def update_groups(self, groups):
        self.render_sidebar()
        for (rtype, rid), room in self.rooms.items():
            if rtype == "group":
                room.set_group_info(groups.get(rid, []))
        if self.groups_dlg and self.groups_dlg.winfo_exists():
            self.groups_dlg.refresh()

    def on_message(self, msg):
        room = self._room(msg["room_type"], msg["room_id"])
        room.add_message(msg)
        if self._current_key() != (msg["room_type"], msg["room_id"]):
            self.tabs.tab(room, text=self.titles[room] + "  •")  # unread dot

    # ---------- rooms / tabs ----------
    def _title(self, rtype, rid):
        if rtype == "private":
            return next(u for u in rid.split("-") if u != self.app.username)
        return "🤖 Bot" if rtype == "bot" else f"#{rid}"

    def _current_key(self):
        if not self.rooms:
            return None
        sel = self.tabs.select()
        for key, room in self.rooms.items():
            if str(room) == sel:
                return key
        return None

    def _room(self, rtype, rid, select=False):
        key = (rtype, rid)
        if key not in self.rooms:
            if not self.rooms:
                self.placeholder.pack_forget()
                self.tabs.pack(fill="both", expand=True)
            room = ChatRoom(self.tabs, self.app, rtype, rid)
            self.rooms[key] = room
            self.titles[room] = self._title(rtype, rid)
            self.tabs.add(room, text=self.titles[room])
            if rtype == "group":
                room.set_group_info(self.app.groups.get(rid, []))
        if select:
            self.tabs.select(self.rooms[key])
        return self.rooms[key]

    def _tab_changed(self, _e=None):
        key = self._current_key()
        if key:
            room = self.rooms[key]
            self.tabs.tab(room, text=self.titles[room])  # clear unread dot
            room.entry.focus()
        self.render_sidebar()

    def open_group(self, name):
        self._room("group", name, select=True)

    def open_bot(self):
        self._room("bot", "chatbot", select=True)

    def show_groups(self):
        if self.groups_dlg and self.groups_dlg.winfo_exists():
            self.groups_dlg.lift()
        else:
            self.groups_dlg = GroupsDialog(self, self.app)
