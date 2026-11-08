import tkinter as tk

from . import theme as T


class GroupsDialog(tk.Toplevel):
    """Sketch 3 · R8 create · R9 all groups with members · R10 join by choice."""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.title("Groups")
        self.geometry("420x430")
        self.configure(bg=T.CARD, padx=14, pady=12)
        self.transient(master.winfo_toplevel())

        T.section(self, "All groups").pack(fill="x")
        self.list = T.ScrollFrame(self)
        self.list.pack(fill="both", expand=True, pady=(4, 8))

        tk.Frame(self, bg=T.LINE, height=1).pack(fill="x", pady=4)
        T.section(self, "Create group").pack(fill="x", pady=(6, 2))
        row = tk.Frame(self, bg=T.CARD)
        row.pack(fill="x")
        self.name = T.entry(row)
        self.name.pack(side="left", fill="x", expand=True, ipady=4)
        self.name.bind("<Return>", lambda _e: self.create())
        T.button(row, "Create", self.create, primary=True).pack(side="left", padx=(6, 0))
        tk.Label(self, text="You start as the only member. Others must press Join themselves.",
                 font=T.F_SMALL, fg=T.MUTE, bg=T.CARD, anchor="w").pack(fill="x", pady=(6, 0))
        self.refresh()

    def refresh(self):
        for w in self.list.inner.winfo_children():
            w.destroy()
        if not self.app.groups:
            tk.Label(self.list.inner, text="No groups yet", font=T.F, fg=T.MUTE, bg=T.CARD).pack(pady=10)
        for g, group in sorted(self.app.groups.items()):
            joined = group.joined
            row = tk.Frame(self.list.inner, bg=T.CARD, pady=5)
            row.pack(fill="x")
            info = tk.Frame(row, bg=T.CARD)
            info.pack(side="left", fill="x", expand=True)
            tk.Label(info, text=f"#{g}", font=T.F_BOLD, fg=T.INK, bg=T.CARD, anchor="w").pack(fill="x")
            detail = ("members: " + ", ".join(group.members) if group.members is not None
                      else f"{group.member_count} members")
            tk.Label(info, text=detail, font=T.F_SMALL, fg=T.MUTE,
                     bg=T.CARD, anchor="w", justify="left", wraplength=250).pack(fill="x")
            if joined:
                if g != "lobby":
                    T.button(row, "Leave", lambda g=g: self.app.main.leave_group(g, parent=self)).pack(side="right")
                T.button(row, "Open", lambda g=g: self.app.main.open_group(g)).pack(side="right", padx=4)
                tk.Label(row, text="Joined ✓", font=T.F_SMALL, fg=T.ONLINE, bg=T.CARD).pack(side="right", padx=6)
            else:
                T.button(row, "Join", lambda g=g: self.app.client.join_group(g), primary=True).pack(side="right")

    def create(self):
        name = self.name.get().strip().lstrip("#")
        if not name:
            return
        self.app.client.create_group(name)
        self.name.delete(0, "end")
