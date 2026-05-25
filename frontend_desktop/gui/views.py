import tkinter as tk
from tkinter import messagebox


# --- PALETA GLOBAL (Sincronizada con app.py y user_profile.py) ---
BG_DARK      = "#0D0D0D"
BG_MAIN      = "#141414"
BG_SECONDARY = "#1E1E1E"
TEXT_MAIN    = "#E0E0E0"
TEXT_MUTED   = "#6B6B6B"
ACCENT       = "#2232E3"
ACCENT_HOVER = "#3A4BFF"
ERROR_COLOR  = "#E32222"

# --- TIPOGRAFÍA REFINADA (Sincronizada con app.py) ---
FONT_UI      = ("Segoe UI", 10)
FONT_UI_BOLD = ("Segoe UI", 10, "bold")
FONT_TITLE   = ("Segoe UI", 16, "bold")
FONT_SMALL   = ("Segoe UI", 9)
FONT_CODE    = ("Consolas", 11)
FONT_LABEL   = ("Segoe UI", 9, "bold")


# --- HELPERS DE UI (Reutilizables en LoginView y RegisterView) ---

def make_input_field(parent, label_text, show=None):
    # Label de sección en azul accent
    tk.Label(parent, text=label_text, font=FONT_LABEL,
             bg=BG_MAIN, fg=ACCENT).pack(anchor="w", pady=(15, 0))

    # Borde falso iluminado (mismo truco que en app.py)
    border = tk.Frame(parent, bg=BG_SECONDARY, padx=2, pady=2)
    border.pack(fill="x", pady=(4, 0))

    entry = tk.Entry(border, font=FONT_CODE, bg=BG_SECONDARY,
                     fg=TEXT_MAIN, relief="flat", insertbackground=ACCENT,
                     highlightthickness=0, show=show)
    entry.pack(fill="x", ipady=10, padx=5)

    # Efecto visual al enfocar: borde se vuelve azul
    entry.bind("<FocusIn>",  lambda e: border.config(bg=ACCENT))
    entry.bind("<FocusOut>", lambda e: border.config(bg=BG_SECONDARY))

    return entry


def make_btn(parent, text, command, primary=True):
    # Fix macOS: tk.Label en vez de tk.Button para respetar el color de fondo
    bg    = ACCENT       if primary else BG_SECONDARY
    hover = ACCENT_HOVER if primary else "#252525"
    fg    = "#FFFFFF"    if primary else TEXT_MAIN

    btn = tk.Label(parent, text=text, font=FONT_UI_BOLD,
                   bg=bg, fg=fg, cursor="hand2")

    # Efecto hover manual (igual que en app.py)
    btn.bind("<Button-1>", lambda e: command())
    btn.bind("<Enter>",    lambda e: btn.config(bg=hover))
    btn.bind("<Leave>",    lambda e: btn.config(bg=bg))
    return btn


# --- VENTANA DE LOGIN ---

