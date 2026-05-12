import tkinter as tk
import random
from tkinter import scrolledtext
from gui.user_profile import UserProfileWindow
from gui.mock_data import MockServer


class ChatClientGUI:
    def __init__(self, root, username="jperez_root", nickname="jperez.sys"):
        self.root = root
        self.root.title("PIMENTEL CO. // WORKSPACE")
        self.root.geometry("1050x700")

        # --- PALETA REFINADA ---
        self.BG_DARK = "#0D0D0D"
        self.BG_MAIN = "#141414"
        self.BG_SECONDARY = "#1E1E1E"
        self.TEXT_MAIN = "#E0E0E0"
        self.TEXT_MUTED = "#6B6B6B"
        self.ACCENT = "#2232E3"
        self.ACCENT_HOVER = "#3A4BFF"
        self.ERROR_COLOR = "#E32222"
        self.SUCCESS_COLOR = "#22E37A"
        self.WARNING_COLOR = "#E3A022"

        # --- TIPOGRAFÍA REFINADA ---
        self.FONT_UI = ("Segoe UI", 10)
        self.FONT_UI_BOLD = ("Segoe UI", 10, "bold")
        self.FONT_TITLE = ("Segoe UI", 16, "bold")
        self.FONT_CODE = ("Consolas", 11)
        self.FONT_LABEL = ("Segoe UI", 9, "bold")
        self.FONT_SMALL = ("Segoe UI", 9)

        # --- SESIÓN Y DATOS ---
        self.username = username
        self.nickname = nickname
        self.current_room = None
        self.chat_history = None
        self.pending_rooms = set()
        self.active_toasts = []

        # MockServer simula el backend — reemplazar por NetworkClient cuando esté listo
        # AQUÍ IRÍA: self.network = NetworkClient(); self.network.connect(IP, PORT)
        self.mock = MockServer(current_user=username, current_nick=nickname)

        self.root.configure(bg=self.BG_MAIN)
        self.build_ui()

        # Iniciar simulaciones de eventos del servidor
        self._simulate_incoming_messages()
        self._simulate_user_leave()

    # --- DIALOGS PERSONALIZADOS ---
    # Reemplazan los messagebox nativos para mantener el estilo del proyecto

    def confirm_dialog(self, title, message, parent=None):
        # Dialog de confirmación (Yes/No) — retorna True si confirma
        result = {"value": False}
        win = parent or self.root

        dialog = tk.Toplevel(win)
        dialog.title("")
        dialog.resizable(False, False)
        dialog.configure(bg=self.BG_MAIN)
        dialog.transient(win)
        dialog.grab_set()
        dialog.focus_force()

        dialog.update_idletasks()
        pw = win.winfo_width()
        ph = win.winfo_height()
        px = win.winfo_x()
        py = win.winfo_y()
        dw, dh = 380, 170
        x = px + (pw - dw) // 2
        y = py + (ph - dh) // 2
        dialog.geometry(f"{dw}x{dh}+{x}+{y}")

        # Borde azul superior
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
        btn_cancel.bind("<Enter>", lambda e: btn_cancel.config(bg="#252525"))
        btn_cancel.bind("<Leave>", lambda e: btn_cancel.config(bg=self.BG_SECONDARY))

        btn_ok = tk.Label(btn_frame, text="CONFIRM", font=self.FONT_LABEL,
                          bg=self.ACCENT, fg="#FFFFFF",
                          cursor="hand2", padx=20, pady=8)
        btn_ok.pack(side="right")
        btn_ok.bind("<Button-1>", lambda e: on_confirm())
        btn_ok.bind("<Enter>", lambda e: btn_ok.config(bg=self.ACCENT_HOVER))
        btn_ok.bind("<Leave>", lambda e: btn_ok.config(bg=self.ACCENT))

        dialog.bind("<Escape>", lambda e: on_cancel())
        dialog.bind("<Return>", lambda e: on_confirm())

        dialog.wait_window()
        return result["value"]

    def info_dialog(self, title, message, parent=None, color=None):
        # Dialog informativo (solo OK)
        win = parent or self.root
        color = color or self.ACCENT

        dialog = tk.Toplevel(win)
        dialog.title("")
        dialog.resizable(False, False)
        dialog.configure(bg=self.BG_MAIN)
        dialog.transient(win)
        dialog.grab_set()
        dialog.focus_force()

        dialog.update_idletasks()
        pw = win.winfo_width()
        ph = win.winfo_height()
        px = win.winfo_x()
        py = win.winfo_y()
        dw, dh = 380, 150
        x = px + (pw - dw) // 2
        y = py + (ph - dh) // 2
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
                          bg=color, fg="#FFFFFF",
                          cursor="hand2", padx=20, pady=8)
        btn_ok.pack(side="right")
        btn_ok.bind("<Button-1>", lambda e: dialog.destroy())
        btn_ok.bind("<Enter>", lambda e: btn_ok.config(bg=self.ACCENT_HOVER))
        btn_ok.bind("<Leave>", lambda e: btn_ok.config(bg=color))

        dialog.bind("<Return>", lambda e: dialog.destroy())
        dialog.bind("<Escape>", lambda e: dialog.destroy())

        dialog.wait_window()

    def build_ui(self):
        # --- SIDEBAR ---
        self.sidebar = tk.Frame(self.root, bg=self.BG_DARK, width=260)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        header_frame = tk.Frame(self.sidebar, bg=self.BG_DARK)
        header_frame.pack(fill="x", padx=25, pady=30)

        tk.Label(header_frame, text="PIMENTEL CO.", font=self.FONT_TITLE,
                 bg=self.BG_DARK, fg=self.TEXT_MAIN, anchor="w").pack(fill="x")

        tk.Frame(self.sidebar, bg=self.ACCENT, height=2).pack(fill="x", padx=25, pady=(0, 20))

        # --- SECCIÓN CHANNELS ---
        channels_header = tk.Frame(self.sidebar, bg=self.BG_DARK)
        channels_header.pack(fill="x", padx=25, pady=(10, 5))

        tk.Label(channels_header, text="CHANNELS", font=self.FONT_UI_BOLD,
                 bg=self.BG_DARK, fg=self.TEXT_MUTED, anchor="w").pack(side="left")

        btn_create = tk.Label(channels_header, text="＋", font=self.FONT_UI_BOLD,
                              bg=self.BG_DARK, fg=self.ACCENT, cursor="hand2")
        btn_create.pack(side="right")
        btn_create.bind("<Button-1>", lambda e: self.open_create_room_dialog())
        btn_create.bind("<Enter>", lambda e: btn_create.config(fg=self.ACCENT_HOVER))
        btn_create.bind("<Leave>", lambda e: btn_create.config(fg=self.ACCENT))

        self.channels_list = tk.Listbox(self.sidebar, bg=self.BG_DARK, fg=self.TEXT_MAIN,
                                        bd=0, highlightthickness=0,
                                        selectbackground=self.ACCENT, selectforeground="#FFFFFF",
                                        font=self.FONT_CODE, height=8, activestyle="none")
        self.channels_list.pack(fill="x", padx=15)
        self.channels_list.bind("<<ListboxSelect>>", self.on_channel_select)

        # --- SECCIÓN ONLINE ---
        tk.Label(self.sidebar, text="ONLINE", font=self.FONT_UI_BOLD,
                 bg=self.BG_DARK, fg=self.TEXT_MUTED, anchor="w").pack(fill="x", padx=25, pady=(25, 5))

        self.online_frame = tk.Frame(self.sidebar, bg=self.BG_DARK)
        self.online_frame.pack(fill="x", padx=15)

        # --- PERFIL INFERIOR ---
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

        # --- PANEL PRINCIPAL ---
        self.main_panel = tk.Frame(self.root, bg=self.BG_MAIN)
        self.main_panel.pack(side="right", fill="both", expand=True)

        self.refresh_sidebar()
        self.show_welcome_view()

    # --- REFRESH DE DATOS ---

    def refresh_sidebar(self):
        self.channels_list.delete(0, tk.END)
        for room in self.mock.get_rooms():
            notif = room["notifications"]
            label = f" # {room['name']}"
            if notif > 0:
                label += f"  [{notif}]"
            self.channels_list.insert(tk.END, label)

        for widget in self.online_frame.winfo_children():
            widget.destroy()

        for user in self.mock.get_online_users():
            row = tk.Frame(self.online_frame, bg=self.BG_SECONDARY, pady=3)
            row.pack(fill="x", pady=2, padx=2)

            tk.Label(row, text="●", font=self.FONT_UI_BOLD,
                     bg=self.BG_SECONDARY, fg=self.SUCCESS_COLOR).pack(side="left", padx=(8, 4))

            tk.Label(row, text=user["nickname"], font=self.FONT_UI,
                     bg=self.BG_SECONDARY, fg=self.TEXT_MAIN).pack(side="left")

    # --- TOAST NOTIFICATION ---

    def show_toast(self, room_id, room_name, sender, message):
        # Limitar a máximo 10 toasts activos al mismo tiempo
        if len(self.active_toasts) >= 10:
            return

        toast = tk.Toplevel(self.root)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.configure(bg=self.BG_SECONDARY)

        self.root.update_idletasks()
        root_x = self.root.winfo_x()
        root_y = self.root.winfo_y()
        root_w = self.root.winfo_width()
        root_h = self.root.winfo_height()

        toast_w = 300
        toast_h = 80
        offset = len(self.active_toasts) * (toast_h + 10)

        x = root_x + root_w - toast_w - 20
        y = root_y + root_h - toast_h - 20 - offset
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
        room = self.mock.get_room(room_id)
        if room and self.username in room["members"]:
            self.current_room = room_id
            room["notifications"] = 0
            self.show_chat_view(room_id)
            self.refresh_sidebar()

    # --- SIMULACIÓN DE MENSAJES ENTRANTES (demo sin backend) ---

    def _simulate_incoming_messages(self):
        # Simula mensajes entrantes de miembros reales de cada sala
        # AQUÍ IRÍA: el hilo de escucha real del NetworkClient
        my_rooms = self.mock.get_my_rooms()  # MODIFICADO: Se elimina el filtro de sala actual

        if my_rooms:
            room = random.choice(my_rooms)
            member_nicknames = self.mock.get_member_nicknames(room["id"])

            if member_nicknames:
                sender = random.choice(member_nicknames)
                msgs = ["Hey, anyone there?", "Check this out.", "Meeting in 5.",
                        "Server looks good.", "Deploy done.", "Need a review."]
                text = random.choice(msgs)

                self.mock.messages.setdefault(room["id"], []).append((sender, text))

                # MODIFICADO: Si estamos en la sala actual, se actualiza el chat history en vez de la notificación
                if room["id"] == self.current_room:
                    if self.chat_history is not None:
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

    # --- SIMULACIÓN DE USUARIOS ABANDONANDO SALA (demo sin backend) ---

    def _simulate_user_leave(self):
        # Simula que un miembro abandona voluntariamente una sala del usuario actual
        # AQUÍ IRÍA: el evento real vendría del servidor vía NetworkClient
        my_rooms = self.mock.get_my_rooms()  # MODIFICADO: Se elimina el filtro

        if my_rooms:
            room = random.choice(my_rooms)
            members = self.mock.get_member_nicknames(room["id"])

            if members:
                leaver = random.choice(members)

                # MODIFICADO: Buscar el username asociado al nickname y removerlo para que no siga enviando mensajes
                leaver_username = None
                for u in self.mock.users:
                    if u["nickname"] == leaver:
                        leaver_username = u["username"]
                        break

                if leaver_username and leaver_username in room["members"]:
                    room["members"].remove(leaver_username)

                # Guardar como mensaje de sistema en el historial de esa sala
                self.mock.messages.setdefault(room["id"], []).append(
                    ("__SYSTEM__", f"{leaver} has left the room.")
                )

                # MODIFICADO: Si estamos en la sala actual, actualizamos en vivo el historial del sistema
                if room["id"] == self.current_room:
                    if self.chat_history is not None:
                        self.chat_history.config(state="normal")
                        self.chat_history.insert(tk.END, f"◆ {leaver} has left the room.\n", "system")
                        self.chat_history.config(state="disabled")
                        self.chat_history.yview(tk.END)
                else:
                    room["notifications"] += 1
                    self.refresh_sidebar()

                    # Toast con estilo de sistema
                    self.show_toast(room["id"], room["name"], "◆ System", f"{leaver} has left.")

        # Simular cada 30 segundos — menos frecuente que los mensajes
        self.root.after(30000, self._simulate_user_leave)

    # --- VISTAS ---

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
        room = self.mock.get_room(room_id)
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
            btn.bind("<Enter>", lambda e: btn.config(bg=self.ACCENT_HOVER))
            btn.bind("<Leave>", lambda e: btn.config(bg=self.ACCENT))

    def show_chat_view(self, room_id):
        self.clear_main_panel()
        self.current_room = room_id
        room = self.mock.get_room(room_id)
        is_coord = self.mock.is_coordinator(room_id)

        # --- CABECERA ---
        header = tk.Frame(self.main_panel, bg=self.BG_MAIN, pady=20)
        header.pack(fill="x", padx=30)

        tk.Label(header, text=f"# {room['name']}", font=self.FONT_TITLE,
                 bg=self.BG_MAIN, fg=self.TEXT_MAIN).pack(side="left")

        if is_coord:
            requests_count = len(self.mock.get_join_requests(room_id))
            manage_text = "⚙ Manage Room" + (f"  [{requests_count}]" if requests_count > 0 else "")
            btn_manage = tk.Label(header, text=manage_text, font=self.FONT_UI_BOLD,
                                  bg=self.BG_MAIN, fg=self.ACCENT, cursor="hand2")
            btn_manage.pack(side="right")
            btn_manage.bind("<Button-1>", lambda e: self.open_coordinator_panel(room_id))
            btn_manage.bind("<Enter>", lambda e: btn_manage.config(fg=self.ACCENT_HOVER))
            btn_manage.bind("<Leave>", lambda e: btn_manage.config(fg=self.ACCENT))

        if not is_coord:
            btn_leave = tk.Label(header, text="← Leave Room", font=self.FONT_LABEL,
                                 bg=self.BG_MAIN, fg=self.ERROR_COLOR, cursor="hand2")
            btn_leave.pack(side="right", padx=(0, 10))
            btn_leave.bind("<Button-1>", lambda e: self.leave_room(room_id))
            btn_leave.bind("<Enter>", lambda e: btn_leave.config(fg="#FF4444"))
            btn_leave.bind("<Leave>", lambda e: btn_leave.config(fg=self.ERROR_COLOR))

        role_text = "COORDINATOR" if is_coord else "MEMBER"
        role_color = self.ACCENT if is_coord else self.TEXT_MUTED
        tk.Label(header, text=role_text, font=self.FONT_LABEL,
                 bg=self.BG_MAIN, fg=role_color).pack(side="right", padx=(0, 20))

        tk.Frame(self.main_panel, bg=self.BG_SECONDARY, height=1).pack(fill="x", padx=30)

        # --- INPUT (pack ANTES para garantizar visibilidad) ---
        input_container = tk.Frame(self.main_panel, bg=self.BG_MAIN, pady=20)
        input_container.pack(fill="x", padx=30, side="bottom")

        border_frame = tk.Frame(input_container, bg=self.ACCENT, bd=0, padx=1, pady=1)
        border_frame.pack(side="left", fill="x", expand=True)

        self.entry_msg = tk.Entry(border_frame, font=self.FONT_CODE, bg=self.BG_SECONDARY,
                                  fg=self.TEXT_MAIN, relief="flat", bd=0, highlightthickness=0,
                                  insertbackground=self.ACCENT)
        self.entry_msg.pack(fill="both", expand=True, ipady=12, padx=10)
        self.entry_msg.bind("<Return>", lambda e: self.send_message())

        # Fix macOS: usar Label en vez de Button para respetar el color
        send_btn = tk.Label(input_container, text="SEND", font=self.FONT_UI_BOLD,
                            bg=self.ACCENT, fg="#FFFFFF", cursor="hand2", width=12)
        send_btn.pack(side="right", padx=(15, 0), ipady=10)
        send_btn.bind("<Button-1>", lambda e: self.send_message())
        send_btn.bind("<Enter>", lambda e: send_btn.config(bg=self.ACCENT_HOVER))
        send_btn.bind("<Leave>", lambda e: send_btn.config(bg=self.ACCENT))

        # --- HISTORIAL (pack DESPUÉS) ---
        chat_frame = tk.Frame(self.main_panel, bg=self.BG_MAIN)
        chat_frame.pack(fill="both", expand=True, padx=30, pady=(20, 0))

        self.chat_history = scrolledtext.ScrolledText(chat_frame, bg=self.BG_MAIN, fg=self.TEXT_MAIN,
                                                      bd=0, font=self.FONT_CODE, wrap="word",
                                                      highlightthickness=0, spacing1=5, spacing3=5)
        self.chat_history.pack(fill="both", expand=True)
        self.chat_history.vbar.configure(width=10)

        self.chat_history.tag_config("system", foreground=self.ACCENT, font=("Consolas", 10, "italic"))
        self.chat_history.tag_config("user", foreground=self.TEXT_MUTED, font=("Consolas", 11, "bold"))
        self.chat_history.tag_config("msg", foreground=self.TEXT_MAIN)

        self._load_chat_history(room_id)
        self.root.after(150, self.entry_msg.focus_force)

    def _load_chat_history(self, room_id):
        # Render todos los mensajes en orden cronológico
        # Los mensajes de sistema usan el tag "__SYSTEM__" para mantener el orden correcto
        self.chat_history.config(state="normal")
        self.chat_history.insert(tk.END, "◆ Connected to node.\n", "system")
        self.chat_history.config(state="disabled")

        for sender, text in self.mock.get_messages(room_id):
            self.chat_history.config(state="normal")
            if sender == "__SYSTEM__":
                self.chat_history.insert(tk.END, f"◆ {text}\n", "system")
            else:
                self.chat_history.insert(tk.END, f"[{sender}] ", "user")
                self.chat_history.insert(tk.END, f"{text}\n", "msg")
            self.chat_history.config(state="disabled")

        self.chat_history.yview(tk.END)

    # --- LEAVE ROOM ---

    def leave_room(self, room_id):
        room = self.mock.get_room(room_id)
        if self.confirm_dialog("LEAVE ROOM", f"Are you sure you want to leave '{room['name']}'?"):
            # AQUÍ IRÍA: self.network.send("LOBBY_LEAVE_ROOM", room_id)
            self.mock.kick_user(room_id, self.username)
            self.mock.messages.setdefault(room_id, []).append(
                ("__SYSTEM__", f"{self.nickname} has left the room.")
            )
            self.current_room = None
            self.refresh_sidebar()
            self.show_welcome_view()

    # --- PANEL DEL COORDINADOR ---

    def open_coordinator_panel(self, room_id):
        room = self.mock.get_room(room_id)

        panel = tk.Toplevel(self.root)
        panel.title(f"MANAGE // {room['name'].upper()}")
        panel.geometry("440x620")
        panel.resizable(False, False)
        panel.configure(bg=self.BG_MAIN)
        panel.transient(self.root)
        panel.grab_set()
        panel.focus_force()

        # --- HEADER ---
        header = tk.Frame(panel, bg=self.BG_MAIN)
        header.pack(fill="x", padx=30, pady=(30, 0))

        tk.Label(header, text=f"# {room['name']}", font=self.FONT_TITLE,
                 bg=self.BG_MAIN, fg=self.TEXT_MAIN, anchor="w").pack(fill="x")
        tk.Label(header, text="Coordinator Panel", font=self.FONT_CODE,
                 bg=self.BG_MAIN, fg=self.TEXT_MUTED, anchor="w").pack(fill="x", pady=(4, 0))

        tk.Frame(panel, bg=self.ACCENT, height=2).pack(fill="x", padx=30, pady=(15, 0))

        form = tk.Frame(panel, bg=self.BG_MAIN, padx=30)
        form.pack(fill="both", expand=True, pady=15)

        # --- SOLICITUDES PENDIENTES ---
        tk.Label(form, text="PENDING REQUESTS", font=self.FONT_LABEL,
                 bg=self.BG_MAIN, fg=self.ACCENT).pack(anchor="w", pady=(10, 5))

        requests = self.mock.get_join_requests(room_id)
        if not requests:
            tk.Label(form, text="No pending requests.", font=self.FONT_SMALL,
                     bg=self.BG_MAIN, fg=self.TEXT_MUTED).pack(anchor="w", padx=5)
        else:
            for req in requests:
                req_frame = tk.Frame(form, bg=self.BG_SECONDARY)
                req_frame.pack(fill="x", pady=3)

                tk.Label(req_frame, text=f"  ● {req['nickname']}", font=self.FONT_UI,
                         bg=self.BG_SECONDARY, fg=self.TEXT_MAIN).pack(side="left", padx=10, pady=8)

                btn_reject = tk.Label(req_frame, text="✕", font=self.FONT_UI_BOLD,
                                      bg=self.BG_SECONDARY, fg=self.ERROR_COLOR, cursor="hand2")
                btn_reject.pack(side="right", padx=10)
                btn_reject.bind("<Button-1>", lambda e, u=req["username"]: self.coord_reject(room_id, u, panel))

                btn_accept = tk.Label(req_frame, text="✓", font=self.FONT_UI_BOLD,
                                      bg=self.BG_SECONDARY, fg=self.SUCCESS_COLOR, cursor="hand2")
                btn_accept.pack(side="right", padx=5)
                btn_accept.bind("<Button-1>", lambda e, u=req["username"]: self.coord_accept(room_id, u, panel))

        tk.Frame(form, bg=self.BG_SECONDARY, height=1).pack(fill="x", pady=15)

        # --- TODOS LOS USUARIOS DEL SISTEMA ---
        tk.Label(form, text="ALL USERS", font=self.FONT_LABEL,
                 bg=self.BG_MAIN, fg=self.ACCENT).pack(anchor="w", pady=(0, 5))

        members = self.mock.get_members(room_id)
        all_users = self.mock.get_all_users()

        for user in all_users:
            user_frame = tk.Frame(form, bg=self.BG_SECONDARY)
            user_frame.pack(fill="x", pady=3)

            dot_color = self.SUCCESS_COLOR if user["online"] else self.TEXT_MUTED
            tk.Label(user_frame, text="●", font=self.FONT_UI,
                     bg=self.BG_SECONDARY, fg=dot_color).pack(side="left", padx=(10, 4), pady=8)

            label = user["nickname"]
            if user["username"] == room["coordinator"]:
                label += "  [COORD]"
            tk.Label(user_frame, text=label, font=self.FONT_UI,
                     bg=self.BG_SECONDARY, fg=self.TEXT_MAIN).pack(side="left", pady=8)

            if user["username"] in members:
                if user["username"] != self.username:
                    btn_kick = tk.Label(user_frame, text="KICK", font=self.FONT_LABEL,
                                        bg=self.BG_SECONDARY, fg=self.ERROR_COLOR, cursor="hand2")
                    btn_kick.pack(side="right", padx=10)
                    btn_kick.bind("<Button-1>", lambda e, u=user["username"]: self.coord_kick(room_id, u, panel))
                else:
                    tk.Label(user_frame, text="YOU", font=self.FONT_LABEL,
                             bg=self.BG_SECONDARY, fg=self.TEXT_MUTED).pack(side="right", padx=10)
            else:
                btn_add = tk.Label(user_frame, text="ADD", font=self.FONT_LABEL,
                                   bg=self.BG_SECONDARY, fg=self.ACCENT, cursor="hand2")
                btn_add.pack(side="right", padx=10)
                btn_add.bind("<Button-1>",
                             lambda e, u=user["username"], n=user["nickname"]: self.coord_add(room_id, u, n, panel))
                btn_add.bind("<Enter>", lambda e, b=btn_add: b.config(fg=self.ACCENT_HOVER))
                btn_add.bind("<Leave>", lambda e, b=btn_add: b.config(fg=self.ACCENT))

        tk.Frame(form, bg=self.BG_SECONDARY, height=1).pack(fill="x", pady=15)

        # --- DELETE ROOM ---
        btn_delete = tk.Label(form, text="⚠ DELETE ROOM", font=self.FONT_LABEL,
                              bg=self.BG_MAIN, fg=self.ERROR_COLOR, cursor="hand2")
        btn_delete.pack(anchor="w")
        btn_delete.bind("<Button-1>", lambda e: self.coord_delete_room(room_id, panel))

    # --- ACCIONES DEL COORDINADOR ---

    def coord_accept(self, room_id, username, panel):
        self.mock.accept_request(room_id, username)
        self.pending_rooms.discard(room_id)
        panel.destroy()
        self.show_chat_view(room_id)
        self.insert_system_message(f"{username} was accepted into the room.")
        self.open_coordinator_panel(room_id)

    def coord_reject(self, room_id, username, panel):
        self.mock.reject_request(room_id, username)
        self.pending_rooms.discard(room_id)
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
        if self.confirm_dialog("DELETE ROOM",
                               "Delete this room? This action cannot be undone.",
                               parent=panel):
            success = self.mock.delete_room(room_id)
            if success:
                panel.destroy()
                self.current_room = None
                self.refresh_sidebar()
                self.show_welcome_view()
            else:
                self.info_dialog("WARNING",
                                 "You can only delete a room when you are the last member.",
                                 parent=panel,
                                 color=self.WARNING_COLOR)
                panel.grab_set()
        else:
            panel.grab_set()

    # --- CREAR CHATROOM ---

    def open_create_room_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("CREATE ROOM")
        dialog.geometry("400x260")
        dialog.resizable(False, False)
        dialog.configure(bg=self.BG_MAIN)
        dialog.transient(self.root)
        dialog.grab_set()

        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() - 400) // 2
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
        entry_name.bind("<FocusIn>", lambda e: border.config(bg=self.ACCENT))
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
        btn.bind("<Enter>", lambda e: btn.config(bg=self.ACCENT_HOVER))
        btn.bind("<Leave>", lambda e: btn.config(bg=self.ACCENT))

    # --- REQUEST JOIN DESDE LA VISTA PRIVADA ---

    def request_join_from_view(self, room_id):
        success = self.mock.request_join(room_id)
        if success:
            # AQUÍ IRÍA: self.network.send("LOBBY_JOIN_REQUEST", room_id)
            self.pending_rooms.add(room_id)
            self.show_private_room_view(room_id)
        else:
            self.info_dialog("WARNING", "Could not send join request.",
                             color=self.WARNING_COLOR)

    # --- SELECCIÓN DE CANAL ---

    def on_channel_select(self, event):
        selection = self.channels_list.curselection()
        if not selection:
            return

        rooms = self.mock.get_rooms()
        if selection[0] >= len(rooms):
            return

        room = rooms[selection[0]]
        self.current_room = room["id"]

        if self.username not in room["members"]:
            self.show_private_room_view(room["id"])
        else:
            self.show_chat_view(room["id"])

        room["notifications"] = 0
        self.refresh_sidebar()

    # --- MENSAJES ---

    def insert_system_message(self, text):
        # Guardar en mock.messages con tag __SYSTEM__ para mantener orden cronológico
        # AQUÍ IRÍA: el backend mandaría este evento a todos los miembros de la sala
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
        # AQUÍ IRÍA: self.network.send_message(self.current_room, msg)
        self.mock.send_message(self.current_room, msg)
        self.chat_history.config(state="normal")
        self.chat_history.insert(tk.END, f"[{self.nickname}] ", "user")
        self.chat_history.insert(tk.END, f"{msg}\n", "msg")
        self.chat_history.config(state="disabled")
        self.chat_history.yview(tk.END)
        self.entry_msg.delete(0, tk.END)

    # --- PERFIL ---

    def open_profile(self):
        UserProfileWindow(self.root, username=self.username, current_nickname=self.nickname)


if __name__ == "__main__":
    root = tk.Tk()
    app = ChatClientGUI(root)
    root.mainloop()