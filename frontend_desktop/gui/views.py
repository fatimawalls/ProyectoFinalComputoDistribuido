import tkinter as tk
from tkinter import messagebox


# --- PALETA GLOBAL ---
BG_DARK      = "#0D0D0D"
BG_MAIN      = "#141414"
BG_SECONDARY = "#1E1E1E"
TEXT_MAIN    = "#E0E0E0"
TEXT_MUTED   = "#6B6B6B"
ACCENT       = "#2232E3"
ACCENT_HOVER = "#3A4BFF"
ERROR_COLOR  = "#E32222"

FONT_UI      = ("Segoe UI", 10)
FONT_UI_BOLD = ("Segoe UI", 10, "bold")
FONT_TITLE   = ("Segoe UI", 16, "bold")
FONT_SMALL   = ("Segoe UI", 9)
FONT_CODE    = ("Consolas", 11)
FONT_LABEL   = ("Segoe UI", 9, "bold")


def make_input_field(parent, label_text, show=None):
    tk.Label(parent, text=label_text, font=FONT_LABEL,
             bg=BG_MAIN, fg=ACCENT).pack(anchor="w", pady=(15, 0))

    border = tk.Frame(parent, bg=BG_SECONDARY, padx=2, pady=2)
    border.pack(fill="x", pady=(4, 0))

    entry = tk.Entry(border, font=FONT_CODE, bg=BG_SECONDARY,
                     fg=TEXT_MAIN, relief="flat", insertbackground=ACCENT,
                     highlightthickness=0, show=show)
    entry.pack(fill="x", ipady=10, padx=5)

    entry.bind("<FocusIn>",  lambda e: border.config(bg=ACCENT))
    entry.bind("<FocusOut>", lambda e: border.config(bg=BG_SECONDARY))
    return entry


def make_btn(parent, text, command, primary=True):
    bg    = ACCENT       if primary else BG_SECONDARY
    hover = ACCENT_HOVER if primary else "#252525"
    fg    = "#FFFFFF"    if primary else TEXT_MAIN

    btn = tk.Label(parent, text=text, font=FONT_UI_BOLD,
                   bg=bg, fg=fg, cursor="hand2")
    btn.bind("<Button-1>", lambda e: command())
    btn.bind("<Enter>",    lambda e: btn.config(bg=hover))
    btn.bind("<Leave>",    lambda e: btn.config(bg=bg))
    return btn


# ─────────────────────────────────────────────────────────────────
# LoginView  —  ahora es un Toplevel, no un Tk con mainloop propio
# ─────────────────────────────────────────────────────────────────

def _center_window(win, w, h):
    """Centra `win` en la pantalla tras que el WM aplique decoraciones."""
    def _do():
        win.update_idletasks()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        win.geometry(f"{w}x{h}+{x}+{y}")
    win.after(0, _do)


class LoginView(tk.Toplevel):
    """
    Ventana de login que vive como Toplevel hijo del root del AppController.
    No llama mainloop(); el loop pertenece al AppController.
    """

    def __init__(self, parent, on_login_success=None, on_go_register=None):
        super().__init__(parent)
        self.on_login_success = on_login_success
        self.on_go_register   = on_go_register

        self.title("PIMENTEL CO. // ACCESS")
        self.resizable(True, True)
        self.minsize(360, 480)
        self.configure(bg=BG_MAIN)

        _center_window(self, 460, 560)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()

    def _on_close(self):
        # Cierra la aplicación limpiamente si el usuario cierra el login
        self.master.destroy()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = tk.Frame(self, bg=BG_MAIN)
        header.pack(fill="x", padx=50, pady=(50, 0))

        tk.Label(header, text="PIMENTEL CO.", font=FONT_TITLE,
                 bg=BG_MAIN, fg=TEXT_MAIN, anchor="w").pack(fill="x")
        tk.Label(header, text="Secure Workspace Access", font=FONT_CODE,
                 bg=BG_MAIN, fg=TEXT_MUTED, anchor="w").pack(fill="x", pady=(4, 0))

        tk.Frame(self, bg=ACCENT, height=2).pack(fill="x", padx=50, pady=(20, 0))

        form = tk.Frame(self, bg=BG_MAIN, padx=50)
        form.pack(fill="both", expand=True, pady=10)
        form.columnconfigure(0, weight=1)

        self.entry_user = make_input_field(form, "USERNAME")
        self.entry_pass = make_input_field(form, "PASSWORD", show="●")

        self.lbl_error = tk.Label(form, text="", font=FONT_SMALL,
                                  bg=BG_MAIN, fg=ERROR_COLOR)
        self.lbl_error.pack(anchor="w", pady=(8, 0))

        self.entry_user.bind("<Return>", lambda e: self.entry_pass.focus())
        self.entry_pass.bind("<Return>", lambda e: self._do_login())

        btn_frame = tk.Frame(form, bg=BG_MAIN)
        btn_frame.pack(fill="x", pady=(25, 0))

        btn_login = make_btn(btn_frame, "CONNECT →", self._do_login, primary=True)
        btn_login.pack(fill="x", ipady=12)

        tk.Frame(form, bg=BG_SECONDARY, height=1).pack(fill="x", pady=20)

        link_frame = tk.Frame(form, bg=BG_MAIN)
        link_frame.pack()

        tk.Label(link_frame, text="No account?", font=FONT_SMALL,
                 bg=BG_MAIN, fg=TEXT_MUTED).pack(side="left")

        lbl_reg = tk.Label(link_frame, text="  REQUEST ACCESS", font=FONT_LABEL,
                           bg=BG_MAIN, fg=ACCENT, cursor="hand2")
        lbl_reg.pack(side="left")
        lbl_reg.bind("<Button-1>", lambda e: self._go_register())
        lbl_reg.bind("<Enter>",    lambda e: lbl_reg.config(fg=ACCENT_HOVER))
        lbl_reg.bind("<Leave>",    lambda e: lbl_reg.config(fg=ACCENT))

        tk.Label(self, text="v0.1.0 // DISTRIBUTED SYSTEM",
                 font=("Consolas", 8), bg=BG_MAIN, fg=TEXT_MUTED).pack(side="bottom", pady=15)

    def _do_login(self):
        user = self.entry_user.get().strip()
        pwd  = self.entry_pass.get().strip()

        if not user:
            self.show_error("Username cannot be empty.")
            self.entry_user.focus(); return
        if not pwd:
            self.show_error("Password cannot be empty.")
            self.entry_pass.focus(); return

        self.show_error("")
        if self.on_login_success:
            self.on_login_success(user, pwd)

    def _go_register(self):
        if self.on_go_register:
            self.on_go_register()   # AppController destruye y crea la ventana correcta

    def show_error(self, msg):
        self.lbl_error.config(text=f"◆ {msg}" if msg else "")