class LoginView:
    def __init__(self, on_login_success=None, on_go_register=None):
        self.on_login_success = on_login_success
        self.on_go_register   = on_go_register

        self.root = tk.Tk()
        self.root.title("PIMENTEL CO. // ACCESS")
        self.root.geometry("460x560")
        self.root.resizable(False, False)
        self.root.configure(bg=BG_MAIN)

        # Centrar la ventana en pantalla
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth()  - 460) // 2
        y = (self.root.winfo_screenheight() - 560) // 2
        self.root.geometry(f"460x560+{x}+{y}")

        self.build_ui()
        self.root.mainloop()

    def build_ui(self):
        # --- HEADER ---
        header = tk.Frame(self.root, bg=BG_MAIN)
        header.pack(fill="x", padx=50, pady=(50, 0))

        tk.Label(header, text="PIMENTEL CO.", font=FONT_TITLE,
                 bg=BG_MAIN, fg=TEXT_MAIN, anchor="w").pack(fill="x")

        tk.Label(header, text="Secure Workspace Access", font=FONT_CODE,
                 bg=BG_MAIN, fg=TEXT_MUTED, anchor="w").pack(fill="x", pady=(4, 0))

        # Línea separadora azul de marca
        tk.Frame(self.root, bg=ACCENT, height=2).pack(fill="x", padx=50, pady=(20, 0))

        # --- FORMULARIO ---
        form = tk.Frame(self.root, bg=BG_MAIN, padx=50)
        form.pack(fill="both", expand=True, pady=10)

        self.entry_user = make_input_field(form, "USERNAME")
        self.entry_pass = make_input_field(form, "PASSWORD", show="●")

        # Label de error (oculto por defecto)
        self.lbl_error = tk.Label(form, text="", font=FONT_SMALL,
                                  bg=BG_MAIN, fg=ERROR_COLOR)
        self.lbl_error.pack(anchor="w", pady=(8, 0))

        # Enter flow: usuario → contraseña → login
        self.entry_user.bind("<Return>", lambda e: self.entry_pass.focus())
        self.entry_pass.bind("<Return>", lambda e: self.do_login())

        # --- BOTONES ---
        btn_frame = tk.Frame(form, bg=BG_MAIN)
        btn_frame.pack(fill="x", pady=(25, 0))

        btn_login = make_btn(btn_frame, "CONNECT →", self.do_login, primary=True)
        btn_login.pack(fill="x", ipady=12)

        # Línea divisoria suave
        tk.Frame(form, bg=BG_SECONDARY, height=1).pack(fill="x", pady=20)

        # Link hacia registro
        link_frame = tk.Frame(form, bg=BG_MAIN)
        link_frame.pack()

        tk.Label(link_frame, text="No account?", font=FONT_SMALL,
                 bg=BG_MAIN, fg=TEXT_MUTED).pack(side="left")

        lbl_reg = tk.Label(link_frame, text="  REQUEST ACCESS", font=FONT_LABEL,
                           bg=BG_MAIN, fg=ACCENT, cursor="hand2")
        lbl_reg.pack(side="left")
        lbl_reg.bind("<Button-1>", lambda e: self.go_register())
        lbl_reg.bind("<Enter>",    lambda e: lbl_reg.config(fg=ACCENT_HOVER))
        lbl_reg.bind("<Leave>",    lambda e: lbl_reg.config(fg=ACCENT))

        # --- FOOTER ---
        tk.Label(self.root, text="v0.1.0 // DISTRIBUTED SYSTEM",
                 font=("Consolas", 8), bg=BG_MAIN, fg=TEXT_MUTED).pack(side="bottom", pady=15)

    def do_login(self):
        user = self.entry_user.get().strip()
        pwd  = self.entry_pass.get().strip()

        # Validación básica en cliente
        if not user:
            self.show_error("Username cannot be empty.")
            self.entry_user.focus(); return
        if not pwd:
            self.show_error("Password cannot be empty.")
            self.entry_pass.focus(); return

        self.show_error("")

        # AQUÍ IRÍA LA CONEXIÓN AL BACKEND C
        # data = encode_for_c("AUTH_LOGIN", user, pwd)
        # self.network_client.send(data)
        if self.on_login_success:
            # Modo controlado: destruir esta ventana y pasar el control al AppController
            self.root.destroy()
            self.on_login_success(user, pwd)
        else:
            # Modo standalone: demo sin backend
            messagebox.showinfo("ACCESS GRANTED",
                                f"Welcome, {user}.\nRedirecting to E-Lobby...",
                                parent=self.root)

    def go_register(self):
        if self.on_go_register:
            # Modo controlado: destruir esta ventana y dejar que AppController abra el registro
            self.root.destroy()
            self.on_go_register()
        else:
            # Modo standalone: navegar directamente
            self.root.destroy()
            RegisterView()

    def show_error(self, msg):
        self.lbl_error.config(text=f"◆ {msg}" if msg else "")


# --- VENTANA DE REGISTRO ---

