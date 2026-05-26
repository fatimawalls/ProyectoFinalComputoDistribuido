import tkinter as tk
from tkinter import messagebox
from gui.views import LoginView, RegisterView
from gui.app import ChatClientGUI
from network.networkClient import NetworkClient

C_SERVER_IP   = "192.168.68.118"
C_SERVER_PORT = 5006


class AppController:
    def __init__(self):
        self.network = NetworkClient()
        self.current_user = None

        self.login_window    = None
        self.register_window = None

        # ── Ventana raíz ÚNICA — vive toda la sesión ─────────────────
        self.root = tk.Tk()
        self.root.withdraw()          # invisible hasta que haya algo que mostrar

        # Callbacks de autenticación y ciclo de vida
        self.network.on_login_response      = self.on_login_response_received
        self.network.on_register_response   = self.on_register_response_received
        self.network.on_sync_complete       = self.on_sync_complete_received
        self.network.on_server_disconnected = self.on_server_disconnected

    # ─────────────────────────────────────────────────────────────
    # ARRANQUE
    # ─────────────────────────────────────────────────────────────

    def run(self):
        self.show_login()
        self.root.mainloop()   # ← UN SOLO mainloop, aquí y en ningún otro lado

    # ─────────────────────────────────────────────────────────────
    # NAVEGACIÓN
    # ─────────────────────────────────────────────────────────────

    def show_login(self):
        # Cerrar registro si estaba abierto
        if self.register_window:
            try:
                self.register_window.destroy()
            except Exception:
                pass
            self.register_window = None

        self.login_window = LoginView(
            parent=self.root,
            on_login_success=self.handle_login,
            on_go_register=self.show_register,
        )

    def show_register(self):
        # Cerrar login si estaba abierto
        if self.login_window:
            try:
                self.login_window.destroy()
            except Exception:
                pass
            self.login_window = None

        self.register_window = RegisterView(
            parent=self.root,
            on_register_success=self.handle_register,
            on_go_login=self.show_login,
        )

    def show_lobby(self):
        # Cerrar login si aún existe
        if self.login_window:
            try:
                self.login_window.destroy()
            except Exception:
                pass
            self.login_window = None

        username = self.network.me.get("username", self.current_user or "")

        # Reutilizamos self.root como ventana principal del lobby
        self.root.deiconify()

        app = ChatClientGUI(
            self.root,
            username=username,
            nickname=username,
            network=self.network,
        )

        # Conectar callbacks en tiempo real hacia la GUI
        self.network.on_new_message         = getattr(app, "on_new_message",     None)
        self.network.on_room_created        = getattr(app, "on_room_created",    None)
        self.network.on_user_added          = getattr(app, "on_user_added",      None)
        self.network.on_user_removed        = getattr(app, "on_user_removed",    None)
        self.network.on_message_deleted     = getattr(app, "on_message_deleted", None)
        self.network.on_room_deleted        = getattr(app, "on_room_deleted",    None)
        self.network.on_server_disconnected = self.on_server_disconnected

    # ─────────────────────────────────────────────────────────────
    # ENVÍOS DESDE LAS VISTAS
    # ─────────────────────────────────────────────────────────────

    def _conectar(self) -> bool:
        if self.network.connected:
            return True
        print(f"[CONTROLADOR] Conectando a {C_SERVER_IP}:{C_SERVER_PORT}...")
        ok = self.network.connect(C_SERVER_IP, C_SERVER_PORT)
        if not ok:
            self._mostrar_error_red()
        return ok

    def _mostrar_error_red(self):
        ventana = self.login_window or self.register_window
        if ventana and hasattr(ventana, "lbl_error"):
            ventana.lbl_error.config(text="◆ No se pudo conectar al servidor.")
        else:
            messagebox.showerror(
                "Error de Red",
                f"No se pudo conectar a {C_SERVER_IP}:{C_SERVER_PORT}.\n"
                "Verifica que el servidor esté encendido.",
                parent=self.root,
            )

    def handle_login(self, user, pwd):
        self.current_user = user
        if not self._conectar():
            return
        self.network.login(user, pwd)
        print(f"[CONTROLADOR] AUTH enviado para '{user}'. Esperando respuesta...")

    def handle_register(self, user, pwd, nick=None):
        self.current_user = user
        if not self._conectar():
            return
        self.network.register(user, pwd)
        print(f"[CONTROLADOR] CREATE_ACCOUNT enviado para '{user}'.")

    # ─────────────────────────────────────────────────────────────
    # CALLBACKS ASÍNCRONOS  (hilo de red → .after() → hilo principal)
    # ─────────────────────────────────────────────────────────────

    def on_login_response_received(self, success, message):
        self.root.after(0, lambda: self._safe_handle_login_ui(success, message))

    def _safe_handle_login_ui(self, success, message):
        if success:
            print("[CONTROLADOR] Login OK — esperando sync...")
            if self.login_window and hasattr(self.login_window, "lbl_error"):
                self.login_window.lbl_error.config(text="◆ Conectado. Cargando datos...")
        else:
            print(f"[CONTROLADOR] Login rechazado: {message}")
            self.network.connected = False
            if self.login_window and hasattr(self.login_window, "lbl_error"):
                self.login_window.lbl_error.config(text=f"◆ {message}")
            else:
                messagebox.showerror("Error de Autenticación", message, parent=self.root)

    def on_sync_complete_received(self):
        print("[CONTROLADOR] Sync completo → abriendo Lobby")
        self.root.after(0, self.show_lobby)

    def on_register_response_received(self, success, user_id, username):
        self.root.after(0, lambda: self._safe_handle_register_ui(success, user_id, username))

    def _safe_handle_register_ui(self, success, user_id, username):
        if success:
            messagebox.showinfo(
                "Registro Exitoso",
                f"Cuenta '{username}' creada (ID: {user_id}).\nAhora puedes iniciar sesión.",
                parent=self.root,
            )
            if self.register_window:
                try:
                    self.register_window.destroy()
                except Exception:
                    pass
            self.register_window = None
            self.network.connected = False
            self.show_login()
        else:
            msg = "El usuario ya existe o hubo un error en el servidor."
            if self.register_window and hasattr(self.register_window, "lbl_error"):
                self.register_window.lbl_error.config(text=f"◆ {msg}")
            else:
                messagebox.showerror("Error de Registro", msg, parent=self.root)
            self.network.connected = False

    def on_server_disconnected(self):
        print("[CONTROLADOR] Desconectado del servidor.")
        self.root.after(
            0,
            lambda: messagebox.showerror(
                "Conexión perdida",
                "Se perdió la conexión con el servidor.\nReinicia la aplicación.",
                parent=self.root,
            ),
        )


if __name__ == "__main__":
    controller = AppController()
    controller.run()