# ─────────────────────────────────────────────────────────────────
# RegisterView  —  también Toplevel
# ─────────────────────────────────────────────────────────────────

class RegisterView(tk.Toplevel):
    def __init__(self, parent, on_register_success=None, on_go_login=None):
        super().__init__(parent)
        self.on_register_success = on_register_success
        self.on_go_login         = on_go_login

        self.title("PIMENTEL CO. // NEW USER REGISTRATION")
        self.resizable(True, True)
        self.minsize(360, 580)
        self.configure(bg=BG_MAIN)

        _center_window(self, 460, 720)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()

    def _on_close(self):
        self.master.destroy()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = tk.Frame(self, bg=BG_MAIN)
        header.pack(fill="x", padx=50, pady=(45, 0))

        tk.Label(header, text="NEW OPERATOR", font=FONT_TITLE,
                 bg=BG_MAIN, fg=TEXT_MAIN, anchor="w").pack(fill="x")
        tk.Label(header, text="Register your credentials to access the system.",
                 font=FONT_CODE, bg=BG_MAIN, fg=TEXT_MUTED,
                 anchor="w", wraplength=360, justify="left").pack(fill="x", pady=(4, 0))

        tk.Frame(self, bg=ACCENT, height=2).pack(fill="x", padx=50, pady=(20, 0))

        form = tk.Frame(self, bg=BG_MAIN, padx=50)
        form.pack(fill="both", expand=True, pady=10)
        form.columnconfigure(0, weight=1)

        self.entry_user    = make_input_field(form, "USERNAME")
        self.entry_nick    = make_input_field(form, "DISPLAY NAME")
        self.entry_pass    = make_input_field(form, "PASSWORD", show="●")
        self.entry_confirm = make_input_field(form, "CONFIRM PASSWORD", show="●")

        self.lbl_error = tk.Label(form, text="", font=FONT_SMALL,
                                  bg=BG_MAIN, fg=ERROR_COLOR)
        self.lbl_error.pack(anchor="w", pady=(8, 0))

        self.entry_user.bind("<Return>",    lambda e: self.entry_nick.focus())
        self.entry_nick.bind("<Return>",    lambda e: self.entry_pass.focus())
        self.entry_pass.bind("<Return>",    lambda e: self.entry_confirm.focus())
        self.entry_confirm.bind("<Return>", lambda e: self._do_register())

        btn_frame = tk.Frame(form, bg=BG_MAIN)
        btn_frame.pack(fill="x", pady=(20, 0))

        btn_reg = make_btn(btn_frame, "CREATE ACCOUNT →", self._do_register, primary=True)
        btn_reg.pack(fill="x", ipady=12)

        tk.Frame(form, bg=BG_SECONDARY, height=1).pack(fill="x", pady=20)

        link_frame = tk.Frame(form, bg=BG_MAIN)
        link_frame.pack()

        tk.Label(link_frame, text="Already registered?", font=FONT_SMALL,
                 bg=BG_MAIN, fg=TEXT_MUTED).pack(side="left")

        lbl_login = tk.Label(link_frame, text="  SIGN IN", font=FONT_LABEL,
                             bg=BG_MAIN, fg=ACCENT, cursor="hand2")
        lbl_login.pack(side="left")
        lbl_login.bind("<Button-1>", lambda e: self._go_login())
        lbl_login.bind("<Enter>",    lambda e: lbl_login.config(fg=ACCENT_HOVER))
        lbl_login.bind("<Leave>",    lambda e: lbl_login.config(fg=ACCENT))

        tk.Label(self, text="v0.1.0 // DISTRIBUTED SYSTEM",
                 font=("Consolas", 8), bg=BG_MAIN, fg=TEXT_MUTED).pack(side="bottom", pady=15)

    def _do_register(self):
        user    = self.entry_user.get().strip()
        nick    = self.entry_nick.get().strip()
        pwd     = self.entry_pass.get().strip()
        confirm = self.entry_confirm.get().strip()

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
        if self.on_register_success:
            self.on_register_success(user, pwd, nick)

    def _go_login(self):
        if self.on_go_login:
            self.on_go_login()

    def show_error(self, msg):
        self.lbl_error.config(text=f"◆ {msg}" if msg else "")


# Modo standalone para pruebas sin backend
if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    LoginView(parent=root)
    root.mainloop()