class RegisterView:
    def __init__(self, on_register_success=None, on_go_login=None):
        self.on_register_success = on_register_success
        self.on_go_login         = on_go_login

        self.root = tk.Tk()
        self.root.title("PIMENTEL CO. // NEW USER REGISTRATION")
        self.root.geometry("460x660")
        self.root.resizable(False, False)
        self.root.configure(bg=BG_MAIN)

        # Centrar la ventana en pantalla
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth()  - 460) // 2
        y = (self.root.winfo_screenheight() - 660) // 2
        self.root.geometry(f"460x660+{x}+{y}")

        self.build_ui()
        self.root.mainloop()

    def build_ui(self):
        # --- HEADER ---
        header = tk.Frame(self.root, bg=BG_MAIN)
        header.pack(fill="x", padx=50, pady=(45, 0))

        tk.Label(header, text="NEW OPERATOR", font=FONT_TITLE,
                 bg=BG_MAIN, fg=TEXT_MAIN, anchor="w").pack(fill="x")

        tk.Label(header, text="Register your credentials to access the system.",
                 font=FONT_CODE, bg=BG_MAIN, fg=TEXT_MUTED,
                 anchor="w", wraplength=360, justify="left").pack(fill="x", pady=(4, 0))

        # Línea separadora azul de marca
        tk.Frame(self.root, bg=ACCENT, height=2).pack(fill="x", padx=50, pady=(20, 0))

        # --- FORMULARIO ---
        form = tk.Frame(self.root, bg=BG_MAIN, padx=50)
        form.pack(fill="both", expand=True, pady=10)

        self.entry_user    = make_input_field(form, "USERNAME")
        self.entry_nick    = make_input_field(form, "DISPLAY NAME")
        self.entry_pass    = make_input_field(form, "PASSWORD", show="●")
        self.entry_confirm = make_input_field(form, "CONFIRM PASSWORD", show="●")

        # Label de error (oculto por defecto)
        self.lbl_error = tk.Label(form, text="", font=FONT_SMALL,
                                  bg=BG_MAIN, fg=ERROR_COLOR)
        self.lbl_error.pack(anchor="w", pady=(8, 0))

        # Enter flow: user → nick → pass → confirm → register
        self.entry_user.bind("<Return>",    lambda e: self.entry_nick.focus())
        self.entry_nick.bind("<Return>",    lambda e: self.entry_pass.focus())
        self.entry_pass.bind("<Return>",    lambda e: self.entry_confirm.focus())
        self.entry_confirm.bind("<Return>", lambda e: self.do_register())

        # --- BOTONES ---
        btn_frame = tk.Frame(form, bg=BG_MAIN)
        btn_frame.pack(fill="x", pady=(20, 0))

        btn_reg = make_btn(btn_frame, "CREATE ACCOUNT →", self.do_register, primary=True)
        btn_reg.pack(fill="x", ipady=12)

        # Línea divisoria suave
        tk.Frame(form, bg=BG_SECONDARY, height=1).pack(fill="x", pady=20)

        # Link de regreso al login
        link_frame = tk.Frame(form, bg=BG_MAIN)
        link_frame.pack()

        tk.Label(link_frame, text="Already registered?", font=FONT_SMALL,
                 bg=BG_MAIN, fg=TEXT_MUTED).pack(side="left")

        lbl_login = tk.Label(link_frame, text="  SIGN IN", font=FONT_LABEL,
                             bg=BG_MAIN, fg=ACCENT, cursor="hand2")
        lbl_login.pack(side="left")
        lbl_login.bind("<Button-1>", lambda e: self.go_login())
        lbl_login.bind("<Enter>",    lambda e: lbl_login.config(fg=ACCENT_HOVER))
        lbl_login.bind("<Leave>",    lambda e: lbl_login.config(fg=ACCENT))

        # --- FOOTER ---
        tk.Label(self.root, text="v0.1.0 // DISTRIBUTED SYSTEM",
                 font=("Consolas", 8), bg=BG_MAIN, fg=TEXT_MUTED).pack(side="bottom", pady=15)

    def do_register(self):
        user    = self.entry_user.get().strip()
        nick    = self.entry_nick.get().strip()
        pwd     = self.entry_pass.get().strip()
        confirm = self.entry_confirm.get().strip()

        # Validaciones del lado cliente
        if not user:
            self.show_error("Username cannot be empty.")
            self.entry_user.focus(); return
        if len(user) < 3:
            self.show_error("Username must be at least 3 characters.")
            self.entry_user.focus(); return
        if not nick:
            self.show_error("Display name cannot be empty.")
            self.entry_nick.focus(); return
        if not pwd:
            self.show_error("Password cannot be empty.")
            self.entry_pass.focus(); return
        if len(pwd) < 6:
            self.show_error("Password must be at least 6 characters.")
            self.entry_pass.focus(); return
        if pwd != confirm:
            self.show_error("Passwords do not match.")
            self.entry_confirm.delete(0, tk.END)
            self.entry_confirm.focus(); return

        self.show_error("")

        # AQUÍ IRÍA LA CONEXIÓN AL BACKEND C
        # data = encode_for_c("AUTH_REGISTER", user, pwd, nick)
        # self.network_client.send(data)
        if self.on_register_success:
            # Modo controlado: destruir esta ventana y pasar el control al AppController
            self.root.destroy()
            self.on_register_success(user, pwd, nick)
        else:
            # Modo standalone: demo sin backend
            messagebox.showinfo("ACCOUNT CREATED",
                                f"Welcome, {nick}.\nYou can now sign in.",
                                parent=self.root)
            self.go_login()

    def go_login(self):
        if self.on_go_login:
            # Modo controlado: destruir esta ventana y dejar que AppController abra el login
            self.root.destroy()
            self.on_go_login()
        else:
            # Modo standalone: navegar directamente
            self.root.destroy()
            LoginView()

    def show_error(self, msg):
        self.lbl_error.config(text=f"◆ {msg}" if msg else "")


# Para probar este archivo solo
if __name__ == "__main__":
    LoginView()