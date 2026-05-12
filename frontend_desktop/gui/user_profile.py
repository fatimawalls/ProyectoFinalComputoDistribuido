import tkinter as tk
from tkinter import messagebox


class UserProfileWindow:
    def __init__(self, parent, username, current_nickname):
        # 1. Corrección Técnica: Guardar referencia del padre para evitar problemas de memoria
        self.parent = parent

        # 2. Crear Toplevel correctamente
        self.window = tk.Toplevel(parent)
        self.window.title("SYS // PROFILE // " + username.upper())
        self.window.geometry("420x550")
        self.window.resizable(False, False)

        # 3. Estilo y Protocolos
        self.window.transient(parent)  # Vincula a la ventana principal
        self.window.wait_visibility()
        self.window.grab_set()  # Bloquea la principal (Modal)
        self.window.focus_set()  # Da el foco a esta ventana

        # Al cerrar con la 'X', liberar el grab_set correctamente
        self.window.protocol("WM_DELETE_WINDOW", self.on_close)

        # --- PALETA DE COLORES REFINADA (Sincronizada con app.py) ---
        self.BG_MAIN = "#141414"
        self.BG_SECONDARY = "#1E1E1E"
        self.TEXT_MAIN = "#E0E0E0"
        self.TEXT_MUTED = "#6B6B6B"
        self.ACCENT = "#2232E3"
        self.ACCENT_HOVER = "#3A4BFF"

        # Tipografía
        self.FONT_TITLE = ("Segoe UI", 16, "bold")
        self.FONT_NICK = ("Segoe UI", 20, "bold")  # Nombre grande
        self.FONT_LABEL = ("Segoe UI", 9, "bold")
        self.FONT_INPUT = ("Consolas", 11)
        self.FONT_AVATAR = ("Segoe UI", 40, "bold")

        self.window.configure(bg=self.BG_MAIN)

        # Datos
        self.username = username
        self.nickname = current_nickname

        self.build_ui()

    def build_ui(self):
        # --- CABECERA (Área del Avatar y Nombre) ---
        header = tk.Frame(self.window, bg=self.BG_MAIN, pady=30)
        header.pack(fill="x")

        # EL "ENCHULE": Avatar Circular Simulado con Canvas
        avatar_size = 100
        self.canvas = tk.Canvas(header, width=avatar_size, height=avatar_size,
                                bg=self.BG_MAIN, highlightthickness=0)
        self.canvas.pack()

        # Dibujar Círculo Azul de Fondo
        self.canvas.create_oval(2, 2, avatar_size - 2, avatar_size - 2,
                                fill=self.ACCENT, outline=self.ACCENT)

        # Dibujar Inicial del Nickname en Blanco
        inicial = self.nickname[0].upper() if self.nickname else "?"
        self.canvas.create_text(avatar_size / 2, avatar_size / 2, text=inicial,
                                fill="#FFFFFF", font=self.FONT_AVATAR)

        # Nombre del usuario (Nickname) en GRANDE
        tk.Label(header, text=self.nickname, font=self.FONT_NICK,
                 bg=self.BG_MAIN, fg=self.TEXT_MAIN).pack(pady=(15, 0))

        # Username del sistema (Muted)
        tk.Label(header, text=f"@{self.username}", font=self.FONT_INPUT,
                 bg=self.BG_MAIN, fg=self.TEXT_MUTED).pack()

        # Línea divisoria suave
        tk.Frame(self.window, bg=self.BG_SECONDARY, height=1).pack(fill="x", padx=40)

        # --- FORMULARIO DE EDICIÓN ---
        form_frame = tk.Frame(self.window, bg=self.BG_MAIN, padx=40, pady=30)
        form_frame.pack(fill="both", expand=True)

        # Campo: Editar Nickname
        tk.Label(form_frame, text="EDIT DISPLAY NAME", font=self.FONT_LABEL,
                 bg=self.BG_MAIN, fg=self.ACCENT).pack(anchor="w")

        # Contenedor de Input "Enchulado" (Borde azul falso)
        border_frame = tk.Frame(form_frame, bg=self.BG_SECONDARY, bd=0, padx=2, pady=2)
        border_frame.pack(fill="x", pady=(5, 30))

        # Eventos para cambiar el color del borde al enfocar (Efecto tecnológico)
        def on_entry_in(e): border_frame.config(bg=self.ACCENT)

        def on_entry_out(e): border_frame.config(bg=self.BG_SECONDARY)

        self.entry_nickname = tk.Entry(border_frame, font=self.FONT_INPUT, bg=self.BG_SECONDARY,
                                       fg=self.TEXT_MAIN, relief="flat", insertbackground=self.ACCENT,
                                       highlightthickness=0)
        self.entry_nickname.pack(fill="x", ipady=10, padx=5)
        self.entry_nickname.insert(0, self.nickname)

        self.entry_nickname.bind("<FocusIn>", on_entry_in)
        self.entry_nickname.bind("<FocusOut>", on_entry_out)

        # --- BOTONES DE ACCIÓN ---
        btn_frame = tk.Frame(form_frame, bg=self.BG_MAIN)
        btn_frame.pack(fill="x", side="bottom", pady=10)

        # Botón Guardar (Azul Plano)
        btn_save = tk.Button(btn_frame, text="SAVE CHANGES", font=self.FONT_LABEL,
                             bg=self.ACCENT, fg="#FFFFFF", relief="flat", cursor="hand2",
                             activebackground=self.ACCENT_HOVER, activeforeground="#FFFFFF",
                             command=self.save_profile, bd=0)
        btn_save.pack(side="right", ipadx=20, ipady=12)

        # Botón Cancelar (Gris Plano)
        btn_cancel = tk.Button(btn_frame, text="CANCEL", font=self.FONT_LABEL,
                               bg=self.BG_SECONDARY, fg=self.TEXT_MAIN, relief="flat", cursor="hand2",
                               activebackground="#333333", activeforeground=self.TEXT_MAIN,
                               command=self.on_close, bd=0)
        btn_cancel.pack(side="right", padx=15, ipadx=20, ipady=12)

    def save_profile(self):
        new_nick = self.entry_nickname.get().strip()
        if not new_nick:
            messagebox.showwarning("Warning", "Nickname cannot be empty.", parent=self.window)
            return

        # AQUÍ IRÍA LA CONEXIÓN AL BACKEND C
        # data = encode_for_c("UPDATE_PROFILE", new_nick)
        # self.parent.network_client.send(data)

        messagebox.showinfo("Success", f"Profile updated to: {new_nick}", parent=self.window)
        # Nota: En una app real, actualizaríamos el label en app.py antes de cerrar
        self.on_close()

    def on_close(self):
        """Libera el grab_set y cierra la ventana"""
        self.window.grab_release()
        self.window.destroy()

    # Para probar este archivo solo


if __name__ == "__main__":
    root = tk.Tk()
    root.configure(bg="#141414")

    # Simular botón en la principal
    tk.Button(root, text="Open Profile Demo",
              command=lambda: UserProfileWindow(root, "jperez_root", "jperez.sys")).pack(pady=50, padx=50)

    root.mainloop()