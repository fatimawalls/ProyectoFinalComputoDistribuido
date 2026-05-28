import tkinter as tk
import random
from tkinter import scrolledtext
from gui.user_profile import UserProfileWindow
from gui.mock_data import MockServer

# Nombres de salas para la simulación de creación
SIM_ROOM_NAMES = ["ops-team", "security", "backend", "qa-testing", "design", "infra", "alerts"]


class ChatClientGUI:
    def __init__(self, root, username="jperez_root", nickname="jperez.sys", network=None):
        self.root = root
        self.root.title("PIMENTEL CO. // WORKSPACE")
        self.root.geometry("1050x700")

        # --- PALETA ---
        self.BG_DARK       = "#0D0D0D"
        self.BG_MAIN       = "#141414"
        self.BG_SECONDARY  = "#1E1E1E"
        self.TEXT_MAIN     = "#E0E0E0"
        self.TEXT_MUTED    = "#6B6B6B"
        self.ACCENT        = "#2232E3"
        self.ACCENT_HOVER  = "#3A4BFF"
        self.ERROR_COLOR   = "#E32222"
        self.SUCCESS_COLOR = "#22E37A"
        self.WARNING_COLOR = "#E3A022"

        # --- TIPOGRAFÍA ---
        self.FONT_UI      = ("Segoe UI", 10)
        self.FONT_UI_BOLD = ("Segoe UI", 10, "bold")
        self.FONT_TITLE   = ("Segoe UI", 16, "bold")
        self.FONT_CODE    = ("Consolas", 11)
        self.FONT_LABEL   = ("Segoe UI", 9, "bold")
        self.FONT_SMALL   = ("Segoe UI", 9)

        # --- SESIÓN ---
        self.username      = username
        self.nickname      = nickname
        self.current_room  = None
        self.chat_history  = None
        self.pending_rooms = set()
        self.active_toasts = []
        self.sim_left      = {}   # {room_id: set de nicknames que salieron en simulación}

        # MockServer simula el backend (fallback cuando no hay red real)
        self.mock    = MockServer(current_user=username, current_nick=nickname)
        self.network = network   # puede ser None; AppController también lo inyecta post-init

        self.root.configure(bg=self.BG_MAIN)
        self.build_ui()

        # Iniciar simulaciones solo si NO hay red real.
        # Si hay red real, AppController conecta self.network ANTES de que estos
        # timers disparen, así que la primera llamada verá self.network y no hará nada.
        self._simulate_incoming_messages()
        self._simulate_user_leave()
        self._simulate_room_creation()

    # ─────────────────────────────────────────────
    #  CUSTOM DIALOGS
    # ─────────────────────────────────────────────

    def confirm_dialog(self, title, message, parent=None):
        result = {"value": False}
        win    = parent or self.root

        dialog = tk.Toplevel(win)
        dialog.title("")
        dialog.resizable(False, False)
        dialog.configure(bg=self.BG_MAIN)
        dialog.transient(win)
        dialog.grab_set()
        dialog.focus_force()

        dialog.update_idletasks()
        dw, dh = 380, 170
        x = win.winfo_x() + (win.winfo_width()  - dw) // 2
        y = win.winfo_y() + (win.winfo_height() - dh) // 2
        dialog.geometry(f"{dw}x{dh}+{x}+{y}")

        tk.Frame(dialog, bg=self.ACCENT, height=3).pack(fill="x")
        body = tk.Frame(dialog, bg=self.BG_MAIN, padx=30, pady=20)
        body.pack(fill="both", expand=True)

        tk.Label(body, text=title, font=self.FONT_UI_BOLD,
                 bg=self.BG_MAIN, fg=self.TEXT_MAIN, anchor="w").pack(fill="x")
        tk.Label(body, text=message, font=self.FONT_SMALL,
                 bg=self.BG_MAIN, fg=self.TEXT_MUTED, anchor="w",
                 wraplength=320, justify="left").pack(fill="x", pady=(8, 20))

        btn_frame = tk.Frame(body, bg=self.BG_MAIN)
        btn_frame.pack(fill="x")

        def on_cancel():
            result["value"] = False
            dialog.destroy()

        def on_confirm():
            result["value"] = True
            dialog.destroy()

        btn_cancel = tk.Label(btn_frame, text="CANCEL", font=self.FONT_LABEL,
                              bg=self.BG_SECONDARY, fg=self.TEXT_MAIN,
                              cursor="hand2", padx=20, pady=8)
        btn_cancel.pack(side="left")
        btn_cancel.bind("<Button-1>", lambda e: on_cancel())
        btn_cancel.bind("<Enter>",    lambda e: btn_cancel.config(bg="#252525"))
        btn_cancel.bind("<Leave>",    lambda e: btn_cancel.config(bg=self.BG_SECONDARY))

        btn_ok = tk.Label(btn_frame, text="CONFIRM", font=self.FONT_LABEL,
                          bg=self.ACCENT, fg="#FFFFFF", cursor="hand2", padx=20, pady=8)
        btn_ok.pack(side="right")
        btn_ok.bind("<Button-1>", lambda e: on_confirm())
        btn_ok.bind("<Enter>",    lambda e: btn_ok.config(bg=self.ACCENT_HOVER))
        btn_ok.bind("<Leave>",    lambda e: btn_ok.config(bg=self.ACCENT))

        dialog.bind("<Escape>", lambda e: on_cancel())
        dialog.bind("<Return>", lambda e: on_confirm())
        dialog.wait_window()
        return result["value"]

    def info_dialog(self, title, message, parent=None, color=None):
        win   = parent or self.root
        color = color or self.ACCENT

        dialog = tk.Toplevel(win)
        dialog.title("")
        dialog.resizable(False, False)
        dialog.configure(bg=self.BG_MAIN)
        dialog.transient(win)
        dialog.grab_set()
        dialog.focus_force()

        dialog.update_idletasks()
        dw, dh = 380, 150
        x = win.winfo_x() + (win.winfo_width()  - dw) // 2
        y = win.winfo_y() + (win.winfo_height() - dh) // 2
        dialog.geometry(f"{dw}x{dh}+{x}+{y}")

        tk.Frame(dialog, bg=color, height=3).pack(fill="x")
        body = tk.Frame(dialog, bg=self.BG_MAIN, padx=30, pady=20)
        body.pack(fill="both", expand=True)

        tk.Label(body, text=title, font=self.FONT_UI_BOLD,
                 bg=self.BG_MAIN, fg=self.TEXT_MAIN, anchor="w").pack(fill="x")
        tk.Label(body, text=message, font=self.FONT_SMALL,
                 bg=self.BG_MAIN, fg=self.TEXT_MUTED, anchor="w",
                 wraplength=320, justify="left").pack(fill="x", pady=(8, 20))

        btn_ok = tk.Label(body, text="OK", font=self.FONT_LABEL,
                          bg=color, fg="#FFFFFF", cursor="hand2", padx=20, pady=8)
        btn_ok.pack(side="right")
        btn_ok.bind("<Button-1>", lambda e: dialog.destroy())
        btn_ok.bind("<Enter>",    lambda e: btn_ok.config(bg=self.ACCENT_HOVER))
        btn_ok.bind("<Leave>",    lambda e: btn_ok.config(bg=color))

        dialog.bind("<Return>", lambda e: dialog.destroy())
        dialog.bind("<Escape>", lambda e: dialog.destroy())
        dialog.wait_window()

    # ─────────────────────────────────────────────
    #  BUILD UI
    # ─────────────────────────────────────────────

    def build_ui(self):
        # ── SIDEBAR ───────────────────────────────────────────────
        self.sidebar = tk.Frame(self.root, bg=self.BG_DARK, width=260)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Logo
        header_frame = tk.Frame(self.sidebar, bg=self.BG_DARK)
        header_frame.pack(fill="x", padx=25, pady=30)
        tk.Label(header_frame, text="PIMENTEL CO.", font=self.FONT_TITLE,
                 bg=self.BG_DARK, fg=self.TEXT_MAIN, anchor="w").pack(fill="x")
        tk.Frame(self.sidebar, bg=self.ACCENT, height=2).pack(fill="x", padx=25, pady=(0, 10))

        # ── PERFIL (bottom, fijo) ─────────────────────────────────
        self.user_panel = tk.Frame(self.sidebar, bg=self.BG_SECONDARY, cursor="hand2")
        self.user_panel.pack(side="bottom", fill="x", padx=15, pady=15)
        self.user_label = tk.Label(self.user_panel, text=f"● {self.nickname}",
                                   font=self.FONT_UI_BOLD, bg=self.BG_SECONDARY,
                                   fg=self.ACCENT, anchor="w", pady=10)
        self.user_label.pack(side="left", padx=15)
        self.user_panel.bind("<Button-1>", lambda e: self.open_profile())
        self.user_label.bind("<Button-1>", lambda e: self.open_profile())
        self.user_panel.bind("<Enter>", lambda e: self.user_panel.config(bg="#252525"))
        self.user_panel.bind("<Leave>", lambda e: self.user_panel.config(bg=self.BG_SECONDARY))

        # ── ÁREA SCROLLABLE (channels + users) ───────────────────
        scroll_container = tk.Frame(self.sidebar, bg=self.BG_DARK)
        scroll_container.pack(fill="both", expand=True)

        canvas = tk.Canvas(scroll_container, bg=self.BG_DARK,
                           highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(scroll_container, orient="vertical",
                                 command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._scroll_inner = tk.Frame(canvas, bg=self.BG_DARK)
        self._scroll_win   = canvas.create_window((0, 0), window=self._scroll_inner,
                                                   anchor="nw")

        def _on_frame_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_configure(e):
            canvas.itemconfig(self._scroll_win, width=e.width)

        self._scroll_inner.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        # Mouse wheel
        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # ── MY CHANNELS ──────────────────────────────────────────
        my_hdr = tk.Frame(self._scroll_inner, bg=self.BG_DARK)
        my_hdr.pack(fill="x", padx=15, pady=(12, 4))
        tk.Label(my_hdr, text="MY CHANNELS", font=self.FONT_LABEL,
                 bg=self.BG_DARK, fg=self.TEXT_MUTED, anchor="w").pack(side="left")
        btn_create = tk.Label(my_hdr, text="＋", font=self.FONT_UI_BOLD,
                              bg=self.BG_DARK, fg=self.ACCENT, cursor="hand2")
        btn_create.pack(side="right")
        btn_create.bind("<Button-1>", lambda e: self.open_create_room_dialog())
        btn_create.bind("<Enter>",    lambda e: btn_create.config(fg=self.ACCENT_HOVER))
        btn_create.bind("<Leave>",    lambda e: btn_create.config(fg=self.ACCENT))

        self.my_rooms_frame = tk.Frame(self._scroll_inner, bg=self.BG_DARK)
        self.my_rooms_frame.pack(fill="x", padx=8, pady=(0, 4))

        # ── OTHER CHANNELS ───────────────────────────────────────
        tk.Frame(self._scroll_inner, bg="#2A2A2A", height=1).pack(fill="x", padx=15, pady=(8, 0))
        other_hdr = tk.Frame(self._scroll_inner, bg=self.BG_DARK)
        other_hdr.pack(fill="x", padx=15, pady=(8, 4))
        tk.Label(other_hdr, text="OTHER CHANNELS", font=self.FONT_LABEL,
                 bg=self.BG_DARK, fg=self.TEXT_MUTED, anchor="w").pack(side="left")

        self.other_rooms_frame = tk.Frame(self._scroll_inner, bg=self.BG_DARK)
        self.other_rooms_frame.pack(fill="x", padx=8, pady=(0, 4))

        # ── USERS ────────────────────────────────────────────────
        tk.Frame(self._scroll_inner, bg="#2A2A2A", height=1).pack(fill="x", padx=15, pady=(8, 0))
        tk.Label(self._scroll_inner, text="CONNECTED USERS", font=self.FONT_LABEL,
                 bg=self.BG_DARK, fg=self.TEXT_MUTED, anchor="w").pack(fill="x", padx=15, pady=(8, 4))

        self.users_frame = tk.Frame(self._scroll_inner, bg=self.BG_DARK)
        self.users_frame.pack(fill="x", padx=8, pady=(0, 8))

        # Keep legacy attribute for compatibility
        self.channels_list = None

        # ── MAIN PANEL ───────────────────────────────────────────
        self.main_panel = tk.Frame(self.root, bg=self.BG_MAIN)
        self.main_panel.pack(side="right", fill="both", expand=True)

        self.refresh_sidebar()
        self.show_welcome_view()

    # ─────────────────────────────────────────────
    #  ADAPTADORES RED / MOCK
    #  Cuando self.network está disponible usa datos
    #  reales; si no, cae al MockServer.
    # ─────────────────────────────────────────────

    def _get_my_rooms(self):
        """Rooms a los que pertenece el usuario actual."""
        if self.network:
            return self.network.get_my_rooms()
        return self.mock.get_my_rooms()

    def _get_all_rooms(self):
        """Todos los rooms conocidos (para sidebar completa)."""
        if self.network:
            return list(self.network.rooms.values())
        return self.mock.get_rooms()

    def _get_room(self, room_id):
        if self.network:
            return self.network.rooms.get(room_id)
        return self.mock.get_room(room_id)

    def _get_messages(self, room_id):
        if self.network:
            return [
                (self._resolve_username(m["userId"]), m["text"])
                for m in self.network.messages.get(room_id, [])
            ]
        return self.mock.get_messages(room_id)

    def _resolve_username(self, user_id):
        """Convierte user_id (int) → nombre visible."""
        if self.network:
            u = self.network.users.get(user_id)
            if u:
                return u.get("name", str(user_id))
        return str(user_id)

    def _is_coordinator(self, room_id):
        if self.network:
            room = self.network.rooms.get(room_id)
            return room and room.get("coordinatorId") == self.network.me.get("id")
        return self.mock.is_coordinator(room_id)

    def _get_all_users(self):
        if self.network:
            my_id = self.network.me.get("id")
            return [
                {"username": str(u["id"]), "nickname": u.get("name", "?"), "online": True}
                for u in self.network.users.values()
                if u["id"] != my_id
            ]
        return self.mock.get_all_users()

    def _is_member(self, room_id):
        if self.network:
            room = self.network.rooms.get(room_id)
            my_id = self.network.me.get("id")
            return room and my_id in room.get("userIds", [])
        room = self.mock.get_room(room_id)
        return room and self.username in room.get("members", [])

    # ─────────────────────────────────────────────
    #  REFRESH SIDEBAR
    # ─────────────────────────────────────────────

    def refresh_sidebar(self):
        # ── MY ROOMS ─────────────────────────────────────────────
        for w in self.my_rooms_frame.winfo_children():
            w.destroy()

        my_rooms    = self._get_my_rooms()
        other_rooms = [r for r in self._get_all_rooms()
                       if r.get("id") not in {m.get("id") for m in my_rooms}]

        self._sidebar_rooms = my_rooms   # kept for legacy on_channel_select fallback

        if my_rooms:
            for room in my_rooms:
                self._make_room_row(self.my_rooms_frame, room, member=True)
        else:
            tk.Label(self.my_rooms_frame, text="  No channels yet.",
                     font=self.FONT_SMALL, bg=self.BG_DARK,
                     fg=self.TEXT_MUTED, anchor="w").pack(fill="x", padx=8, pady=4)

        # ── OTHER ROOMS ──────────────────────────────────────────
        for w in self.other_rooms_frame.winfo_children():
            w.destroy()

        if other_rooms:
            for room in other_rooms:
                self._make_room_row(self.other_rooms_frame, room, member=False)
        else:
            tk.Label(self.other_rooms_frame, text="  No other channels.",
                     font=self.FONT_SMALL, bg=self.BG_DARK,
                     fg=self.TEXT_MUTED, anchor="w").pack(fill="x", padx=8, pady=4)

        # ── USERS ────────────────────────────────────────────────
        for w in self.users_frame.winfo_children():
            w.destroy()

        users = self._get_all_users()
        if users:
            for user in users:
                row = tk.Frame(self.users_frame, bg=self.BG_DARK)
                row.pack(fill="x", pady=1)
                dot_color = self.SUCCESS_COLOR if user.get("online") else self.TEXT_MUTED
                tk.Label(row, text="●", font=("Segoe UI", 8),
                         bg=self.BG_DARK, fg=dot_color).pack(side="left", padx=(8, 4))
                tk.Label(row, text=user["nickname"], font=self.FONT_SMALL,
                         bg=self.BG_DARK, fg=self.TEXT_MAIN).pack(side="left")
        else:
            tk.Label(self.users_frame, text="  No other users online.",
                     font=self.FONT_SMALL, bg=self.BG_DARK,
                     fg=self.TEXT_MUTED, anchor="w").pack(fill="x", padx=8, pady=4)

    def _make_room_row(self, parent, room, member: bool):
        """Renders a single room row button in the sidebar."""
        room_id = room.get("id")
        notif   = room.get("notifications", 0)
        name    = room.get("name", str(room_id))

        is_active = (room_id == self.current_room)

        bg_normal  = "#1C2340" if member else self.BG_DARK
        bg_active  = self.ACCENT
        bg_hover   = "#252560" if member else "#222222"
        fg_normal  = self.TEXT_MAIN if member else self.TEXT_MUTED
        fg_active  = "#FFFFFF"

        bg = bg_active if is_active else bg_normal
        fg = fg_active if is_active else fg_normal

        row = tk.Frame(parent, bg=bg, cursor="hand2")
        row.pack(fill="x", pady=1)

        # hash prefix
        tk.Label(row, text="#", font=self.FONT_LABEL,
                 bg=bg, fg=self.ACCENT if not is_active else "#FFFFFF").pack(side="left", padx=(8, 2), pady=6)

        lbl = tk.Label(row, text=name, font=self.FONT_SMALL,
                       bg=bg, fg=fg, anchor="w")
        lbl.pack(side="left", fill="x", expand=True, pady=6)

        if notif > 0:
            badge = tk.Label(row, text=str(notif), font=("Segoe UI", 8, "bold"),
                             bg=self.ERROR_COLOR, fg="#FFFFFF", padx=5, pady=1)
            badge.pack(side="right", padx=6)

        # Click handler
        def _click(e, rid=room_id, is_mem=member):
            self.current_room = rid
            if is_mem:
                self.show_chat_view(rid)
                room["notifications"] = 0
            else:
                self.show_private_room_view(rid)
            self.refresh_sidebar()

        for widget in (row, lbl):
            widget.bind("<Button-1>", _click)
            widget.bind("<Enter>",    lambda e, r=row, bh=bg_hover, ba=bg_active, act=is_active:
                                          r.config(bg=bh if not act else ba))
            widget.bind("<Leave>",    lambda e, r=row, bn=bg_normal, ba=bg_active, act=is_active:
                                          r.config(bg=ba if act else bn))

    # ─────────────────────────────────────────────
    #  TOASTS
    # ─────────────────────────────────────────────

    def show_toast(self, room_id, room_name, sender, message):
        if len(self.active_toasts) >= 10:
            return

        toast = tk.Toplevel(self.root)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.configure(bg=self.BG_SECONDARY)

        self.root.update_idletasks()
        toast_w = 300
        toast_h = 80
        offset  = len(self.active_toasts) * (toast_h + 10)
        x = self.root.winfo_x() + self.root.winfo_width()  - toast_w - 20
        y = self.root.winfo_y() + self.root.winfo_height() - toast_h - 20 - offset
        toast.geometry(f"{toast_w}x{toast_h}+{x}+{y}")
        self.active_toasts.append(toast)

        tk.Frame(toast, bg=self.ACCENT, height=3).pack(fill="x")
        content = tk.Frame(toast, bg=self.BG_SECONDARY, padx=12, pady=8)
        content.pack(fill="both", expand=True)

        header = tk.Frame(content, bg=self.BG_SECONDARY)
        header.pack(fill="x")
        tk.Label(header, text=f"# {room_name}", font=self.FONT_UI_BOLD,
                 bg=self.BG_SECONDARY, fg=self.ACCENT).pack(side="left")
        btn_close = tk.Label(header, text="✕", font=self.FONT_SMALL,
                             bg=self.BG_SECONDARY, fg=self.TEXT_MUTED, cursor="hand2")
        btn_close.pack(side="right")
        btn_close.bind("<Button-1>", lambda e: self._close_toast(toast))

        preview = f"{sender}: {message}"
        if len(preview) > 38:
            preview = preview[:38] + "..."
        tk.Label(content, text=preview, font=self.FONT_SMALL,
                 bg=self.BG_SECONDARY, fg=self.TEXT_MAIN, anchor="w").pack(fill="x", pady=(4, 0))

        content.bind("<Button-1>", lambda e: self._toast_click(toast, room_id))
        for child in content.winfo_children():
            child.bind("<Button-1>", lambda e, rid=room_id: self._toast_click(toast, rid))
        content.bind("<Enter>", lambda e: content.config(bg="#252525"))
        content.bind("<Leave>", lambda e: content.config(bg=self.BG_SECONDARY))

        self.root.after(4000, lambda: self._close_toast(toast))

    def _close_toast(self, toast):
        if toast in self.active_toasts:
            self.active_toasts.remove(toast)
        try:
            toast.destroy()
        except tk.TclError:
            pass

    def _toast_click(self, toast, room_id):
        self._close_toast(toast)
        if self._is_member(room_id):
            self.current_room = room_id
            room = self._get_room(room_id)
            if room:
                room["notifications"] = 0
            self.show_chat_view(room_id)
            self.refresh_sidebar()

    # ─────────────────────────────────────────────
    #  SIMULACIONES
    # ─────────────────────────────────────────────

    def _simulate_incoming_messages(self):
        if self.network:   # red real → no simular
            return
        # AQUÍ IRÍA: el hilo de escucha real del NetworkClient
        my_rooms = self.mock.get_my_rooms()
        if my_rooms:
            room   = random.choice(my_rooms)
            left   = self.sim_left.get(room["id"], set())
            members = [n for n in self.mock.get_member_nicknames(room["id"]) if n not in left]

            if members:
                sender = random.choice(members)
                msgs   = ["Hey, anyone there?", "Check this out.", "Meeting in 5.",
                          "Server looks good.", "Deploy done.", "Need a review."]
                text   = random.choice(msgs)
                self.mock.messages.setdefault(room["id"], []).append((sender, text))

                if room["id"] == self.current_room:
                    if self.chat_history:
                        self.chat_history.config(state="normal")
                        self.chat_history.insert(tk.END, f"[{sender}] ", "user")
                        self.chat_history.insert(tk.END, f"{text}\n", "msg")
                        self.chat_history.config(state="disabled")
                        self.chat_history.yview(tk.END)
                else:
                    room["notifications"] += 1
                    self.refresh_sidebar()
                    self.show_toast(room["id"], room["name"], sender, text)

        self.root.after(12000, self._simulate_incoming_messages)

    def _simulate_user_leave(self):
        if self.network:
            return
        # AQUÍ IRÍA: el evento real del servidor vía NetworkClient
        my_rooms = self.mock.get_my_rooms()
        if my_rooms:
            room     = random.choice(my_rooms)
            left     = self.sim_left.get(room["id"], set())
            members  = [n for n in self.mock.get_member_nicknames(room["id"]) if n not in left]

            if members:
                leaver = random.choice(members)
                if room["id"] not in self.sim_left:
                    self.sim_left[room["id"]] = set()
                self.sim_left[room["id"]].add(leaver)

                msg = f"{leaver} has left the room."
                self.mock.messages.setdefault(room["id"], []).append(("__SYSTEM__", msg))

                # Quitar de members para que el coordinator panel lo refleje
                for u in self.mock.users:
                    if u["nickname"] == leaver and u["username"] in room["members"]:
                        room["members"].remove(u["username"])
                        break

                if room["id"] == self.current_room:
                    if self.chat_history:
                        self.chat_history.config(state="normal")
                        self.chat_history.insert(tk.END, f"◆ {msg}\n", "system")
                        self.chat_history.config(state="disabled")
                        self.chat_history.yview(tk.END)
                else:
                    room["notifications"] += 1
                    self.refresh_sidebar()
                    self.show_toast(room["id"], room["name"], "◆ System", f"{leaver} has left.")

        self.root.after(30000, self._simulate_user_leave)

    def _simulate_room_creation(self):
        if self.network:
            return
        # Simula que otro usuario crea una sala nueva
        # AQUÍ IRÍA: el servidor notificaría este evento a todos los clientes conectados
        existing_names = [r["name"] for r in self.mock.rooms]
        available      = [n for n in SIM_ROOM_NAMES if n not in existing_names]

        if available:
            name        = random.choice(available)
            other_users = [u for u in self.mock.users
                           if u["username"] != self.username and u["online"]]

            if other_users:
                creator  = random.choice(other_users)
                room_id  = name.lower().replace(" ", "-")
                new_room = {
                    "id":            room_id,
                    "name":          name,
                    "coordinator":   creator["username"],
                    "members":       [creator["username"]],
                    "notifications": 0,
                }
                self.mock.rooms.append(new_room)
                self.mock.messages[room_id] = []
                self.mock.requests[room_id] = []

                self.refresh_sidebar()

        self.root.after(45000, self._simulate_room_creation)

    # ─────────────────────────────────────────────
    #  VISTAS
    # ─────────────────────────────────────────────

    def clear_main_panel(self):
        self.chat_history = None
        for widget in self.main_panel.winfo_children():
            widget.destroy()

    def show_welcome_view(self):
        self.clear_main_panel()
        frame = tk.Frame(self.main_panel, bg=self.BG_MAIN)
        frame.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(frame, text="SECURE CONNECTION ESTABLISHED", font=self.FONT_UI_BOLD,
                 bg=self.BG_MAIN, fg=self.ACCENT).pack(pady=5)
        tk.Label(frame, text=f"Welcome, {self.nickname}.",
                 font=self.FONT_CODE, bg=self.BG_MAIN, fg=self.TEXT_MAIN).pack(pady=5)
        tk.Label(frame, text="Select a workspace channel to begin.",
                 font=self.FONT_UI, bg=self.BG_MAIN, fg=self.TEXT_MUTED).pack(pady=5)

    def show_private_room_view(self, room_id):
        self.clear_main_panel()
        self.current_room = room_id
        room       = self._get_room(room_id)
        is_pending = room_id in self.pending_rooms

        frame = tk.Frame(self.main_panel, bg=self.BG_MAIN)
        frame.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(frame, text=f"# {room['name']}", font=self.FONT_TITLE,
                 bg=self.BG_MAIN, fg=self.TEXT_MAIN).pack()
        tk.Label(frame, text="This channel is private.", font=self.FONT_CODE,
                 bg=self.BG_MAIN, fg=self.TEXT_MUTED).pack(pady=(8, 0))
        tk.Frame(frame, bg=self.BG_SECONDARY, height=1, width=300).pack(pady=25)

        if is_pending:
            tk.Label(frame, text="REQUEST PENDING", font=self.FONT_UI_BOLD,
                     bg=self.BG_MAIN, fg=self.WARNING_COLOR).pack(pady=5)
            tk.Label(frame, text="Waiting for the coordinator to accept your request.",
                     font=self.FONT_SMALL, bg=self.BG_MAIN, fg=self.TEXT_MUTED).pack()
        else:
            tk.Label(frame, text="You need coordinator approval to join this channel.",
                     font=self.FONT_SMALL, bg=self.BG_MAIN, fg=self.TEXT_MUTED).pack(pady=(0, 20))
            btn = tk.Label(frame, text="  REQUEST ACCESS →  ", font=self.FONT_UI_BOLD,
                           bg=self.ACCENT, fg="#FFFFFF", cursor="hand2")
            btn.pack(ipady=12, ipadx=10)
            btn.bind("<Button-1>", lambda e: self.request_join_from_view(room_id))
            btn.bind("<Enter>",    lambda e: btn.config(bg=self.ACCENT_HOVER))
            btn.bind("<Leave>",    lambda e: btn.config(bg=self.ACCENT))

    def show_chat_view(self, room_id):
        self.clear_main_panel()
        self.current_room = room_id
        room     = self._get_room(room_id)
        is_coord = self._is_coordinator(room_id)

        # CABECERA
        header = tk.Frame(self.main_panel, bg=self.BG_MAIN, pady=20)
        header.pack(fill="x", padx=30)

        tk.Label(header, text=f"# {room['name']}", font=self.FONT_TITLE,
                 bg=self.BG_MAIN, fg=self.TEXT_MAIN).pack(side="left")

        if is_coord:
            if self.network:
                room = self.network.rooms.get(room_id, {})
                requests_count = len(room.get("requestIds", []))
            else:
                requests_count = len(self.mock.get_join_requests(room_id))
            manage_text    = "⚙ Manage Room" + (f"  [{requests_count}]" if requests_count > 0 else "")
            btn_manage = tk.Label(header, text=manage_text, font=self.FONT_UI_BOLD,
                                  bg=self.BG_MAIN, fg=self.ACCENT, cursor="hand2")
            btn_manage.pack(side="right")
            btn_manage.bind("<Button-1>", lambda e: self.open_coordinator_panel(room_id))
            btn_manage.bind("<Enter>",    lambda e: btn_manage.config(fg=self.ACCENT_HOVER))
            btn_manage.bind("<Leave>",    lambda e: btn_manage.config(fg=self.ACCENT))
        else:
            # Botón Leave Room
            btn_leave = tk.Label(header, text="← Leave Room", font=self.FONT_LABEL,
                                 bg=self.BG_MAIN, fg=self.ERROR_COLOR, cursor="hand2")
            btn_leave.pack(side="right", padx=(0, 10))
            btn_leave.bind("<Button-1>", lambda e: self.leave_room(room_id))
            btn_leave.bind("<Enter>",    lambda e: btn_leave.config(fg="#FF4444"))
            btn_leave.bind("<Leave>",    lambda e: btn_leave.config(fg=self.ERROR_COLOR))

            # Botón Members (solo para miembros no coordinadores)
            btn_members = tk.Label(header, text="Members", font=self.FONT_LABEL,
                                   bg=self.BG_MAIN, fg=self.TEXT_MUTED, cursor="hand2")
            btn_members.pack(side="right", padx=(0, 15))
            btn_members.bind("<Button-1>", lambda e: self.open_members_panel(room_id))
            btn_members.bind("<Enter>",    lambda e: btn_members.config(fg=self.TEXT_MAIN))
            btn_members.bind("<Leave>",    lambda e: btn_members.config(fg=self.TEXT_MUTED))

        role_text  = "COORDINATOR" if is_coord else "MEMBER"
        role_color = self.ACCENT if is_coord else self.TEXT_MUTED
        tk.Label(header, text=role_text, font=self.FONT_LABEL,
                 bg=self.BG_MAIN, fg=role_color).pack(side="right", padx=(0, 20))

        tk.Frame(self.main_panel, bg=self.BG_SECONDARY, height=1).pack(fill="x", padx=30)

        # INPUT (pack ANTES)
        input_container = tk.Frame(self.main_panel, bg=self.BG_MAIN, pady=20)
        input_container.pack(fill="x", padx=30, side="bottom")

        border_frame = tk.Frame(input_container, bg=self.ACCENT, bd=0, padx=1, pady=1)
        border_frame.pack(side="left", fill="x", expand=True)

        self.entry_msg = tk.Entry(border_frame, font=self.FONT_CODE, bg=self.BG_SECONDARY,
                                  fg=self.TEXT_MAIN, relief="flat", bd=0, highlightthickness=0,
                                  insertbackground=self.ACCENT)
        self.entry_msg.pack(fill="both", expand=True, ipady=12, padx=10)
        self.entry_msg.bind("<Return>", lambda e: self.send_message())

        send_btn = tk.Label(input_container, text="SEND", font=self.FONT_UI_BOLD,
                            bg=self.ACCENT, fg="#FFFFFF", cursor="hand2", width=12)
        send_btn.pack(side="right", padx=(15, 0), ipady=10)
        send_btn.bind("<Button-1>", lambda e: self.send_message())
        send_btn.bind("<Enter>",    lambda e: send_btn.config(bg=self.ACCENT_HOVER))
        send_btn.bind("<Leave>",    lambda e: send_btn.config(bg=self.ACCENT))

        # HISTORIAL (pack DESPUÉS)
        chat_frame = tk.Frame(self.main_panel, bg=self.BG_MAIN)
        chat_frame.pack(fill="both", expand=True, padx=30, pady=(20, 0))

        self.chat_history = scrolledtext.ScrolledText(
            chat_frame, bg=self.BG_MAIN, fg=self.TEXT_MAIN,
            bd=0, font=self.FONT_CODE, wrap="word",
            highlightthickness=0, spacing1=5, spacing3=5)
        self.chat_history.pack(fill="both", expand=True)
        self.chat_history.vbar.configure(width=10)

        self.chat_history.tag_config("system", foreground=self.ACCENT, font=("Consolas", 10, "italic"))
        self.chat_history.tag_config("user",   foreground=self.TEXT_MUTED, font=("Consolas", 11, "bold"))
        self.chat_history.tag_config("msg",    foreground=self.TEXT_MAIN)

        self._load_chat_history(room_id)
        self.root.after(150, self.entry_msg.focus_force)

    def _load_chat_history(self, room_id):
        self.chat_history.config(state="normal")
        self.chat_history.insert(tk.END, "◆ Connected to node.\n", "system")
        self.chat_history.config(state="disabled")

        for sender, text in self._get_messages(room_id):
            self.chat_history.config(state="normal")
            if sender == "__SYSTEM__":
                self.chat_history.insert(tk.END, f"◆ {text}\n", "system")
            else:
                self.chat_history.insert(tk.END, f"[{sender}] ", "user")
                self.chat_history.insert(tk.END, f"{text}\n", "msg")
            self.chat_history.config(state="disabled")

        self.chat_history.yview(tk.END)

    # ─────────────────────────────────────────────
    #  MEMBERS PANEL (para usuarios no coordinadores)
    # ─────────────────────────────────────────────

    def open_members_panel(self, room_id):
        room = self._get_room(room_id)
        if not room:
            print(f"[GUI ERROR] No se encontró la sala {room_id} para abrir panel de miembros.")
            return

        panel = tk.Toplevel(self.root)
        panel.title(f"MEMBERS // {room['name'].upper()}")
        panel.geometry("400x500")
        panel.configure(bg=self.BG_DARK)
        panel.transient(self.root)
        panel.grab_set()

        tk.Label(panel, text=f"MIEMBROS DE #{room['name']}", font=self.FONT_TITLE,
                 bg=self.BG_DARK, fg=self.TEXT_MAIN).pack(pady=15)

        list_frame = tk.Frame(panel, bg=self.BG_MAIN, padx=5, pady=5)
        list_frame.pack(fill="both", expand=True, padx=20, pady=10)

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")

        lb = tk.Listbox(list_frame, font=self.FONT_CODE, bg=self.BG_MAIN, fg=self.TEXT_MAIN,
                        selectbackground=self.ACCENT, selectforeground=self.TEXT_MAIN,
                        bd=0, highlightthickness=0, yscrollcommand=scrollbar.set)
        lb.pack(fill="both", expand=True, side="left")
        scrollbar.config(command=lb.yview)

        # Determinar de dónde se extraen los miembros y mapear IDs a nombres reales del Servidor C
        if self.network:
            # Protocolo del handbook: {"type":"CHATROOM", "userIds":[1,2,3]}
            # Se cruza el ID con el diccionario global de la app para extraer el alias
            user_ids_list = room.get("userIds", [])
            for u_id in user_ids_list:
                # Buscamos en el mapeo de usuarios guardado en memoria durante el SYNC
                user_info = self.network.users.get(u_id, {})
                user_name = user_info.get("name", "Desconocido")
                lb.insert(tk.END, f"  • ID: {u_id} — {user_name}")
        else:
            members_list = self.mock.get_members(room_id)
            for m in members_list:
                lb.insert(tk.END, f"  • {m}")

        btn_close = tk.Button(panel, text="CLOSE", font=self.FONT_LABEL,
                              bg=self.BG_SECONDARY, fg=self.TEXT_MAIN, relief="flat", cursor="hand2",
                              command=panel.destroy, bd=0)
        btn_close.pack(fill="x", side="bottom", padx=20, pady=15, ipady=8)

    def refresh_users_ui(self):
        # 1. Asegurarnos de que tenemos el panel y la red
        if not hasattr(self, 'panel_usuarios') or not self.network:
            return

        # 2. DESTRUIR SOLO LOS BOTONES VIEJOS DE LOS USUARIOS
        # ¡Ojo! Si aquí destruyes el panel entero y luego llamas a tu función
        # que construye la barra lateral, vas a duplicar partes de la UI.
        for widget in self.panel_usuarios.winfo_children():
            widget.destroy()

        # 3. VOLVER A CREAR SOLO LOS BOTONES DE CONTACTOS
        for uid, user_data in self.network.users.items():
            username = user_data.get("name", f"User_{uid}")
            
            # Solo creamos el botón y lo empaquetamos (pack)
            btn_user = tk.Button(
                self.panel_usuarios, 
                text=f"🟢 {username}", 
                font=self.FONT_UI,
                bg=self.BG_MAIN, 
                fg=self.TEXT_MAIN, 
                relief="flat",
                anchor="w"
            )
            btn_user.pack(fill="x", pady=2)
    # ─────────────────────────────────────────────
    #  LEAVE ROOM
    # ─────────────────────────────────────────────

    def leave_room(self, room_id):
        room = self._get_room(room_id)
        if not room:
            return
        if self.confirm_dialog("LEAVE ROOM", f"Are you sure you want to leave '{room['name']}'?"):
            if self.network:
                self.network.leave_room(room_id)
            else:
                self.mock.kick_user(room_id, self.username)
                self.mock.messages.setdefault(room_id, []).append(
                    ("__SYSTEM__", f"{self.nickname} has left the room.")
                )
                self.current_room = None
                self.refresh_sidebar()
                self.show_welcome_view()

    # ─────────────────────────────────────────────
    #  COORDINATOR PANEL
    # ─────────────────────────────────────────────

    def open_coordinator_panel(self, room_id):
        room = self._get_room(room_id)
        if not room:
            print(f"[GUI ERROR] No se encontró la sala {room_id} para gestionar como Coordinador.")
            return

        panel = tk.Toplevel(self.root)
        panel.title(f"MANAGE // {room['name'].upper()}")
        panel.geometry("540x720")
        panel.resizable(False, True)
        panel.configure(bg=self.BG_DARK)
        panel.transient(self.root)
        panel.grab_set()

        # ── Título ────────────────────────────────────────────────
        tk.Label(panel, text=f"PANEL DE CONTROL // #{room['name'].upper()}",
                 font=self.FONT_TITLE, bg=self.BG_DARK, fg=self.ACCENT).pack(pady=15)

        # ── Scrollable interior ───────────────────────────────────
        canvas   = tk.Canvas(panel, bg=self.BG_DARK, highlightthickness=0)
        scrollbar = tk.Scrollbar(panel, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="top", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=self.BG_DARK)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_configure(e):
            canvas.itemconfig(inner_id, width=e.width)

        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # ─────────────────────────────────────────────────────────
        # SECCIÓN A: AÑADIR USUARIO (ADD_USER del handbook)
        # ─────────────────────────────────────────────────────────
        tk.Label(inner, text="AÑADIR USUARIO A LA SALA", font=self.FONT_LABEL,
                 bg=self.BG_DARK, fg=self.SUCCESS_COLOR).pack(anchor="w", padx=25, pady=(10, 0))

        add_frame = tk.Frame(inner, bg=self.BG_MAIN, bd=1, relief="solid")
        add_frame.pack(fill="x", padx=25, pady=5)

        # Usuarios conocidos que NO están en la sala
        if self.network:
            room_user_ids = set(room.get("userIds", []))
            my_id = self.network.me.get("id")
            addable = [
                (uid, udata.get("name", f"User_{uid}"))
                for uid, udata in self.network.users.items()
                if uid not in room_user_ids
            ]
        else:
            room_members = set(self.mock.get_members(room_id))
            addable = [
                (u["username"], u["nickname"])
                for u in self.mock.users
                if u["username"] not in room_members
            ]

        if not addable:
            tk.Label(add_frame, text="No hay usuarios disponibles para agregar.",
                     font=self.FONT_UI, bg=self.BG_MAIN, fg=self.TEXT_MUTED).pack(pady=12)
        else:
            for a_id, a_name in addable:
                row = tk.Frame(add_frame, bg=self.BG_MAIN, pady=4)
                row.pack(fill="x", padx=10)

                tk.Label(row, text=f"● {a_name}", font=self.FONT_UI,
                         bg=self.BG_MAIN, fg=self.TEXT_MAIN).pack(side="left")

                def _add(target_id=a_id, target_name=a_name):
                    if self.network:
                        # Handbook: {"type":"ADD_USER","chatRoomId":X,"userId":Y}
                        self.network.add_user_to_room(target_id, room_id)
                        # La respuesta llega vía on_user_added → refresh_sidebar
                    else:
                        r = self.mock.get_room(room_id)
                        if r and target_id not in r["members"]:
                            r["members"].append(target_id)
                    panel.destroy()
                    self.refresh_sidebar()

                btn_add = tk.Button(row, text="ADD", font=self.FONT_SMALL,
                                    bg=self.SUCCESS_COLOR, fg=self.BG_DARK,
                                    relief="flat", cursor="hand2", command=_add)
                btn_add.pack(side="right")
                btn_add.bind("<Enter>", lambda e, b=btn_add: b.config(bg="#1AC96A"))
                btn_add.bind("<Leave>", lambda e, b=btn_add: b.config(bg=self.SUCCESS_COLOR))

        # ─────────────────────────────────────────────────────────
        # SECCIÓN B: SOLICITUDES DE INGRESO PENDIENTES
        # ─────────────────────────────────────────────────────────
        tk.Frame(inner, bg="#2A2A2A", height=1).pack(fill="x", padx=25, pady=(12, 0))
        tk.Label(inner, text="SOLICITUDES PENDIENTES", font=self.FONT_LABEL,
                 bg=self.BG_DARK, fg=self.WARNING_COLOR).pack(anchor="w", padx=25, pady=(8, 0))

        req_frame = tk.Frame(inner, bg=self.BG_MAIN, bd=1, relief="solid")
        req_frame.pack(fill="x", padx=25, pady=5)

        if self.network:
            requests_list = [
                {
                    "userId": uid,
                    "nickname": self.network.users.get(uid, {}).get("name", f"User_{uid}")
                }
                for uid in room.get("requestIds", [])
            ]
        else:
            requests_list = self.mock.requests.get(room_id, [])

        if not requests_list:
            tk.Label(req_frame, text="No hay solicitudes pendientes.", font=self.FONT_UI,
                     bg=self.BG_MAIN, fg=self.TEXT_MUTED).pack(pady=12)
        else:
            for req in requests_list:
                r_item = tk.Frame(req_frame, bg=self.BG_MAIN, pady=4)
                r_item.pack(fill="x", padx=10)

                r_id   = req.get("userId",   req.get("username", "?"))
                r_name = req.get("nickname", req.get("name",     "Usuario"))

                tk.Label(r_item, text=f"• {r_name} (ID: {r_id})", font=self.FONT_UI,
                         bg=self.BG_MAIN, fg=self.TEXT_MAIN).pack(side="left")

                def accept_action(uid=r_id):
                    if self.network:
                        self.network.add_user_to_room(int(uid), room_id)
                    else:
                        self.mock.accept_request(room_id, uid)
                    panel.destroy()
                    self.open_coordinator_panel(room_id)

                def reject_action(uid=r_id):
                    if self.network:
                        self.network.delete_join_request(room_id, int(uid))
                    else:
                        self.mock.reject_request(room_id, uid)
                    panel.destroy()
                    self.open_coordinator_panel(room_id)

                tk.Button(r_item, text="REJECT", font=self.FONT_SMALL,
                          bg=self.ERROR_COLOR, fg=self.TEXT_MAIN, relief="flat",
                          command=reject_action).pack(side="right", padx=2)
                tk.Button(r_item, text="ACCEPT", font=self.FONT_SMALL,
                          bg=self.SUCCESS_COLOR, fg=self.BG_DARK, relief="flat",
                          command=accept_action).pack(side="right", padx=2)

        # ─────────────────────────────────────────────────────────
        # SECCIÓN C: EXPULSAR MIEMBROS (REMOVE_USER del handbook)
        # ─────────────────────────────────────────────────────────
        tk.Frame(inner, bg="#2A2A2A", height=1).pack(fill="x", padx=25, pady=(12, 0))
        tk.Label(inner, text="EXPULSAR MIEMBROS", font=self.FONT_LABEL,
                 bg=self.BG_DARK, fg=self.ERROR_COLOR).pack(anchor="w", padx=25, pady=(8, 0))

        memb_frame = tk.Frame(inner, bg=self.BG_MAIN, bd=1, relief="solid")
        memb_frame.pack(fill="x", padx=25, pady=5)

        if self.network:
            coord_id = room.get("coordinatorId")
            display_members = [
                (m_id, self.network.users.get(m_id, {}).get("name", f"User_{m_id}"))
                for m_id in room.get("userIds", [])
                if m_id != coord_id          # el coordinador no se patea a sí mismo
            ]
        else:
            display_members = [
                (m, m) for m in self.mock.get_members(room_id)
                if m != self.username
            ]

        if not display_members:
            tk.Label(memb_frame, text="No hay otros miembros en la sala.", font=self.FONT_UI,
                     bg=self.BG_MAIN, fg=self.TEXT_MUTED).pack(pady=12)
        else:
            for m_id, m_name in display_members:
                m_item = tk.Frame(memb_frame, bg=self.BG_MAIN, pady=4)
                m_item.pack(fill="x", padx=10)

                tk.Label(m_item, text=f"● {m_name}", font=self.FONT_UI,
                         bg=self.BG_MAIN, fg=self.TEXT_MAIN).pack(side="left")

                def kick_action(target_id=m_id, target_name=m_name):
                    panel.grab_release()
                    if self.confirm_dialog("KICK USER",
                                          f"¿Expulsar a {target_name} de la sala?",
                                          parent=panel):
                        if self.network:
                            # Handbook: {"type":"REMOVE_USER","chatRoomId":X,"userId":Y}
                            self.network.remove_user_from_room(target_id, room_id)
                        else:
                            self.mock.kick_user(room_id, target_id)
                        panel.destroy()
                        self.refresh_sidebar()
                    else:
                        panel.grab_set()

                btn_kick = tk.Button(m_item, text="KICK", font=self.FONT_SMALL,
                                     bg=self.ERROR_COLOR, fg=self.TEXT_MAIN,
                                     relief="flat", cursor="hand2", command=kick_action)
                btn_kick.pack(side="right")

        # ─────────────────────────────────────────────────────────
        # PIE: ELIMINAR SALA + CERRAR
        # ─────────────────────────────────────────────────────────
        footer_frame = tk.Frame(panel, bg=self.BG_DARK)
        footer_frame.pack(fill="x", side="bottom", padx=25, pady=15)

        def delete_room_action():
            panel.grab_release()
            if self.confirm_dialog("DELETE ROOM",
                                   "¿Eliminar esta sala? Solo es posible si eres el único miembro.",
                                   parent=panel):
                if self.network:
                    # Handbook: {"type":"DELETE_CHATROOM","chatRoomId":X}
                    self.network.delete_room(room_id)
                else:
                    success = self.mock.delete_room(room_id)
                    if not success:
                        self.info_dialog("ADVERTENCIA",
                                         "Solo puedes eliminar la sala si eres el último miembro.",
                                         parent=panel, color=self.WARNING_COLOR)
                        panel.grab_set()
                        return
                panel.destroy()
                self.current_room = None
                self.refresh_sidebar()
                self.show_welcome_view()
            else:
                panel.grab_set()

        tk.Button(footer_frame, text="DELETE ROOM", font=self.FONT_LABEL,
                  bg=self.ERROR_COLOR, fg=self.TEXT_MAIN, relief="flat", cursor="hand2",
                  command=delete_room_action, bd=0).pack(side="left", ipady=8, ipadx=10)

        tk.Button(footer_frame, text="CLOSE", font=self.FONT_LABEL,
                  bg=self.BG_SECONDARY, fg=self.TEXT_MAIN, relief="flat", cursor="hand2",
                  command=panel.destroy, bd=0).pack(side="right", ipady=8, ipadx=20)
    
    # ─────────────────────────────────────────────
    #  ACCIONES COORDINADOR
    # ─────────────────────────────────────────────

    def coord_accept(self, room_id, username, panel):
        self.mock.accept_request(room_id, username)
        panel.destroy()
        self.show_chat_view(room_id)
        self.insert_system_message(f"{username} was accepted into the room.")
        self.open_coordinator_panel(room_id)

    def coord_reject(self, room_id, username, panel):
        self.mock.reject_request(room_id, username)
        panel.destroy()
        self.show_chat_view(room_id)
        self.insert_system_message(f"{username}'s request was rejected.")
        self.open_coordinator_panel(room_id)

    def coord_kick(self, room_id, username, panel):
        panel.grab_release()
        if self.confirm_dialog("KICK USER", f"Remove {username} from the room?", parent=panel):
            self.mock.kick_user(room_id, username)
            panel.destroy()
            self.show_chat_view(room_id)
            self.insert_system_message(f"{username} was removed from the room.")
            self.open_coordinator_panel(room_id)
        else:
            panel.grab_set()

    def coord_add(self, room_id, username, nickname, panel):
        # AQUÍ IRÍA: self.network.send("COORD_INVITE_USER", room_id, username)
        room = self.mock.get_room(room_id)
        room["members"].append(username)
        self.mock.reject_request(room_id, username)
        panel.destroy()
        self.show_chat_view(room_id)
        self.insert_system_message(f"{nickname} was added to the room.")
        self.open_coordinator_panel(room_id)

    def coord_delete_room(self, room_id, panel):
        panel.grab_release()
        if self.confirm_dialog("DELETE ROOM", "Delete this room? This action cannot be undone.", parent=panel):
            success = self.mock.delete_room(room_id)
            if success:
                panel.destroy()
                self.current_room = None
                self.refresh_sidebar()
                self.show_welcome_view()
            else:
                self.info_dialog("WARNING",
                                 "You can only delete a room when you are the last member.",
                                 parent=panel, color=self.WARNING_COLOR)
                panel.grab_set()
        else:
            panel.grab_set()

    # ─────────────────────────────────────────────
    #  CALLBACKS EN TIEMPO REAL (NetworkClient)
    #  AppController los inyecta tras __init__.
    # ─────────────────────────────────────────────

    def on_new_message(self, room_id, msg_dict):
        """Llega cuando el servidor hace push de un mensaje nuevo."""
        sender = self._resolve_username(msg_dict.get("userId"))
        text   = msg_dict.get("text", "")
        if room_id == self.current_room and self.chat_history:
            self.chat_history.config(state="normal")
            self.chat_history.insert(tk.END, f"[{sender}] ", "user")
            self.chat_history.insert(tk.END, f"{text}\n", "msg")
            self.chat_history.config(state="disabled")
            self.chat_history.yview(tk.END)
        else:
            # Notificación en sidebar
            if self.network:
                room = self.network.rooms.get(room_id)
                if room:
                    room["notifications"] = room.get("notifications", 0) + 1
            self.refresh_sidebar()
            room_name = (self.network.rooms.get(room_id, {}).get("name", str(room_id))
                         if self.network else str(room_id))
            self.show_toast(room_id, room_name, sender, text)

    def on_room_created(self, room_dict):
        """Llega cuando se crea una sala nueva (broadcast del servidor)."""
        self.refresh_sidebar()

    def on_user_added(self, room_id, user_dict):
        """Llega cuando alguien es agregado a una sala."""
        self.refresh_sidebar()
        if room_id == self.current_room:
            name = user_dict.get("name", "?")
            if self.chat_history:
                self.chat_history.config(state="normal")
                self.chat_history.insert(tk.END, f"◆ {name} joined the room.\n", "system")
                self.chat_history.config(state="disabled")
                self.chat_history.yview(tk.END)

    def on_user_removed(self, room_id, user_id):
        """Llega cuando alguien es removido de una sala."""
        name = self._resolve_username(user_id)
        my_id = self.network.me.get("id") if self.network else None
        if user_id == my_id:
            # Nos removieron a nosotros
            if self.current_room == room_id:
                self.current_room = None
                self.show_welcome_view()
            self.refresh_sidebar()
        else:
            self.refresh_sidebar()
            if room_id == self.current_room and self.chat_history:
                self.chat_history.config(state="normal")
                self.chat_history.insert(tk.END, f"◆ {name} was removed from the room.\n", "system")
                self.chat_history.config(state="disabled")
                self.chat_history.yview(tk.END)

    def on_message_deleted(self, room_id, message_id):
        """Llega cuando se elimina un mensaje (recarga historial si es la sala activa)."""
        if room_id == self.current_room:
            self.show_chat_view(room_id)

    def on_room_deleted(self, room_id):
        """Llega cuando se elimina una sala."""
        if self.current_room == room_id:
            self.current_room = None
            self.show_welcome_view()
        self.refresh_sidebar()

    def refresh_users_ui(self):
        # 1. Limpiar el contenedor actual de usuarios
        for widget in self.panel_usuarios.winfo_children():
            widget.destroy()
        
        # 2. Volver a iterar sobre la memoria actualizada y dibujarlos
        for uid, user_data in self.network.users.items():
            # Aquí creas tu Label, Button, etc.
            tk.Label(self.panel_usuarios, text=f"🟢 {user_data['name']}").pack()

    # ─────────────────────────────────────────────
    #  CREATE ROOM
    # ─────────────────────────────────────────────

    def open_create_room_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("CREATE ROOM")
        dialog.geometry("400x260")
        dialog.resizable(False, False)
        dialog.configure(bg=self.BG_MAIN)
        dialog.transient(self.root)
        dialog.grab_set()

        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth()  - 400) // 2
        y = (dialog.winfo_screenheight() - 260) // 2
        dialog.geometry(f"400x260+{x}+{y}")

        tk.Label(dialog, text="CREATE ROOM", font=self.FONT_TITLE,
                 bg=self.BG_MAIN, fg=self.TEXT_MAIN).pack(anchor="w", padx=30, pady=(30, 0))
        tk.Frame(dialog, bg=self.ACCENT, height=2).pack(fill="x", padx=30, pady=(10, 0))

        form = tk.Frame(dialog, bg=self.BG_MAIN, padx=30)
        form.pack(fill="both", expand=True, pady=10)

        tk.Label(form, text="ROOM NAME", font=self.FONT_LABEL,
                 bg=self.BG_MAIN, fg=self.ACCENT).pack(anchor="w", pady=(15, 0))

        border = tk.Frame(form, bg=self.BG_SECONDARY, padx=2, pady=2)
        border.pack(fill="x", pady=(4, 0))

        entry_name = tk.Entry(border, font=self.FONT_CODE, bg=self.BG_SECONDARY,
                              fg=self.TEXT_MAIN, relief="flat", insertbackground=self.ACCENT,
                              highlightthickness=0)
        entry_name.pack(fill="x", ipady=10, padx=5)
        entry_name.bind("<FocusIn>",  lambda e: border.config(bg=self.ACCENT))
        entry_name.bind("<FocusOut>", lambda e: border.config(bg=self.BG_SECONDARY))
        dialog.after(150, entry_name.focus_force)

        lbl_error = tk.Label(form, text="", font=self.FONT_SMALL,
                             bg=self.BG_MAIN, fg=self.ERROR_COLOR)
        lbl_error.pack(anchor="w", pady=(5, 0))

        def do_create():
            name = entry_name.get().strip()
            if not name:
                lbl_error.config(text="◆ Room name cannot be empty.")
                return
            if len(name) < 3:
                lbl_error.config(text="◆ Room name must be at least 3 characters.")
                return
            if self.network:
                self.network.create_room(name)
                # La sala llegará vía on_room_created callback + refresh_sidebar
                dialog.destroy()
            else:
                room_id = name.lower().replace(" ", "-")
                self.mock.create_room(name)
                self.refresh_sidebar()
                dialog.destroy()
                self.show_chat_view(room_id)
                self.insert_system_message(f"Room '{name}' created. You are the coordinator.")

        entry_name.bind("<Return>", lambda e: do_create())

        btn = tk.Label(form, text="CREATE →", font=self.FONT_UI_BOLD,
                       bg=self.ACCENT, fg="#FFFFFF", cursor="hand2")
        btn.pack(fill="x", ipady=10, pady=(20, 0))
        btn.bind("<Button-1>", lambda e: do_create())
        btn.bind("<Enter>",    lambda e: btn.config(bg=self.ACCENT_HOVER))
        btn.bind("<Leave>",    lambda e: btn.config(bg=self.ACCENT))

    # ─────────────────────────────────────────────
    #  REQUEST JOIN
    # ─────────────────────────────────────────────

    def request_join_from_view(self, room_id):
        if self.network:
            self.network.request_join_room(room_id)
            self.pending_rooms.add(room_id)
            self.show_private_room_view(room_id)
        else:
            success = self.mock.request_join(room_id)
            if success:
                self.pending_rooms.add(room_id)
                self.show_private_room_view(room_id)
            else:
                self.info_dialog("WARNING", "Could not send join request.", color=self.WARNING_COLOR)

    def on_join_request_sent(self, room_id, success):
        """Callback: el servidor confirmó (o rechazó) el envío de la solicitud."""
        def _update():
            if not success:
                self.pending_rooms.discard(room_id)
                self.info_dialog("WARNING", "Could not send join request.", color=self.WARNING_COLOR)
                if self.current_room == room_id:
                    self.show_private_room_view(room_id)
        self.root.after(0, _update)

    def on_join_request_received(self, room_id, requester_id, requester_name):
        """Callback: llegó una solicitud de ingreso para una sala que coordino."""
        def _update():
            room = self._get_room(room_id)
            room_name = room["name"] if room else str(room_id)
            self.show_toast(
                room_id, room_name,
                "◆ Join Request",
                f"{requester_name} wants to join #{room_name}",
            )
            if self.current_room == room_id:
                self.show_chat_view(room_id)
        self.root.after(0, _update)

    # ─────────────────────────────────────────────
    #  CHANNEL SELECT
    # ─────────────────────────────────────────────

    def on_channel_select(self, event):
        # Navigation is now handled by _make_room_row click bindings.
        pass

    # ─────────────────────────────────────────────
    #  MENSAJES
    # ─────────────────────────────────────────────

    def insert_system_message(self, text):
        # AQUÍ IRÍA: el backend mandaría este evento a todos los miembros
        if not self.current_room:
            return
        self.mock.messages.setdefault(self.current_room, []).append(("__SYSTEM__", text))
        if self.chat_history is None:
            return
        self.chat_history.config(state="normal")
        self.chat_history.insert(tk.END, f"◆ {text}\n", "system")
        self.chat_history.config(state="disabled")
        self.chat_history.yview(tk.END)

    def send_message(self):
        msg = self.entry_msg.get().strip()
        if not msg or not self.current_room:
            return
        if self.network:
            self.network.send_message(self.current_room, msg)
            # El mensaje llegará de vuelta vía on_new_message callback
        else:
            self.mock.send_message(self.current_room, msg)
            self.chat_history.config(state="normal")
            self.chat_history.insert(tk.END, f"[{self.nickname}] ", "user")
            self.chat_history.insert(tk.END, f"{msg}\n", "msg")
            self.chat_history.config(state="disabled")
            self.chat_history.yview(tk.END)
        self.entry_msg.delete(0, tk.END)

    # ─────────────────────────────────────────────
    #  PERFIL
    # ─────────────────────────────────────────────

    def open_profile(self):
        UserProfileWindow(self.root, username=self.username, current_nickname=self.nickname)

    


if __name__ == "__main__":
    root = tk.Tk()
    app = ChatClientGUI(root)
    root.mainloop()