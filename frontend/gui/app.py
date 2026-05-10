import tkinter as tk
from tkinter import messagebox, scrolledtext
from gui.user_profile import UserProfileWindow
from gui.mock_data import MockServer


class ChatClientGUI:
    def __init__(self, root, username="jperez_root", nickname="jperez.sys"):
        self.root = root
        self.root.title("PIMENTEL CO. // WORKSPACE")
        self.root.geometry("1050x700")

        # --- PALETA REFINADA ---
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

        # --- TIPOGRAFÍA REFINADA ---
        self.FONT_UI      = ("Segoe UI", 10)
        self.FONT_UI_BOLD = ("Segoe UI", 10, "bold")
        self.FONT_TITLE   = ("Segoe UI", 16, "bold")
        self.FONT_CODE    = ("Consolas", 11)
        self.FONT_LABEL   = ("Segoe UI", 9, "bold")
        self.FONT_SMALL   = ("Segoe UI", 9)

        # --- SESIÓN Y DATOS ---
        self.username      = username
        self.nickname      = nickname
        self.current_room  = None
        self.chat_history  = None  # Referencia al widget activo de chat
        self.system_log    = {}    # Persiste mensajes de sistema por sala entre recargas
        self.pending_rooms = set() # Salas donde el usuario ya mandó solicitud

        # MockServer simula el backend — reemplazar por NetworkClient cuando esté listo
        # AQUÍ IRÍA: self.network = NetworkClient(); self.network.connect(IP, PORT)
        self.mock = MockServer(current_user=username, current_nick=nickname)

        self.root.configure(bg=self.BG_MAIN)
        self.build_ui()

    def build_ui(self):
        # --- SIDEBAR ---
        self.sidebar = tk.Frame(self.root, bg=self.BG_DARK, width=260)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Header
        header_frame = tk.Frame(self.sidebar, bg=self.BG_DARK)
        header_frame.pack(fill="x", padx=25, pady=30)

        tk.Label(header_frame, text="PIMENTEL CO.", font=self.FONT_TITLE,
                 bg=self.BG_DARK, fg=self.TEXT_MAIN, anchor="w").pack(fill="x")

        # Línea separadora azul
        tk.Frame(self.sidebar, bg=self.ACCENT, height=2).pack(fill="x", padx=25, pady=(0, 20))

        # --- SECCIÓN CHANNELS ---
        channels_header = tk.Frame(self.sidebar, bg=self.BG_DARK)
        channels_header.pack(fill="x", padx=25, pady=(10, 5))

        tk.Label(channels_header, text="CHANNELS", font=self.FONT_UI_BOLD,
                 bg=self.BG_DARK, fg=self.TEXT_MUTED, anchor="w").pack(side="left")

        # Botón + para crear chatroom
        btn_create = tk.Label(channels_header, text="＋", font=self.FONT_UI_BOLD,
                              bg=self.BG_DARK, fg=self.ACCENT, cursor="hand2")
        btn_create.pack(side="right")
        btn_create.bind("<Button-1>", lambda e: self.open_create_room_dialog())
        btn_create.bind("<Enter>",    lambda e: btn_create.config(fg=self.ACCENT_HOVER))
        btn_create.bind("<Leave>",    lambda e: btn_create.config(fg=self.ACCENT))

        # Lista de canales
        self.channels_list = tk.Listbox(self.sidebar, bg=self.BG_DARK, fg=self.TEXT_MAIN,
                                        bd=0, highlightthickness=0,
                                        selectbackground=self.ACCENT, selectforeground="#FFFFFF",
                                        font=self.FONT_CODE, height=8, activestyle="none")
        self.channels_list.pack(fill="x", padx=15)
        self.channels_list.bind("<<ListboxSelect>>", self.on_channel_select)

        # --- SECCIÓN DIRECTORY ---
        tk.Label(self.sidebar, text="DIRECTORY", font=self.FONT_UI_BOLD,
                 bg=self.BG_DARK, fg=self.TEXT_MUTED, anchor="w").pack(fill="x", padx=25, pady=(25, 5))

        self.users_list = tk.Listbox(self.sidebar, bg=self.BG_DARK, fg=self.TEXT_MUTED,
                                     bd=0, highlightthickness=0,
                                     selectbackground=self.BG_SECONDARY, selectforeground=self.TEXT_MAIN,
                                     font=self.FONT_UI, height=8, activestyle="none")
        self.users_list.pack(fill="x", padx=15)

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

        # Cargar datos y mostrar bienvenida
        self.refresh_sidebar()
        self.show_welcome_view()

    # --- REFRESH DE DATOS ---

    def refresh_sidebar(self):
        # Actualizar lista de canales con datos del mock (o backend cuando esté listo)
        self.channels_list.delete(0, tk.END)
        for room in self.mock.get_rooms():
            notif = room["notifications"]
            label = f" # {room['name']}"
            if notif > 0:
                label += f"  [{notif}]"
            self.channels_list.insert(tk.END, label)

        # Actualizar directorio de usuarios
        self.users_list.delete(0, tk.END)
        for user in self.mock.get_online_users():
            self.users_list.insert(tk.END, f"  ●  {user['nickname']}")

    # --- VISTAS ---

    def clear_main_panel(self):
        self.chat_history = None  # Limpiar referencia al chat anterior
        for widget in self.main_panel.winfo_children():
            widget.destroy()

    def show_welcome_view(self):
        self.clear_main_panel()
        frame = tk.Frame(self.main_panel, bg=self.BG_MAIN)
        frame.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(frame, text="SECURE CONNECTION ESTABLISHED", font=self.FONT_UI_BOLD,
                 bg=self.BG_MAIN, fg=self.ACCENT).pack(pady=5)
        tk.Label(frame, text="Select a workspace channel to begin.",
                 font=self.FONT_UI, bg=self.BG_MAIN, fg=self.TEXT_MUTED).pack(pady=10)

    def show_private_room_view(self, room_id):
        # Vista para salas donde el usuario no es miembro
        self.clear_main_panel()
        self.current_room = room_id
        room      = self.mock.get_room(room_id)
        is_pending = room_id in self.pending_rooms

        frame = tk.Frame(self.main_panel, bg=self.BG_MAIN)
        frame.place(relx=0.5, rely=0.5, anchor="center")

        # Nombre de la sala
        tk.Label(frame, text=f"# {room['name']}", font=self.FONT_TITLE,
                 bg=self.BG_MAIN, fg=self.TEXT_MAIN).pack()

        tk.Label(frame, text="This channel is private.", font=self.FONT_CODE,
                 bg=self.BG_MAIN, fg=self.TEXT_MUTED).pack(pady=(8, 0))

        # Línea divisoria
        tk.Frame(frame, bg=self.BG_SECONDARY, height=1, width=300).pack(pady=25)

        if is_pending:
            # Estado pendiente: ya mandó solicitud
            tk.Label(frame, text="REQUEST PENDING", font=self.FONT_UI_BOLD,
                     bg=self.BG_MAIN, fg=self.WARNING_COLOR).pack(pady=5)
            tk.Label(frame, text="Waiting for the coordinator to accept your request.",
                     font=self.FONT_SMALL, bg=self.BG_MAIN, fg=self.TEXT_MUTED).pack()
        else:
            # Botón de solicitud
            tk.Label(frame, text="You need coordinator approval to join this channel.",
                     font=self.FONT_SMALL, bg=self.BG_MAIN, fg=self.TEXT_MUTED).pack(pady=(0, 20))

            btn = tk.Label(frame, text="  REQUEST ACCESS →  ", font=self.FONT_UI_BOLD,
                           bg=self.ACCENT, fg="#FFFFFF", cursor="hand2")
            btn.pack(ipady=12, ipadx=10)
            btn.bind("<Button-1>", lambda e: self.request_join_from_view(room_id, frame))
            btn.bind("<Enter>",    lambda e: btn.config(bg=self.ACCENT_HOVER))
            btn.bind("<Leave>",    lambda e: btn.config(bg=self.ACCENT))

    def show_chat_view(self, room_id):
        self.clear_main_panel()
        self.current_room = room_id
        room     = self.mock.get_room(room_id)
        is_coord = self.mock.is_coordinator(room_id)

        # --- CABECERA ---
        header = tk.Frame(self.main_panel, bg=self.BG_MAIN, pady=20)
        header.pack(fill="x", padx=30)

        tk.Label(header, text=f"# {room['name']}", font=self.FONT_TITLE,
                 bg=self.BG_MAIN, fg=self.TEXT_MAIN).pack(side="left")

        # Botón Manage Room (solo si es coordinador)
        if is_coord:
            requests_count = len(self.mock.get_join_requests(room_id))
            manage_text    = "⚙ Manage Room" + (f"  [{requests_count}]" if requests_count > 0 else "")
            btn_manage = tk.Label(header, text=manage_text, font=self.FONT_UI_BOLD,
                                  bg=self.BG_MAIN, fg=self.ACCENT, cursor="hand2")
            btn_manage.pack(side="right")
            btn_manage.bind("<Button-1>", lambda e: self.open_coordinator_panel(room_id))
            btn_manage.bind("<Enter>",    lambda e: btn_manage.config(fg=self.ACCENT_HOVER))
            btn_manage.bind("<Leave>",    lambda e: btn_manage.config(fg=self.ACCENT))

        # Indicador de rol
        role_text  = "COORDINATOR" if is_coord else "MEMBER"
        role_color = self.ACCENT if is_coord else self.TEXT_MUTED
        tk.Label(header, text=role_text, font=self.FONT_LABEL,
                 bg=self.BG_MAIN, fg=role_color).pack(side="right", padx=(0, 20))

        # Línea divisoria
        tk.Frame(self.main_panel, bg=self.BG_SECONDARY, height=1).pack(fill="x", padx=30)

        # --- INPUT (pack ANTES que el historial para garantizar visibilidad) ---
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
        send_btn.bind("<Enter>",    lambda e: send_btn.config(bg=self.ACCENT_HOVER))
        send_btn.bind("<Leave>",    lambda e: send_btn.config(bg=self.ACCENT))

        # --- HISTORIAL DE CHAT (pack DESPUÉS para que el input tenga prioridad de espacio) ---
        chat_frame = tk.Frame(self.main_panel, bg=self.BG_MAIN)
        chat_frame.pack(fill="both", expand=True, padx=30, pady=(20, 0))

        self.chat_history = scrolledtext.ScrolledText(chat_frame, bg=self.BG_MAIN, fg=self.TEXT_MAIN,
                                                      bd=0, font=self.FONT_CODE, wrap="word",
                                                      highlightthickness=0, spacing1=5, spacing3=5)
        self.chat_history.pack(fill="both", expand=True)
        self.chat_history.vbar.configure(width=10)

        self.chat_history.tag_config("system", foreground=self.ACCENT, font=("Consolas", 10, "italic"))
        self.chat_history.tag_config("user",   foreground=self.TEXT_MUTED, font=("Consolas", 11, "bold"))
        self.chat_history.tag_config("msg",    foreground=self.TEXT_MAIN)

        # Cargar historial completo
        self._load_chat_history(room_id)

        # Fix macOS: forzar foco al input con delay
        self.root.after(150, self.entry_msg.focus_force)

    def _load_chat_history(self, room_id):
        # Mensaje inicial de conexión
        self.chat_history.config(state="normal")
        self.chat_history.insert(tk.END, "◆ Connected to node.\n", "system")
        self.chat_history.config(state="disabled")

        # Mensajes de chat del mock
        for sender, text in self.mock.get_messages(room_id):
            self.chat_history.config(state="normal")
            self.chat_history.insert(tk.END, f"[{sender}] ", "user")
            self.chat_history.insert(tk.END, f"{text}\n", "msg")
            self.chat_history.config(state="disabled")

        # Restaurar mensajes de sistema previos guardados en system_log
        for log_msg in self.system_log.get(room_id, []):
            self.chat_history.config(state="normal")
            self.chat_history.insert(tk.END, f"◆ {log_msg}\n", "system")
            self.chat_history.config(state="disabled")

        self.chat_history.yview(tk.END)

    # --- PANEL DEL COORDINADOR ---

    def open_coordinator_panel(self, room_id):
        room = self.mock.get_room(room_id)

        panel = tk.Toplevel(self.root)
        panel.title(f"MANAGE // {room['name'].upper()}")
        panel.geometry("420x580")
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

        # Línea divisoria
        tk.Frame(form, bg=self.BG_SECONDARY, height=1).pack(fill="x", pady=15)

        # --- MIEMBROS ---
        tk.Label(form, text="MEMBERS", font=self.FONT_LABEL,
                 bg=self.BG_MAIN, fg=self.ACCENT).pack(anchor="w", pady=(0, 5))

        for member in self.mock.get_members(room_id):
            mem_frame = tk.Frame(form, bg=self.BG_SECONDARY)
            mem_frame.pack(fill="x", pady=3)

            label = f"  ● {member}"
            if member == room["coordinator"]:
                label += "  [COORD]"
            tk.Label(mem_frame, text=label, font=self.FONT_UI,
                     bg=self.BG_SECONDARY, fg=self.TEXT_MAIN).pack(side="left", padx=10, pady=8)

            if member != self.username:
                btn_kick = tk.Label(mem_frame, text="KICK", font=self.FONT_LABEL,
                                    bg=self.BG_SECONDARY, fg=self.ERROR_COLOR, cursor="hand2")
                btn_kick.pack(side="right", padx=10)
                btn_kick.bind("<Button-1>", lambda e, u=member: self.coord_kick(room_id, u, panel))

        # Línea divisoria
        tk.Frame(form, bg=self.BG_SECONDARY, height=1).pack(fill="x", pady=15)

        # --- DELETE ROOM ---
        btn_delete = tk.Label(form, text="⚠ DELETE ROOM", font=self.FONT_LABEL,
                              bg=self.BG_MAIN, fg=self.ERROR_COLOR, cursor="hand2")
        btn_delete.pack(anchor="w")
        btn_delete.bind("<Button-1>", lambda e: self.coord_delete_room(room_id, panel))

    # --- ACCIONES DEL COORDINADOR ---

    def coord_accept(self, room_id, username, panel):
        self.mock.accept_request(room_id, username)
        # Quitar del estado pendiente si el usuario aceptado era el actual
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
        confirm = messagebox.askyesno("KICK USER",
                                      f"Remove {username} from the room?",
                                      parent=panel)
        if confirm:
            self.mock.kick_user(room_id, username)
            panel.destroy()
            self.show_chat_view(room_id)
            self.insert_system_message(f"{username} was removed from the room.")
            self.open_coordinator_panel(room_id)

    def coord_delete_room(self, room_id, panel):
        confirm = messagebox.askyesno("DELETE ROOM",
                                      "Delete this room? This action cannot be undone.",
                                      parent=panel)
        if confirm:
            success = self.mock.delete_room(room_id)
            if success:
                panel.destroy()
                self.current_room = None
                self.system_log.pop(room_id, None)  # Limpiar log de sala borrada
                self.refresh_sidebar()
                self.show_welcome_view()
            else:
                messagebox.showwarning("WARNING",
                                       "You can only delete a room when you are the last member.",
                                       parent=panel)

    # --- CREAR CHATROOM ---

    def open_create_room_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("CREATE ROOM")
        dialog.geometry("400x260")
        dialog.resizable(False, False)
        dialog.configure(bg=self.BG_MAIN)
        dialog.transient(self.root)
        dialog.grab_set()

        # Centrar en pantalla
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

        # Fix macOS: forzar foco con delay para que el dialog esté listo
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
            # Navegar a la nueva sala para mostrar el mensaje ahí
            self.show_chat_view(room_id)
            self.insert_system_message(f"Room '{name}' created. You are the coordinator.")

        entry_name.bind("<Return>", lambda e: do_create())

        btn = tk.Label(form, text="CREATE →", font=self.FONT_UI_BOLD,
                       bg=self.ACCENT, fg="#FFFFFF", cursor="hand2")
        btn.pack(fill="x", ipady=10, pady=(20, 0))
        btn.bind("<Button-1>", lambda e: do_create())
        btn.bind("<Enter>",    lambda e: btn.config(bg=self.ACCENT_HOVER))
        btn.bind("<Leave>",    lambda e: btn.config(bg=self.ACCENT))

    # --- REQUEST JOIN DESDE LA VISTA PRIVADA ---

    def request_join_from_view(self, room_id, frame):
        room    = self.mock.get_room(room_id)
        success = self.mock.request_join(room_id)

        if success:
            # Marcar como pendiente y refrescar la vista
            self.pending_rooms.add(room_id)
            self.show_private_room_view(room_id)
        else:
            messagebox.showwarning("WARNING", "Could not send join request.", parent=self.root)

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

        # Mostrar vista privada si no es miembro, chat si ya pertenece
        if self.username not in room["members"]:
            self.show_private_room_view(room["id"])
        else:
            self.show_chat_view(room["id"])

        # Limpiar notificaciones al entrar
        room["notifications"] = 0
        self.refresh_sidebar()

    # --- MENSAJES ---

    def insert_system_message(self, text):
        # Solo escribe si hay un chat activo
        if self.chat_history is None:
            return

        # Guardar en el log de la sala actual para persistir entre recargas
        if self.current_room not in self.system_log:
            self.system_log[self.current_room] = []
        self.system_log[self.current_room].append(text)

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
        # Lanza la ventana de perfil importada de user_profile.py
        UserProfileWindow(self.root, username=self.username, current_nickname=self.nickname)


if __name__ == "__main__":
    root = tk.Tk()
    app = ChatClientGUI(root)
    root.mainloop()