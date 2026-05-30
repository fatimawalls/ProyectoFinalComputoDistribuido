import sys
import tkinter as tk
from tkinter import messagebox
from gui.views import LoginView, RegisterView
from gui.app import ChatClientGUI
from network.networkClient import NetworkClient

# Valores por defecto de respaldo
C_SERVER_IP   = "127.0.0.1"
C_SERVER_PORT = 5006

# Load Balancer opcional.
# Si USE_LOAD_BALANCER=True, el cliente pregunta al LB a qué chat server conectarse.
USE_LOAD_BALANCER = True
LB_IP   = "127.0.0.1"
LB_PORT = 4000


class AppController:
    def __init__(
        self,
        server_ip=C_SERVER_IP,
        server_port=C_SERVER_PORT,
        use_load_balancer=USE_LOAD_BALANCER,
        lb_ip=LB_IP,
        lb_port=LB_PORT,
    ):
        self.network = NetworkClient()
        self.current_user = None

        # ── Guardamos los parámetros dinámicos de conexión ────────────
        self.server_ip = server_ip
        self.server_port = server_port
        self.use_load_balancer = use_load_balancer
        self.lb_ip = lb_ip
        self.lb_port = lb_port

        self.login_window    = None
        self.register_window = None

        # Guard: evita que show_lobby se ejecute más de una vez por sesión
        self._lobby_shown = False

        # ── Ventana raíz ÚNICA — vive toda la sesión ─────────────────
        self.root = tk.Tk()
        self.root.withdraw()          # Invisible hasta que haya algo que mostrar

        # Callbacks de autenticación y ciclo de vida de la red
        self.network.on_login_response      = self.on_login_response_received
        self.network.on_register_response   = self.on_register_response_received
        self.network.on_sync_complete       = self.on_sync_complete_received
        self.network.on_server_disconnected = self.on_server_disconnected

        self.network.on_user_online         = self.on_user_online_received
        self.network.on_user_offline        = self.on_user_offline_received

    # ─────────────────────────────────────────────────────────────
    # ARRANQUE DEL CONTROLLER
    # ─────────────────────────────────────────────────────────────

    def run(self):
        self.show_login()
        self.root.mainloop()   # ← UN SOLO mainloop en toda la aplicación

    # ─────────────────────────────────────────────────────────────
    # NAVEGACIÓN ENTRE VENTANAS
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
        # Guard: si el lobby ya fue construido, ignorar llamadas duplicadas
        if self._lobby_shown:
            print("[CONTROLADOR] show_lobby ignorado — lobby ya activo (sync duplicado del servidor)")
            return
        self._lobby_shown = True

        # Cerrar login si aún existe activo
        if self.login_window:
            try:
                self.login_window.destroy()
            except Exception:
                pass
            self.login_window = None

        username = self.network.me.get("username", self.current_user or "")

        # Reutilizamos la ventana raíz principal de Tkinter para el lobby
        self.root.deiconify()

        app = ChatClientGUI(
            self.root,
            username=username,
            nickname=username,
            network=self.network,
        )

        # Guardar la referencia a la GUI para refrescos asíncronos
        self._app = app

        # Conectar callbacks en tiempo real de mensajería hacia la GUI
        self.network.on_new_message         = getattr(app, "on_new_message",     None)
        self.network.on_room_created        = getattr(app, "on_room_created",    None)
        self.network.on_user_added          = getattr(app, "on_user_added",      None)
        self.network.on_user_removed        = getattr(app, "on_user_removed",    None)
        self.network.on_message_deleted     = getattr(app, "on_message_deleted", None)
        self.network.on_room_deleted        = getattr(app, "on_room_deleted",    None)
        self.network.on_server_disconnected = self.on_server_disconnected
        self.network.on_user_offline        = self.on_user_offline_received

    # ─────────────────────────────────────────────────────────────
    # PETICIONES Y CONEXIÓN DE RED (MÉTODOS INTERNOS)
    # ─────────────────────────────────────────────────────────────

    def _conectar(self) -> bool:
        if self.network.connected:
            return True

        target_ip = self.server_ip
        target_port = self.server_port

        if self.use_load_balancer:
            assignment = self.network.ask_loadbalancer(self.lb_ip, self.lb_port)

            if assignment is None:
                self._mostrar_error_red(
                    extra=f"No se pudo obtener servidor desde Load Balancer {self.lb_ip}:{self.lb_port}."
                )
                return False

            target_ip, target_port = assignment
            print(f"[CONTROLADOR] LB asignó chat server {target_ip}:{target_port}")

        print(f"[CONTROLADOR] Conectando a {target_ip}:{target_port}...")
        ok = self.network.connect(target_ip, target_port)

        if not ok:
            self._mostrar_error_red(
                extra=f"No se pudo conectar a {target_ip}:{target_port}."
            )

        return ok

    def _mostrar_error_red(self, extra=None):
        ventana = self.login_window or self.register_window
        msg = extra or (
            f"No se pudo conectar a {self.server_ip}:{self.server_port}.\n"
            "Verifica que el servidor esté encendido."
        )

        if ventana and hasattr(ventana, "lbl_error"):
            ventana.lbl_error.config(text=f"◆ {msg}")
        else:
            messagebox.showerror(
                "Error de Red",
                msg,
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
        self.network.register(user, pwd, nick)
        print(f"[CONTROLADOR] CREATE_ACCOUNT enviado para '{user}' con nickname '{nick or user}'.")

    # ─────────────────────────────────────────────────────────────
    # CALLBACKS ASÍNCRONOS (Hilos de Red ──> .after() ──> Hilo Principal GUI)
    # ─────────────────────────────────────────────────────────────

    def on_login_response_received(self, success, message):
        self.root.after(0, lambda: self._safe_handle_login_ui(success, message))

    def _safe_handle_login_ui(self, success, message):
        if success:
            print("[CONTROLADOR] Login OK — esperando sincronización de datos...")
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
        """
        El sync inicial ya trae TODO:
        - usuarios
        - salas
        - mensajes

        Por eso ya no se hacen GET_USERS ni GET_ROOMS.
        """
        print("[CONTROLADOR] Sync completo → abriendo lobby con la base local cargada")
        self.root.after(0, self._try_open_lobby)

    def _try_open_lobby(self):
        """Abre el lobby de la app sólo cuando ambas listas están cargadas."""
        if self._lobby_shown:
            if hasattr(self, '_app') and self._app is not None:
                try:
                    self._app.refresh_sidebar()
                except Exception:
                    pass
            return
        self.show_lobby()

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

    # ─────────────────────────────────────────────────────────────
    # EVENTOS PUSH EN TIEMPO REAL
    # ─────────────────────────────────────────────────────────────

    def on_user_online_received(self, user_id, username):
        """Notificación push cuando un usuario se conecta en red."""
        self.root.after(0, self._safe_refresh_sidebar)

    def on_user_offline_received(self, user_id, username):
        """Notificación push cuando un usuario se desconecta."""
        self.root.after(0, self._safe_refresh_sidebar)

    def _safe_refresh_sidebar(self):
        """Refresca de manera segura el sidebar de la GUI si está activo."""
        if hasattr(self, '_app') and self._app is not None:
            try:
                self._app.refresh_sidebar()
            except Exception as e:
                print(f"[CONTROLADOR] Error al refrescar sidebar: {e}")

    def on_server_disconnected(self):
        print("[CONTROLADOR] Desconectado del servidor.")
        self.root.after(
            0,
            lambda: messagebox.showerror(
                "Conexión perdida",
                "Se perdió la conexión con el servidor de chat.\nPor favor, reinicia la aplicación.",
                parent=self.root,
            ),
        )


# ─────────────────────────────────────────────────────────────
# BLOQUE PRINCIPAL DE EJECUCIÓN (ENTRY POINT)
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    server_ip = C_SERVER_IP
    server_port = C_SERVER_PORT
    use_lb = USE_LOAD_BALANCER
    lb_ip = LB_IP
    lb_port = LB_PORT

    # Uso:
    #   python AppController.py
    #   python AppController.py --no-lb 127.0.0.1 5006
    #   python AppController.py --lb 127.0.0.1 4000
    args = sys.argv[1:]

    if args and args[0] == "--no-lb":
        use_lb = False
        args = args[1:]

        if len(args) > 0:
            server_ip = args[0]
        if len(args) > 1:
            try:
                server_port = int(args[1])
            except ValueError:
                print(f"[ERROR] El puerto '{args[1]}' debe ser entero. Usando {server_port}")

    elif args and args[0] == "--lb":
        use_lb = True
        args = args[1:]

        if len(args) > 0:
            lb_ip = args[0]
        if len(args) > 1:
            try:
                lb_port = int(args[1])
            except ValueError:
                print(f"[ERROR] El puerto LB '{args[1]}' debe ser entero. Usando {lb_port}")

    elif args:
        # Compatibilidad vieja: si pasan IP/puerto, conectamos directo.
        use_lb = False
        server_ip = args[0]
        if len(args) > 1:
            try:
                server_port = int(args[1])
            except ValueError:
                print(f"[ERROR] El puerto '{args[1]}' debe ser entero. Usando {server_port}")

    if use_lb:
        print(f"[CONTROLADOR] Usando Load Balancer {lb_ip}:{lb_port}")
    else:
        print(f"[CONTROLADOR] Conexión directa a {server_ip}:{server_port}")

    controller = AppController(
        server_ip=server_ip,
        server_port=server_port,
        use_load_balancer=use_lb,
        lb_ip=lb_ip,
        lb_port=lb_port,
    )
    controller.run()
