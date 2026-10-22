"""Native Tkinter user interface for Local Chat App."""
from __future__ import annotations

import base64
import os
import tempfile
import threading
import uuid
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from app.discovery import DiscoveryResponder, discover_servers, get_local_ipv4
from app.sockets import FILE_CHUNK_SIZE, MAX_FILE_SIZE, ChatClient, ChatServer

COLORS = {
    "bg": "#f2f4f8", "panel": "#ffffff", "sidebar": "#202944",
    "sidebar_text": "#f3f5ff", "ink": "#1d2638", "muted": "#778196",
    "accent": "#6268e8", "accent_hover": "#4f55d2", "line": "#e4e8ef",
    "own": "#5359db", "green": "#43a877", "red": "#bd4f59",
}


class DesktopChatApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Local Chat")
        self.root.geometry("1020x700")
        self.root.minsize(760, 540)
        self.root.configure(bg=COLORS["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.style = ttk.Style(self.root)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self.host_server: ChatServer | None = None
        self.discovery: DiscoveryResponder | None = None
        self.client: ChatClient | None = None
        self.servers: list[dict] = []
        self.selected_server: dict | None = None
        self.client_id = ""
        self.recipient_ids: dict[str, str] = {}
        self.pending_file_offers: dict[str, dict] = {}
        self.incoming_files: dict[str, dict] = {}
        self.root.after(150, self.scan_rooms)

    def run(self) -> None:
        self.root.mainloop()

    def _clear(self) -> None:
        for widget in self.root.winfo_children():
            widget.destroy()

    def _safe_after(self, callback, *args) -> None:
        try:
            self.root.after(0, callback, *args)
        except tk.TclError:
            pass

    def _button(self, parent, text: str, command, primary: bool = False, **kwargs) -> tk.Button:
        bg = COLORS["accent"] if primary else "#eef0f7"
        fg = "white" if primary else COLORS["ink"]
        hover = COLORS["accent_hover"] if primary else "#e2e6f0"
        return tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                         activebackground=hover, activeforeground=fg,
                         relief="flat", bd=0, padx=18, pady=10,
                         font=("Segoe UI", 10, "bold"), cursor="hand2", **kwargs)

    def _header(self, parent, title: str, subtitle: str) -> None:
        header = tk.Frame(parent, bg=COLORS["bg"])
        header.pack(fill="x", padx=36, pady=(28, 18))
        mark = tk.Label(header, text="L", bg=COLORS["accent"], fg="white",
                        font=("Segoe UI", 18, "bold"), width=2, height=1, padx=3, pady=3)
        mark.pack(side="left", padx=(0, 13))
        text = tk.Frame(header, bg=COLORS["bg"])
        text.pack(side="left", anchor="w")
        tk.Label(text, text=title, bg=COLORS["bg"], fg=COLORS["ink"],
                 font=("Segoe UI", 20, "bold")).pack(anchor="w")
        tk.Label(text, text=subtitle, bg=COLORS["bg"], fg=COLORS["muted"],
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(3, 0))

    def scan_rooms(self) -> None:
        self._clear()
        shell = tk.Frame(self.root, bg=COLORS["bg"])
        shell.pack(fill="both", expand=True)
        self._header(shell, "Local Chat", "Private real-time chat for your Wi-Fi or LAN")
        card = tk.Frame(shell, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
        card.pack(fill="both", expand=True, padx=36, pady=(0, 32))
        top = tk.Frame(card, bg=COLORS["panel"])
        top.pack(fill="x", padx=24, pady=(22, 12))
        tk.Label(top, text="Rooms on your network", bg=COLORS["panel"], fg=COLORS["ink"],
                 font=("Segoe UI", 14, "bold")).pack(side="left")
        self.scan_status = tk.Label(top, text="Searching…", bg=COLORS["panel"], fg=COLORS["muted"],
                                    font=("Segoe UI", 9))
        self.scan_status.pack(side="right")
        self.room_list = tk.Frame(card, bg=COLORS["panel"])
        self.room_list.pack(fill="both", expand=True, padx=24, pady=12)
        footer = tk.Frame(card, bg=COLORS["panel"])
        footer.pack(fill="x", padx=24, pady=(8, 22))
        self.scan_footer = footer
        self.host_button = self._button(footer, "Create a room", self.show_host_form)
        self.host_button.pack(side="left")
        self.retry_button = self._button(footer, "Scan again", self.scan_rooms, primary=True)
        self.retry_button.pack(side="right")
        self._show_loading()
        threading.Thread(target=self._scan_worker, daemon=True, name="room-scan").start()

    def _show_loading(self) -> None:
        for child in self.room_list.winfo_children():
            child.destroy()
        tk.Label(self.room_list, text="Looking for a running room on this local network…",
                 bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 11)).pack(pady=25)
        self.host_button.configure(state="disabled")
        self.retry_button.configure(state="disabled")

    def _scan_worker(self) -> None:
        try:
            rooms = discover_servers(timeout=1.5)
            error = None
        except OSError as exc:
            rooms, error = [], str(exc)
        self._safe_after(self._show_rooms, rooms, error)

    def _show_rooms(self, rooms: list[dict], error: str | None) -> None:
        self.servers = rooms
        for child in self.room_list.winfo_children():
            child.destroy()
        self.host_button.configure(state="normal")
        self.retry_button.configure(state="normal")
        if error:
            self.scan_status.configure(text="Discovery unavailable")
            tk.Label(self.room_list, text=f"LAN discovery could not run: {error}\nYou can still host a room or join one by scanning again.",
                     bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 10), justify="left").pack(anchor="w", pady=18)
            return
        if not rooms:
            self.scan_status.configure(text="No rooms found")
            tk.Label(self.room_list, text="No active chat room found on the local network.\nCreate one here, or scan again if a host is starting.",
                     bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 11), justify="left").pack(anchor="w", pady=18)
            return
        self.scan_status.configure(text=f"{len(rooms)} room{'s' if len(rooms) != 1 else ''} found")
        self.room_var = tk.IntVar(value=0)
        for index, room in enumerate(rooms):
            row = tk.Frame(self.room_list, bg="#fafbfe", highlightbackground=COLORS["line"], highlightthickness=1)
            row.pack(fill="x", pady=5)
            tk.Radiobutton(row, variable=self.room_var, value=index, bg="#fafbfe", activebackground="#fafbfe",
                           selectcolor=COLORS["accent"], command=lambda i=index: self._set_selected(i)).pack(side="left", padx=(12, 6), pady=12)
            labels = tk.Frame(row, bg="#fafbfe")
            labels.pack(side="left", fill="x", expand=True, pady=10)
            tk.Label(labels, text=room["room"], bg="#fafbfe", fg=COLORS["ink"],
                     font=("Segoe UI", 11, "bold")).pack(anchor="w")
            tk.Label(labels, text=f"{room['hostname']}  ·  {room['host']}:{room['port']}", bg="#fafbfe",
                     fg=COLORS["muted"], font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 0))
        self.selected_server = rooms[0]
        footer_button = self._button(self.scan_footer, "Join selected room", self.show_join_form, primary=True)
        footer_button.pack(side="right", padx=(0, 10))

    def _set_selected(self, index: int) -> None:
        if 0 <= index < len(self.servers):
            self.selected_server = self.servers[index]

    def show_host_form(self) -> None:
        self._clear()
        shell = tk.Frame(self.root, bg=COLORS["bg"])
        shell.pack(fill="both", expand=True)
        self._header(shell, "Create a room", "This device will host the chat for your local network")
        card = tk.Frame(shell, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
        card.place(relx=0.5, rely=0.56, anchor="center", width=500, height=300)
        tk.Label(card, text="Room name", bg=COLORS["panel"], fg=COLORS["ink"],
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=28, pady=(32, 8))
        self.room_name_entry = tk.Entry(card, font=("Segoe UI", 12), relief="solid", bd=1)
        self.room_name_entry.insert(0, "LAN Chat Room")
        self.room_name_entry.pack(fill="x", padx=28, ipady=10)
        tk.Label(card, text="The app will host this room and automatically connect you.",
                 bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 9)).pack(anchor="w", padx=28, pady=(11, 22))
        self.host_progress = tk.Label(card, text="", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 9))
        self.host_progress.pack(anchor="w", padx=28)
        buttons = tk.Frame(card, bg=COLORS["panel"])
        buttons.pack(fill="x", padx=28, pady=(15, 20))
        self._button(buttons, "Back", self.scan_rooms).pack(side="left")
        self._button(buttons, "Create and join", self.create_host, primary=True).pack(side="right")
        self.room_name_entry.focus_set()
        self.room_name_entry.bind("<Return>", lambda _event: self.create_host())

    def create_host(self) -> None:
        room_name = self.room_name_entry.get().strip()[:80] or "LAN Chat Room"
        self.host_progress.configure(text="Starting the local room…")
        for button in self.root.winfo_children()[0].winfo_children()[-1].winfo_children():
            if isinstance(button, tk.Button):
                button.configure(state="disabled")
        threading.Thread(target=self._host_worker, args=(room_name,), daemon=True, name="room-host-start").start()

    def _host_worker(self, room_name: str) -> None:
        server = None
        responder = None
        try:
            server = ChatServer(room_name)
            server.start()
            responder = DiscoveryResponder(server.port, server.room_name)
            responder.start()
            self._safe_after(self._host_ready, server, responder)
        except Exception as exc:
            if responder:
                responder.stop()
            if server:
                server.stop()
            error_message = str(exc)
            self._safe_after(lambda error=error_message: messagebox.showerror("Could not start room", error, parent=self.root))
            self._safe_after(self.show_host_form)

    def _host_ready(self, server: ChatServer, responder: DiscoveryResponder) -> None:
        self.host_server = server
        self.discovery = responder
        self.selected_server = {"host": "127.0.0.1", "port": server.port, "room": server.room_name,
                                "hostname": "This device"}
        self.show_join_form()

    def show_join_form(self) -> None:
        if not self.selected_server:
            return
        room = self.selected_server
        self._clear()
        shell = tk.Frame(self.root, bg=COLORS["bg"])
        shell.pack(fill="both", expand=True)
        self._header(shell, "Join room", f"{room['room']}  ·  {room['host']}:{room['port']}")
        card = tk.Frame(shell, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
        card.place(relx=0.5, rely=0.56, anchor="center", width=500, height=300)
        tk.Label(card, text="Choose your display name", bg=COLORS["panel"], fg=COLORS["ink"],
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=28, pady=(32, 8))
        self.username_entry = tk.Entry(card, font=("Segoe UI", 12), relief="solid", bd=1)
        self.username_entry.pack(fill="x", padx=28, ipady=10)
        tk.Label(card, text="This name is visible to everyone in the room.", bg=COLORS["panel"],
                 fg=COLORS["muted"], font=("Segoe UI", 9)).pack(anchor="w", padx=28, pady=(11, 25))
        buttons = tk.Frame(card, bg=COLORS["panel"])
        buttons.pack(fill="x", padx=28)
        back_action = self.scan_rooms if self.host_server is None else lambda: self.show_chat(room, "Host")
        back_text = "Back" if self.host_server is None else "Join as Host"
        self._button(buttons, back_text, back_action).pack(side="left")
        self._button(buttons, "Join chat", self.join_selected, primary=True).pack(side="right")
        self.username_entry.focus_set()
        self.username_entry.bind("<Return>", lambda _event: self.join_selected())

    def join_selected(self) -> None:
        if not self.selected_server:
            return
        username = self.username_entry.get().strip()[:24] or "Guest"
        room = self.selected_server
        self.show_chat(room, username)

    def show_chat(self, room: dict, username: str) -> None:
        self._clear()
        root_frame = tk.Frame(self.root, bg=COLORS["panel"])
        root_frame.pack(fill="both", expand=True)
        sidebar = tk.Frame(root_frame, bg=COLORS["sidebar"], width=250)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        brand = tk.Frame(sidebar, bg=COLORS["sidebar"])
        brand.pack(fill="x", padx=19, pady=(22, 24))
        tk.Label(brand, text="L", bg=COLORS["accent"], fg="white", width=2, height=1,
                 font=("Segoe UI", 16, "bold"), padx=3, pady=3).pack(side="left", padx=(0, 10))
        brand_labels = tk.Frame(brand, bg=COLORS["sidebar"])
        brand_labels.pack(side="left")
        tk.Label(brand_labels, text="Local Chat", bg=COLORS["sidebar"], fg="white",
                 font=("Segoe UI", 12, "bold")).pack(anchor="w")
        tk.Label(brand_labels, text="PRIVATE LAN ROOM", bg=COLORS["sidebar"], fg="#aeb7cf",
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(3, 0))
        tk.Label(sidebar, text="CURRENT ROOM", bg=COLORS["sidebar"], fg="#aeb7cf",
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=20, pady=(0, 8))
        tk.Label(sidebar, text=room["room"], bg="#303b5b", fg="white", anchor="w",
                 wraplength=205, padx=12, pady=12, font=("Segoe UI", 10, "bold")).pack(fill="x", padx=14)
        user_heading = tk.Frame(sidebar, bg=COLORS["sidebar"])
        user_heading.pack(fill="x", padx=20, pady=(25, 8))
        tk.Label(user_heading, text="ONLINE MEMBERS", bg=COLORS["sidebar"], fg="#aeb7cf",
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        self.user_count = tk.Label(user_heading, text="0", bg="#3d4770", fg="white",
                                   font=("Segoe UI", 8, "bold"), padx=7, pady=3)
        self.user_count.pack(side="right")
        self.users_frame = tk.Frame(sidebar, bg=COLORS["sidebar"])
        self.users_frame.pack(fill="x", padx=12)
        note = "Messages stay in memory on the host while it is running."
        if self.host_server:
            note = f"Hosting at {get_local_ipv4()}:{self.host_server.port}\n\n{note}"
        self.host_note = tk.Label(sidebar, text=note,
                                  bg=COLORS["sidebar"], fg="#aeb7cf", justify="left", wraplength=210,
                                  font=("Segoe UI", 8))
        self.host_note.pack(side="bottom", anchor="w", padx=19, pady=16)

        main = tk.Frame(root_frame, bg=COLORS["panel"])
        main.pack(side="left", fill="both", expand=True)
        header = tk.Frame(main, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
        header.pack(fill="x")
        title_box = tk.Frame(header, bg=COLORS["panel"])
        title_box.pack(side="left", padx=23, pady=16)
        tk.Label(title_box, text="Room conversation", bg=COLORS["panel"], fg=COLORS["ink"],
                 font=("Segoe UI", 12, "bold")).pack(anchor="w")
        tk.Label(title_box, text="Real-time chat on your Wi-Fi or LAN", bg=COLORS["panel"],
                 fg=COLORS["muted"], font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 0))
        self.connection_label = tk.Label(header, text="Connecting…", bg="#fff4dc", fg="#996d13",
                                         font=("Segoe UI", 9, "bold"), padx=10, pady=6)
        self.connection_label.pack(side="right", padx=20)
        feed_frame = tk.Frame(main, bg=COLORS["panel"])
        feed_frame.pack(fill="both", expand=True, padx=20, pady=15)
        self.feed = tk.Text(feed_frame, state="disabled", wrap="word", relief="flat", bd=0,
                            bg=COLORS["panel"], fg=COLORS["ink"], font=("Segoe UI", 10),
                            padx=10, pady=10, spacing1=2, spacing3=6)
        scroll = ttk.Scrollbar(feed_frame, command=self.feed.yview)
        self.feed.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.feed.pack(side="left", fill="both", expand=True)
        self.feed.tag_configure("own_label", foreground=COLORS["own"], justify="right", font=("Segoe UI", 9, "bold"))
        self.feed.tag_configure("other_label", foreground="#596579", font=("Segoe UI", 9, "bold"))
        self.feed.tag_configure("own_body", foreground=COLORS["own"], justify="right")
        self.feed.tag_configure("system", foreground=COLORS["muted"], justify="center", font=("Segoe UI", 9, "italic"))
        self.feed.tag_configure("error", foreground=COLORS["red"], justify="center")
        transfer_bar = tk.Frame(main, bg=COLORS["panel"])
        transfer_bar.pack(fill="x", padx=18, pady=(0, 8))
        tk.Label(transfer_bar, text="Send file to", bg=COLORS["panel"], fg=COLORS["muted"],
                 font=("Segoe UI", 9)).pack(side="left", padx=(2, 8))
        self.recipient_combo = ttk.Combobox(transfer_bar, state="readonly", width=24)
        self.recipient_combo.pack(side="left")
        self.file_button = self._button(transfer_bar, "Choose file…", self._choose_file)
        self.file_button.pack(side="left", padx=(8, 0))
        composer_area = tk.Frame(main, bg="#f8f9fc", highlightbackground=COLORS["line"], highlightthickness=1)
        composer_area.pack(fill="x", padx=18, pady=(0, 18))
        composer = tk.Frame(composer_area, bg="#f8f9fc")
        composer.pack(fill="x", padx=10, pady=9)
        self.message_entry = tk.Entry(composer, relief="flat", bg="#f8f9fc", fg=COLORS["ink"],
                                      font=("Segoe UI", 10), insertbackground=COLORS["ink"])
        self.message_entry.pack(side="left", fill="x", expand=True, padx=(7, 10), ipady=9)
        self.message_entry.insert(0, "Write a message…")
        self.message_entry.configure(fg="#9aa3b1")
        self.message_entry.bind("<FocusIn>", self._clear_placeholder)
        self.message_entry.bind("<Return>", self._send_message)
        self._button(composer, "Send", self._send_message, primary=True).pack(side="right")

        self.client = ChatClient(room["host"], room["port"], username,
                                 lambda data: self._safe_after(self._handle_event, data),
                                 lambda state: self._safe_after(self._set_connection, state))
        self.client.start()

    def _clear_placeholder(self, _event=None) -> None:
        if self.message_entry.get() == "Write a message…":
            self.message_entry.delete(0, "end")
            self.message_entry.configure(fg=COLORS["ink"])

    def _send_message(self, _event=None):
        text = self.message_entry.get().strip()
        if not text or text == "Write a message…":
            return "break"
        if self.client and self.client.send_message(text):
            self.message_entry.delete(0, "end")
        else:
            self._append_event({"type": "error", "text": "Not connected yet. Your message was not sent."})
        self.message_entry.focus_set()
        return "break"

    def _set_connection(self, state: str) -> None:
        if not hasattr(self, "connection_label") or not self.connection_label.winfo_exists():
            return
        self.connection_label.configure(text=state)
        if state == "Connected":
            self.connection_label.configure(bg="#e7f6ee", fg="#258453")
        elif state == "Disconnected":
            self.connection_label.configure(bg="#fdeced", fg=COLORS["red"])
        else:
            self.connection_label.configure(bg="#fff4dc", fg="#996d13")

    def _handle_event(self, data: dict) -> None:
        kind = data.get("type")
        if kind == "welcome":
            self.client_id = data.get("client_id", "")
            self._set_connection("Connected")
        elif kind == "history_start":
            self.feed.configure(state="normal")
            self.feed.delete("1.0", "end")
            self.feed.configure(state="disabled")
            self.history_count = data.get("count", 0)
        elif kind == "history_item":
            self._append_event(data.get("message", {}))
        elif kind == "history_end":
            if not getattr(self, "history_count", 0):
                self._append_event({"type": "system", "text": "You’re in. Say hello and start the conversation."})
        elif kind == "users":
            self._render_users(data.get("users", []))
        elif kind == "file_offer":
            self._handle_file_offer(data)
        elif kind == "file_accepted":
            transfer = self.pending_file_offers.get(data.get("transfer_id"))
            if transfer:
                transfer["accepted"] = True
                transfer["response"].set()
                self._append_event({"type": "system", "text": f"{data.get('username', 'Recipient')} accepted the file. Sending…"})
        elif kind == "file_rejected":
            transfer = self.pending_file_offers.get(data.get("transfer_id"))
            if transfer:
                transfer["accepted"] = False
                transfer["response"].set()
            self._append_event({"type": "system", "text": f"{data.get('username', 'Recipient')} declined the file."})
        elif kind == "file_chunk":
            self._handle_file_chunk(data)
        elif kind == "file_complete":
            self._finish_incoming_file(data)
        elif kind == "file_sent":
            self._append_event({"type": "system", "text": f"File sent to {data.get('username', 'recipient')}."})
        elif kind == "file_cancelled":
            self._discard_incoming_file(data.get("transfer_id"))
            transfer = self.pending_file_offers.pop(data.get("transfer_id"), None)
            if transfer:
                transfer["accepted"] = False
                transfer["response"].set()
            self._append_event({"type": "error", "text": data.get("text", "File transfer was cancelled.")})
        else:
            self._append_event(data)

    def _choose_file(self) -> None:
        if not self.client:
            return
        recipient_label = self.recipient_combo.get()
        recipient_id = self.recipient_ids.get(recipient_label)
        if not recipient_id:
            messagebox.showinfo("Choose a recipient", "Select an online person to receive the file.", parent=self.root)
            return
        path = filedialog.askopenfilename(parent=self.root, title="Choose a file to send")
        if not path:
            return
        try:
            size = os.path.getsize(path)
        except OSError as exc:
            messagebox.showerror("Could not read file", str(exc), parent=self.root)
            return
        if size > MAX_FILE_SIZE:
            messagebox.showerror(
                "File is too large",
                f"Choose a file no larger than {MAX_FILE_SIZE // (1024 * 1024)} MB.",
                parent=self.root,
            )
            return
        transfer_id = uuid.uuid4().hex
        response = threading.Event()
        transfer = {"response": response, "accepted": None}
        self.pending_file_offers[transfer_id] = transfer
        offer = {
            "type": "file_offer", "transfer_id": transfer_id,
            "recipient_id": recipient_id, "filename": os.path.basename(path),
            "size": size,
        }
        if not self.client.send_event(offer):
            self.pending_file_offers.pop(transfer_id, None)
            self._append_event({"type": "error", "text": "Not connected. The file offer was not sent."})
            return
        self._append_event({"type": "system", "text": f"Waiting for {recipient_label} to accept the file…"})
        threading.Thread(
            target=self._send_file_worker,
            args=(transfer_id, path, size, response, transfer),
            daemon=True,
            name="file-transfer",
        ).start()

    def _send_file_worker(self, transfer_id: str, path: str, size: int,
                          response: threading.Event, transfer: dict) -> None:
        if not response.wait(timeout=120):
            if self.client:
                self.client.send_event({"type": "file_cancel", "transfer_id": transfer_id})
            self._safe_after(self._append_event, {
                "type": "error", "text": "No response to the file offer; transfer cancelled."
            })
            self._safe_after(self.pending_file_offers.pop, transfer_id, None)
            return
        if not transfer["accepted"]:
            self._safe_after(self.pending_file_offers.pop, transfer_id, None)
            return
        try:
            sent = 0
            with open(path, "rb") as file:
                index = 0
                while chunk := file.read(FILE_CHUNK_SIZE):
                    if not self.client or not self.client.send_event({
                        "type": "file_chunk", "transfer_id": transfer_id,
                        "index": index, "data": base64.b64encode(chunk).decode("ascii"),
                    }):
                        raise OSError("Connection lost while sending the file.")
                    sent += len(chunk)
                    index += 1
            if sent != size or not self.client or not self.client.send_event({
                "type": "file_complete", "transfer_id": transfer_id,
            }):
                raise OSError("The file changed or the connection was lost during transfer.")
        except OSError as exc:
            if self.client:
                self.client.send_event({"type": "file_cancel", "transfer_id": transfer_id})
            self._safe_after(self._append_event, {"type": "error", "text": f"Could not send file: {exc}"})
        finally:
            self._safe_after(self.pending_file_offers.pop, transfer_id, None)

    def _handle_file_offer(self, data: dict) -> None:
        transfer_id = data.get("transfer_id")
        filename = data.get("filename", "file")
        username = data.get("username", "Someone")
        size = data.get("size", 0)
        allowed = messagebox.askyesno(
            "Incoming file",
            f"{username} wants to send you “{filename}” ({size:,} bytes).\n\nAllow this transfer?",
            parent=self.root,
        )
        destination = ""
        if allowed:
            destination = filedialog.asksaveasfilename(
                parent=self.root, title="Save incoming file", initialfile=filename,
            )
            allowed = bool(destination)
        if not self.client:
            return
        if not allowed:
            self.client.send_event({
                "type": "file_response", "transfer_id": transfer_id, "accepted": False,
            })
            self._append_event({"type": "system", "text": f"Declined the file from {username}."})
            return
        try:
            stream = tempfile.NamedTemporaryFile(
                mode="wb", prefix=".local-chat-", suffix=".part",
                dir=os.path.dirname(destination) or ".", delete=False,
            )
        except OSError as exc:
            self.client.send_event({
                "type": "file_response", "transfer_id": transfer_id, "accepted": False,
            })
            self._append_event({"type": "error", "text": f"Could not create a file for saving: {exc}"})
            return
        self.incoming_files[transfer_id] = {
            "stream": stream, "temp_path": stream.name, "destination": destination,
            "size": size, "received": 0, "next_index": 0,
        }
        if not self.client.send_event({
            "type": "file_response", "transfer_id": transfer_id, "accepted": True,
        }):
            self._discard_incoming_file(transfer_id)
            self._append_event({"type": "error", "text": "Not connected. The file was not accepted."})
            return
        self._append_event({"type": "system", "text": f"Accepted a file from {username}; receiving…"})

    def _handle_file_chunk(self, data: dict) -> None:
        transfer_id = data.get("transfer_id")
        transfer = self.incoming_files.get(transfer_id)
        try:
            chunk = base64.b64decode(data.get("data", ""), validate=True)
            index = data.get("index")
            if (transfer is None or not isinstance(index, int) or isinstance(index, bool)
                    or index != transfer["next_index"]
                    or not chunk or len(chunk) > FILE_CHUNK_SIZE
                    or transfer["received"] + len(chunk) > transfer["size"]):
                raise ValueError("Invalid file data received.")
            transfer["stream"].write(chunk)
            transfer["received"] += len(chunk)
            transfer["next_index"] += 1
        except (TypeError, ValueError, OSError) as exc:
            self._discard_incoming_file(transfer_id)
            if self.client:
                self.client.send_event({"type": "file_cancel", "transfer_id": transfer_id})
            self._append_event({"type": "error", "text": f"File reception failed: {exc}"})

    def _finish_incoming_file(self, data: dict) -> None:
        transfer_id = data.get("transfer_id")
        transfer = self.incoming_files.pop(transfer_id, None)
        if transfer is None:
            return
        try:
            if transfer["received"] != transfer["size"]:
                raise OSError("The received file size did not match the offer.")
            transfer["stream"].close()
            os.replace(transfer["temp_path"], transfer["destination"])
        except OSError as exc:
            self._discard_incoming_file(transfer_id, transfer)
            self._append_event({"type": "error", "text": f"Could not finish saving the file: {exc}"})
            return
        self._append_event({"type": "system", "text": f"File received and saved to {transfer['destination']}."})

    def _discard_incoming_file(self, transfer_id: str, transfer: dict | None = None) -> None:
        incoming = transfer or self.incoming_files.pop(transfer_id, None)
        if not incoming:
            return
        try:
            incoming["stream"].close()
        except OSError:
            pass
        try:
            os.remove(incoming["temp_path"])
        except FileNotFoundError:
            pass
        except OSError as exc:
            self._append_event({"type": "error", "text": f"Could not remove incomplete file: {exc}"})

    def _append_event(self, data: dict) -> None:
        if not hasattr(self, "feed") or not self.feed.winfo_exists():
            return
        kind = data.get("type")
        self.feed.configure(state="normal")
        if kind == "message":
            own = data.get("sender_id") == self.client_id
            label = "You" if own else data.get("username", "Guest")
            stamp = data.get("time", "")
            if stamp:
                stamp = stamp[11:16]
            self.feed.insert("end", f"{label}  ·  {stamp}\n", "own_label" if own else "other_label")
            self.feed.insert("end", f"{data.get('text', '')}\n\n", "own_body" if own else "")
        elif kind == "system":
            self.feed.insert("end", f"{data.get('text', '')}\n\n", "system")
        elif kind == "error":
            self.feed.insert("end", f"{data.get('text', 'Chat error')}\n\n", "error")
        self.feed.configure(state="disabled")
        self.feed.see("end")

    def _render_users(self, users: list[dict]) -> None:
        if not hasattr(self, "users_frame") or not self.users_frame.winfo_exists():
            return
        for child in self.users_frame.winfo_children():
            child.destroy()
        self.user_count.configure(text=str(len(users)))
        choices: dict[str, str] = {}
        for user in users:
            row = tk.Frame(self.users_frame, bg=COLORS["sidebar"])
            row.pack(fill="x", pady=3)
            initial = (user.get("username") or "?")[0].upper()
            tk.Label(row, text=initial, bg="#3d4770", fg="white", width=2, height=1,
                     font=("Segoe UI", 9, "bold"), padx=2, pady=3).pack(side="left", padx=(4, 9))
            label = user.get("username", "Guest")
            if user.get("id") == self.client_id:
                label += " (you)"
            else:
                choice = f"{label} · {user.get('id', '')[:6]}"
                choices[choice] = user.get("id", "")
            tk.Label(row, text=label, bg=COLORS["sidebar"], fg=COLORS["sidebar_text"],
                     font=("Segoe UI", 9), anchor="w").pack(side="left", fill="x", expand=True)
            tk.Label(row, text="●", bg=COLORS["sidebar"], fg=COLORS["green"],
                     font=("Segoe UI", 8)).pack(side="right", padx=5)
        self.recipient_ids = choices
        if hasattr(self, "recipient_combo") and self.recipient_combo.winfo_exists():
            previous = self.recipient_combo.get()
            self.recipient_combo.configure(values=list(choices))
            if previous in choices:
                self.recipient_combo.set(previous)
            elif choices:
                self.recipient_combo.current(0)
            else:
                self.recipient_combo.set("")

    def close(self) -> None:
        for transfer in self.pending_file_offers.values():
            transfer["accepted"] = False
            transfer["response"].set()
        if self.client:
            self.client.stop()
        for transfer_id in list(self.incoming_files):
            self._discard_incoming_file(transfer_id)
        if self.discovery:
            self.discovery.stop()
        if self.host_server:
            self.host_server.stop()
        self.root.destroy()
