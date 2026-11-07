import math
import tkinter as tk
from tkinter import font as tkfont

from . import theme as T
from .emoji_picker import EmojiPicker
from .mentions import mention_query, split_mentions, suggest
from .net_interface import BOT_NAME, private_peer

# Keys that move through or close the @mention suggestions instead of searching again.
SUGGESTION_KEYS = {"Up", "Down", "Return", "KP_Enter", "Tab", "Escape"}
MODIFIER_PREFIXES = ("Shift", "Control", "Alt", "Meta", "Super", "Caps", "Command", "Option")


class ChatRoom(tk.Frame):
    """Sketch 2/4/5 · one chat room (R5): header, message window and chat box (R6).
    Used for private, group and bot rooms."""

    def __init__(self, master, app, room_type, room_id):
        super().__init__(master, bg=T.CARD)
        self.app, self.room_type, self.room_id = app, room_type, room_id
        self.messages = {}      # message_id -> msg (for reply quotes)
        self.system_messages = {}  # server event IDs, separate from replyable chat
        self.reply_to = None
        self.unsent = None      # (text, reply_to) sent but not yet echoed by the server
        self.typing_row = None
        self.emoji_picker = None

        # header bar
        head = tk.Frame(self, bg=T.BG)
        head.pack(fill="x")
        self.header = tk.Label(head, font=T.F_BOLD, bg=T.BG, fg=T.INK, anchor="w", padx=10, pady=6)
        self.header.pack(side="left", fill="x", expand=True)
        self.join_btn = T.button(head, "Join", lambda: app.client.join_group(room_id), primary=True)
        self.leave_btn = T.button(head, "Leave group", lambda: app.main.leave_group(room_id))
        self.joined = None  # group rooms only: None until the first update
        tk.Frame(self, bg=T.LINE, height=1).pack(fill="x")

        # chat box (packed at the bottom first so it never gets squeezed out)
        self.bottom = tk.Frame(self, bg=T.CARD, padx=8, pady=8)
        self.bottom.pack(side="bottom", fill="x")
        tk.Frame(self, bg=T.LINE, height=1).pack(side="bottom", fill="x")
        self.reply_bar = tk.Frame(self.bottom, bg=T.CARD)
        tk.Frame(self.reply_bar, bg=T.ACC, width=3).pack(side="left", fill="y")
        self.reply_lbl = tk.Label(self.reply_bar, font=T.F_SMALL, fg=T.MUTE, bg=T.CARD, anchor="w")
        self.reply_lbl.pack(side="left", fill="x", expand=True, padx=6)
        tk.Button(self.reply_bar, text="✕", font=T.F_SMALL, relief="flat", bd=0, bg=T.CARD, fg=T.MUTE,
                  highlightthickness=0,  # no dark focus frame around it in macOS dark mode
                  cursor="hand2", command=self.clear_reply).pack(side="right")
        self.locked_lbl = tk.Label(self.bottom, text="Join this group to send messages",
                                   font=T.F_SMALL, fg=T.MUTE, bg=T.CARD, anchor="w")
        self.input_row = tk.Frame(self.bottom, bg=T.CARD)
        self.input_row.pack(fill="x")
        self.entry = T.entry(self.input_row)
        self.entry.pack(side="left", fill="x", expand=True, ipady=5)
        self.entry.bind("<Return>", self._on_return)
        self.emoji_btn = T.button(self.input_row, "😀", self.open_emoji)
        self.emoji_btn.pack(side="left", padx=4)
        self.send_btn = T.button(self.input_row, "Send", self.send, primary=True)
        self.send_btn.pack(side="left")

        # message window
        self.list = T.ScrollFrame(self)
        self.list.pack(fill="both", expand=True)

        # @mention suggestions: drawn over the message window, just above the chat box
        self.unread_mentions = 0  # messages mentioning you since you last looked at this chat
        self.suggested = []
        self.suggest_box = tk.Listbox(self, font=T.F, width=26, activestyle="none", relief="flat",
                                      bd=0, highlightthickness=1, highlightbackground=T.LINE,
                                      bg=T.CARD, fg=T.INK, selectbackground=T.ME,
                                      selectforeground=T.INK, exportselection=False, takefocus=0)
        self.suggest_box.bind("<ButtonRelease-1>",
                              lambda e: self.accept_suggestion(self.suggest_box.nearest(e.y)))
        self.entry.bind("<KeyRelease>", self._on_key_release, add="+")
        self.entry.bind("<Down>", lambda _e: self._move_suggestion(1))
        self.entry.bind("<Up>", lambda _e: self._move_suggestion(-1))
        self.entry.bind("<Tab>", lambda _e: self.accept_suggestion() if self.suggested else None)
        self.entry.bind("<Escape>", lambda _e: self.hide_suggestions())

        if room_type == "private":
            other = private_peer(room_id, app.username)
            self.header.config(text=f"Private chat with {other}")
        elif room_type == "bot":
            self.header.config(text="🤖 Chatbot")
        self.add_system({"private": "Only you and the other person can see this chat",
                         "group": "Only group members can see this chat",
                         "bot": "Ask the AI chatbot anything"}[room_type])

    # ---------- group membership (R10, R11) ----------
    def set_group_info(self, info):
        """Active = joined. Inactive = not joined, left, or the group was deleted (read-only)."""
        exists = info is not None
        joined = exists and info.joined
        if self.joined is not None and joined != self.joined:
            if not joined or not self.app.client.supports_group_events:
                self.add_system("You joined the group" if joined else "You left the group")
        was_member = self.joined is not None and (self.joined or getattr(self, "_left", False))
        self._left = was_member and not joined
        self.joined = joined

        self.join_btn.pack_forget()
        self.leave_btn.pack_forget()
        self.locked_lbl.pack_forget()
        if not exists:
            self.header.config(text=f"#{self.room_id}  ·  group closed", fg=T.MUTE)
            self.locked_lbl.config(text="This group no longer exists. You can still read old messages.")
        else:
            detail = ("members: " + ", ".join(info.members) if info.members is not None
                      else f"{info.member_count} members")
            self.header.config(text=f"#{self.room_id}  ·  {detail}", fg=T.INK)
            if joined:
                if self.room_id != "lobby":
                    self.leave_btn.pack(side="right", padx=8)
            else:
                self.join_btn.pack(side="right", padx=8)
                self.locked_lbl.config(text="You left this group. Join again to send messages."
                                       if self._left else "Join this group to send messages")
        if not joined:
            self.locked_lbl.pack(fill="x", pady=(0, 4), before=self.input_row)
            self.clear_reply()
            self.close_emoji()
            self.hide_suggestions()
        for w in (self.entry, self.emoji_btn, self.send_btn):
            T.set_enabled(w, joined)

    # ---------- sending ----------
    def send(self):
        text = self.entry.get().strip()
        if not text or self.entry.cget("state") == "disabled":
            return
        if self.room_type == "bot" and self.typing_row:
            return  # the server takes one chatbot question at a time; keep the draft
        if self.app.client.send_message(self.room_type, self.room_id, text, self.reply_to) is False:
            return
        self.unsent = (text, self.reply_to)  # kept until the server echoes it back
        self.entry.delete(0, "end")
        self.clear_reply()
        self.hide_suggestions()

    def restore_unsent(self):
        """The server rejected a message: put it back in an empty chat box so it is not lost."""
        if not self.unsent or self.entry.cget("state") == "disabled" or self.entry.get().strip():
            return
        text, reply_to = self.unsent
        self.entry.insert(0, text)
        if reply_to in self.messages:
            self.set_reply(reply_to)

    def _forget_unsent(self, msg):
        """Our own message came back from the server, so it was delivered."""
        if self.unsent and msg["text"] == self.unsent[0]:
            if self.entry.get().strip() == self.unsent[0]:  # restored by an unrelated error
                self.entry.delete(0, "end")
                self.clear_reply()
            self.unsent = None

    def _on_return(self, _e=None):
        if self.suggested:
            return self.accept_suggestion()
        self.send()

    def open_emoji(self):
        self.close_emoji()
        self.emoji_picker = EmojiPicker(
            self.emoji_btn, lambda e: (self.entry.insert("insert", e), self.entry.focus()))

    def close_emoji(self):
        if self.emoji_picker is not None and self.emoji_picker.winfo_exists():
            self.emoji_picker.destroy()
        self.emoji_picker = None

    # ---------- displaying ----------
    def add_system(self, text):
        tk.Label(self.list.inner, text=text, font=T.F_SMALL, fg=T.MUTE, bg=T.CARD).pack(pady=(8, 4))

    def add_message(self, msg):
        """Draw a message once. Returns True only for a newly drawn chat message."""
        if msg["type"] == "system_message":
            if msg["message_id"] not in self.system_messages:
                self.system_messages[msg["message_id"]] = msg
                self.add_system(msg["text"])
                self.list.scroll_to_end()
            return False
        if msg["message_id"] in self.messages:
            return False
        self.messages[msg["message_id"]] = msg
        mine = msg["sender"] == self.app.username
        from_bot = msg["sender"] == BOT_NAME
        names = msg.get("mentions") or []
        me = (self.app.username or "").casefold()
        # Only people's messages turn yellow; the bot's answers stay green (names are still highlighted).
        mentions_me = not mine and not from_bot and any(name.casefold() == me for name in names)
        if self.typing_row and not mine:
            self.typing_row.destroy()
            self.typing_row = None
        if mine:
            color = T.ME
        elif mentions_me:
            color = T.MENTION
        else:
            color = T.BOT if from_bot or self.room_type == "bot" else T.THEM

        row = tk.Frame(self.list.inner, bg=T.CARD)
        row.pack(fill="x", padx=10, pady=3)
        bubble = tk.Frame(row, bg=color, padx=9, pady=5)
        bubble.pack(side="right" if mine else "left")

        who = "You" if mine else (f"🤖 {BOT_NAME}" if from_bot else msg["sender"])
        tk.Label(bubble, text=f"{who}  {msg.get('timestamp', '')[11:16]}", font=T.F_SMALL,
                 fg=T.MUTE, bg=color, anchor="w").pack(fill="x")

        quoted = self.messages.get(msg.get("reply_to"))
        if msg.get("reply_to"):  # reply quote with a blue strip
            q = tk.Frame(bubble, bg=color)
            q.pack(fill="x", pady=(2, 3))
            tk.Frame(q, bg=T.ACC, width=3).pack(side="left", fill="y")
            quote = f"{quoted['sender']}: {quoted['text'][:50]}" if quoted else "Original message unavailable"
            tk.Label(q, text=quote, font=T.F_SMALL, fg=T.MUTE,
                     bg=color, justify="left", wraplength=260).pack(side="left", padx=(5, 0))

        text = msg["text"]
        # Text.width uses font character cells, not Unicode code-point counts.
        font = tkfont.Font(font=T.F)
        pixels = max((font.measure(line) for line in text.splitlines()), default=1)
        width = min(math.ceil(pixels / max(1, font.measure("0"))) + 1, 42)
        body = tk.Text(bubble, font=T.F, bg=color, fg=T.INK, relief="flat", bd=0, highlightthickness=0,
                       wrap="word", width=width, height=1, padx=0, pady=0, cursor="arrow")
        body.tag_config("mention", foreground=T.ACC, font=T.F_BOLD)
        body.tag_config("mention_me", foreground=T.INK, background=T.MENTION_TAG, font=T.F_BOLD)
        # Highlight exactly the names the server confirmed as mentions.
        for part, name in split_mentions(text, names):
            tag = () if name is None else ("mention_me" if name.casefold() == me else "mention")
            body.insert("end", part, tag)
        body.config(state="disabled")
        body.pack(anchor="w")
        body.bind("<Map>", lambda _e, b=body: self._fit(b))  # measure once it's laid out

        T.bind_tree(bubble, "<Button-3>", lambda e, m=msg["message_id"]: self._menu(e, m))
        T.bind_tree(bubble, "<Button-2>", lambda e, m=msg["message_id"]: self._menu(e, m))  # macOS
        if mine:
            self._forget_unsent(msg)
            self._note_outside_mentions(names)
            if self.room_type == "bot":
                self._show_typing()  # after the server echo, so it sits below the question
        return True

    def _note_outside_mentions(self, names):
        """A mention never shares a message, so tell the sender who will not see it."""
        if self.room_type == "private":
            members = {self.app.username, private_peer(self.room_id, self.app.username)}
        elif self.room_type == "group":
            info = self.app.groups.get(self.room_id)
            if info is None or info.members is None:
                return
            members = set(info.members)
        else:
            return
        outside = [name for name in names if name != BOT_NAME and name not in members]
        if outside:
            verb = "is" if len(outside) == 1 else "are"
            self.add_system(f"{', '.join(outside)} {verb} not in this chat, "
                            "so they will not see this message")

    def _fit(self, body):
        """Grow the Text widget to its wrapped height, then scroll down."""
        if not body.winfo_exists():
            return
        body.update_idletasks()
        n = body.count("1.0", "end", "displaylines")
        n = n[0] if isinstance(n, tuple) else n
        body.config(height=max(1, n or 1))
        self.list.scroll_to_end()

    def _show_typing(self):
        if self.typing_row:
            return
        self.typing_row = tk.Frame(self.list.inner, bg=T.CARD)
        self.typing_row.pack(fill="x", padx=10, pady=3)
        tk.Label(self.typing_row, text="Bot is typing…", font=T.F_SMALL, fg=T.MUTE, bg=T.BOT,
                 padx=9, pady=5).pack(side="left")
        self.list.scroll_to_end()

    # ---------- reply (right-click a message) ----------
    def _menu(self, event, message_id):
        if self.entry.cget("state") == "disabled":
            return
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="Reply", command=lambda: self.set_reply(message_id))
        m.tk_popup(event.x_root, event.y_root)

    def set_reply(self, message_id):
        msg = self.messages[message_id]
        self.reply_to = message_id
        self.reply_lbl.config(text=f"Replying to {msg['sender']}: {msg['text'][:40]}")
        self.reply_bar.pack(fill="x", pady=(0, 6), before=self.input_row)
        self.entry.focus()

    def clear_reply(self):
        self.reply_to = None
        self.reply_bar.pack_forget()

    # ---------- @mention suggestions (type "@", then Up/Down and Enter/Tab, or click) ----------
    def mention_candidates(self):
        """People who can read this chat, plus the chatbot: the names worth mentioning."""
        me = self.app.username
        if self.room_type == "private":
            names = [private_peer(self.room_id, me)]
        elif self.room_type == "group":
            info = self.app.groups.get(self.room_id)
            names = list(info.members or ()) if info is not None and info.joined else []
        else:
            return []  # nobody else reads the chatbot room
        names = [name for name in names if name != me]
        if self.app.client.supports_bot:
            names.append(BOT_NAME)
        return names

    def _entry_text(self):
        """The entry's text and cursor, with the cursor as a Python string index."""
        text, cursor = self.entry.get(), self.entry.index("insert")
        if self.entry.index("end") != len(text):  # Tk 8.6 counts emoji as two characters
            cursor = len(text.encode("utf-16-le")[:cursor * 2].decode("utf-16-le", "ignore"))
        return text, cursor

    def _tk_index(self, text, index):
        """Convert a Python index in the entry's current text to a Tk entry index."""
        if self.entry.index("end") != len(text):
            return len(text[:index].encode("utf-16-le")) // 2
        return index

    def update_mention_suggestions(self):
        """Offer names matching the "@partial" just before the cursor."""
        found = None
        if self.entry.cget("state") != "disabled":
            text, cursor = self._entry_text()
            found = mention_query(text[:cursor])
        names = suggest(found[1], self.mention_candidates()) if found else []
        if not names:
            self.hide_suggestions()
            return
        self.suggested = names
        self.suggest_box.delete(0, "end")
        for name in names:
            self.suggest_box.insert("end", f"  🤖 @{name}" if name == BOT_NAME else f"  @{name}")
        self.suggest_box.config(height=len(names))
        self._select_suggestion(0)
        # Bottom-left of the message window, lined up with the entry and clear of the divider.
        self.suggest_box.place(in_=self.list, x=8, rely=1.0, y=-6, anchor="sw")
        self.suggest_box.lift()

    def _select_suggestion(self, index):
        self.suggest_box.selection_clear(0, "end")
        self.suggest_box.selection_set(index)
        self.suggest_box.activate(index)

    def _move_suggestion(self, step):
        if not self.suggested:
            return None
        current = self.suggest_box.curselection()
        self._select_suggestion(((current[0] if current else 0) + step) % len(self.suggested))
        return "break"

    def accept_suggestion(self, index=None):
        """Replace "@partial" before the cursor with "@Full Name " and keep typing."""
        text, cursor = self._entry_text()
        found = mention_query(text[:cursor])
        if not self.suggested or found is None:
            self.hide_suggestions()
            return None
        if index is None:
            current = self.suggest_box.curselection()
            index = current[0] if current else 0
        name = self.suggested[min(index, len(self.suggested) - 1)]
        start = self._tk_index(text, found[0])
        self.entry.delete(start, self._tk_index(text, cursor))
        self.entry.insert(start, f"@{name} ")
        self.entry.icursor(self._tk_index(self.entry.get(), found[0] + len(name) + 2))
        self.hide_suggestions()
        self.entry.focus_set()
        return "break"

    def hide_suggestions(self):
        self.suggested = []
        self.suggest_box.place_forget()

    def _on_key_release(self, event):
        if event.keysym in SUGGESTION_KEYS or event.keysym.startswith(MODIFIER_PREFIXES):
            return
        self.update_mention_suggestions()
