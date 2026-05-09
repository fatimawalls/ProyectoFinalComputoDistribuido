import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from user_profile import UserProfileWindow

class ChatClientGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("PIMENTEL CO. // WORKSPACE")
        self.root.geometry("1050x700")

        # --- PALETA REFINADA ---
        self.BG_DARK = "#0D0D0D"  # Negro casi absoluto para el sidebar
        self.BG_MAIN = "#141414"  # Gris extremadamente oscuro para el fondo
        self.BG_SECONDARY = "#1E1E1E"  # Gris oscuro para áreas de texto
        self.TEXT_MAIN = "#E0E0E0"  # Blanco roto (no lastima la vista)
        self.TEXT_MUTED = "#6B6B6B"  # Gris para texto secundario
        self.ACCENT = "#2232E3"  # Tu azul tecnológico
        self.ACCENT_HOVER = "#3A4BFF"  # Azul más claro para el hover

        # --- TIPOGRAFÍA REFINADA ---
        self.FONT_UI = ("Segoe UI", 10)  # Limpia y moderna para menús
        self.FONT_UI_BOLD = ("Segoe UI", 10, "bold")
        self.FONT_TITLE = ("Segoe UI", 16, "bold")
        self.FONT_CODE = ("Consolas", 11)  # Estilo terminal para el chat

        self.nickname = "jperez.sys"
        self.root.configure(bg=self.BG_MAIN)

        self.build_ui()

    def build_ui(self):
        # --- SIDEBAR (Minimalista) ---
        sidebar = tk.Frame(self.root, bg=self.BG_DARK, width=260)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        # Header
        header_frame = tk.Frame(sidebar, bg=self.BG_DARK)
        header_frame.pack(fill="x", padx=25, pady=30)

        tk.Label(header_frame, text="PIMENTEL CO.", font=self.FONT_TITLE,
                 bg=self.BG_DARK, fg=self.TEXT_MAIN, anchor="w").pack(fill="x")

        # Línea separadora azul muy sutil
        tk.Frame(sidebar, bg=self.ACCENT, height=2).pack(fill="x", padx=25, pady=(0, 20))

        # Canales
        tk.Label(sidebar, text="CHANNELS", font=self.FONT_UI_BOLD,
                 bg=self.BG_DARK, fg=self.TEXT_MUTED, anchor="w").pack(fill="x", padx=25, pady=(10, 5))

        self.channels_list = tk.Listbox(sidebar, bg=self.BG_DARK, fg=self.TEXT_MAIN,
                                        bd=0, highlightthickness=0,
                                        selectbackground=self.ACCENT, selectforeground="#FFFFFF",
                                        font=self.FONT_CODE, height=8, activestyle="none")
        self.channels_list.pack(fill="x", padx=15)

        self.channels_list.insert(tk.END, " # general")
        self.channels_list.insert(tk.END, " # root-access  [1]")
        self.channels_list.insert(tk.END, " # dev-ops      [3]")
        self.channels_list.bind('<<ListboxSelect>>', self.on_channel_select)

        # Directorio
        tk.Label(sidebar, text="DIRECTORY", font=self.FONT_UI_BOLD,
                 bg=self.BG_DARK, fg=self.TEXT_MUTED, anchor="w").pack(fill="x", padx=25, pady=(30, 5))

        self.users_list = tk.Listbox(sidebar, bg=self.BG_DARK, fg=self.TEXT_MUTED,
                                     bd=0, highlightthickness=0,
                                     selectbackground=self.BG_SECONDARY, selectforeground=self.TEXT_MAIN,
                                     font=self.FONT_UI, height=10, activestyle="none")
        self.users_list.pack(fill="x", padx=15)
        for u in ["Maria_P", "Admin_Root", "Juan_Dev"]: self.users_list.insert(tk.END, f"  ●  {u}")

        # Perfil inferior flotante
        self.user_panel = tk.Frame(sidebar, bg=self.BG_SECONDARY, cursor="hand2")
        self.user_panel.pack(side="bottom", fill="x", padx=15, pady=15)

        self.user_label = tk.Label(self.user_panel, text=f"● {self.nickname}",
                                   font=self.FONT_UI_BOLD, bg=self.BG_SECONDARY,
                                   fg=self.ACCENT, anchor="w", pady=10)
        self.user_label.pack(side="left", padx=15)

        # Bindings para abrir el perfil al hacer clic
        self.user_panel.bind("<Button-1>", lambda e: self.open_profile())
        self.user_label.bind("<Button-1>", lambda e: self.open_profile())

        # Efecto visual al pasar el mouse (opcional para el "enchule")
        self.user_panel.bind("<Enter>", lambda e: self.user_panel.config(bg="#252525"))
        self.user_panel.bind("<Leave>", lambda e: self.user_panel.config(bg=self.BG_SECONDARY))

        # --- PANEL PRINCIPAL ---
        self.main_panel = tk.Frame(self.root, bg=self.BG_MAIN)
        self.main_panel.pack(side="right", fill="both", expand=True)

        self.show_welcome_view()

    # --- VISTAS ---
    def clear_main_panel(self):
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

    def show_chat_view(self, channel_name):
        self.clear_main_panel()

        # Cabecera Refinada (Separada del contenido principal)
        header = tk.Frame(self.main_panel, bg=self.BG_MAIN, pady=20)
        header.pack(fill="x", padx=30)

        tk.Label(header, text=f"{channel_name.strip()}", font=self.FONT_TITLE,
                 bg=self.BG_MAIN, fg=self.TEXT_MAIN).pack(side="left")

        # Botón de sistema estilizado
        btn_manage = tk.Label(header, text="⚙ Manage Room", font=self.FONT_UI_BOLD,
                              bg=self.BG_MAIN, fg=self.ACCENT, cursor="hand2")
        btn_manage.pack(side="right")
        # Efecto hover manual para el Label
        btn_manage.bind("<Enter>", lambda e: btn_manage.config(fg=self.ACCENT_HOVER))
        btn_manage.bind("<Leave>", lambda e: btn_manage.config(fg=self.ACCENT))

        # Línea divisoria suave
        tk.Frame(self.main_panel, bg=self.BG_SECONDARY, height=1).pack(fill="x", padx=30)

        # Historial de Chat
        chat_frame = tk.Frame(self.main_panel, bg=self.BG_MAIN)
        chat_frame.pack(fill="both", expand=True, padx=30, pady=20)

        self.chat_history = scrolledtext.ScrolledText(chat_frame, bg=self.BG_MAIN, fg=self.TEXT_MAIN,
                                                      bd=0, font=self.FONT_CODE, wrap="word",
                                                      highlightthickness=0, spacing1=5, spacing3=5)
        self.chat_history.pack(fill="both", expand=True)
        self.chat_history.vbar.configure(width=10)  # Hace el scrollbar nativo un poco más fino

        self.chat_history.tag_config("system", foreground=self.ACCENT, font=("Consolas", 10, "italic"))
        self.chat_history.tag_config("user", foreground=self.TEXT_MUTED, font=("Consolas", 11, "bold"))
        self.chat_history.tag_config("msg", foreground=self.TEXT_MAIN)

        self.insert_system_message("Connected to node.")
        self.insert_system_message(f"Admin_Root joined.")

        # --- ÁREA DE INPUT REFINADA (Borde falso iluminado) ---
        input_container = tk.Frame(self.main_panel, bg=self.BG_MAIN, pady=20)
        input_container.pack(fill="x", padx=30, side="bottom")

        # Borde exterior azul claro que contiene el Entry
        border_frame = tk.Frame(input_container, bg=self.ACCENT, bd=0, padx=1, pady=1)
        border_frame.pack(side="left", fill="x", expand=True)

        self.entry_msg = tk.Entry(border_frame, font=self.FONT_CODE, bg=self.BG_SECONDARY,
                                  fg=self.TEXT_MAIN, relief="flat", bd=0, highlightthickness=0,
                                  insertbackground=self.ACCENT)
        self.entry_msg.pack(fill="both", expand=True, ipady=12, padx=10)
        self.entry_msg.bind("<Return>", lambda e: self.send_message())

        # Botón de enviar plano
        send_btn = tk.Button(input_container, text="SEND", font=self.FONT_UI_BOLD,
                             bg=self.ACCENT, fg="#FFFFFF", relief="flat", bd=0, cursor="hand2",
                             activebackground=self.ACCENT_HOVER, activeforeground="#FFFFFF",
                             command=self.send_message, width=12)
        send_btn.pack(side="right", padx=(15, 0), ipady=10)

    def open_profile(self):
        """Lanza la ventana de perfil importada de user_profile.py"""
        # Le pasamos 'self.root' como padre, el username real y el nickname actual
        UserProfileWindow(self.root, username="jperez_root", current_nickname=self.nickname)

    # --- LÓGICA ---
    def on_channel_select(self, event):
        selection = self.channels_list.curselection()
        if selection:
            name = self.channels_list.get(selection[0])
            self.show_chat_view(name)

    def insert_system_message(self, text):
        self.chat_history.config(state='normal')
        self.chat_history.insert(tk.END, f"◆ {text}\n", "system")
        self.chat_history.config(state='disabled')
        self.chat_history.yview(tk.END)

    def send_message(self):
        msg = self.entry_msg.get()
        if msg:
            self.chat_history.config(state='normal')
            self.chat_history.insert(tk.END, f"[{self.nickname}] ", "user")
            self.chat_history.insert(tk.END, f"{msg}\n", "msg")
            self.chat_history.config(state='disabled')
            self.chat_history.yview(tk.END)
            self.entry_msg.delete(0, tk.END)

if __name__ == "__main__":
    root = tk.Tk()
    app = ChatClientGUI(root)
    root.mainloop()