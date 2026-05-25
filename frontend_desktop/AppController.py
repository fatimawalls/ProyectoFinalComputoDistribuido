import tkinter as tk
from tkinter import messagebox
from gui.views import LoginView, RegisterView
from gui.app import ChatClientGUI
from network.networkClient import NetworkClient


# --- CONTROLADOR PRINCIPAL DE LA APLICACIÓN ---
# Orquesta el flujo: Login → E-Lobby, Login → Registro → Login

class AppController:
    def __init__(self):
        # Cliente de red compartido en toda la app
        self.network = NetworkClient()

        # Datos del usuario autenticado (se llenan al hacer login o registro)
        self.current_user = None
        self.current_nick = None
        
        # Referencias a las ventanas activas para poder cerrarlas o interactuar
        self.login_window = None
        self.register_window = None
        self.root_window = None  # Almacenará la ventana del Lobby

        # --- ASIGNACIÓN DE CALLBACKS DE RED ---
        # Vinculamos las respuestas que lleguen del servidor C con funciones de este controlador
        self.network.on_login_response = self.on_login_response_received
        self.network.on_register_response = self.on_register_response_received

    def run(self):
        # Intentar conectar al backend en C inmediatamente al arrancar la app
        # Si tu equipo usa el puerto 5000, cámbialo aquí.
        print("[CONTROLADOR] Inicializando conexión con el Servidor C...")
        connected = self.network.connect("127.0.0.1", 5000)
        
        if not connected:
            # Creamos una ventana efímera solo para mostrar un mensaje de error crítico
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Error de Red", "No se pudo establecer conexión con el servidor de Chat (C).\nPor favor, verifica que el servidor esté encendido.")
            root.destroy()
            return

        # Punto de entrada si la red está arriba: arrancar con la pantalla de login
        self.show_login()

    # --- NAVEGACIÓN ---

    def show_login(self):
        # Guardamos la instancia de la vista para poder manipularla o cerrarla después
        self.login_window = LoginView(
            on_login_success=self.handle_login,
            on_go_register=self.show_register
        )

    def show_register(self):
        self.register_window = RegisterView(
            on_register_success=self.handle_register,
            on_go_login=self.show_login
        )

    def show_lobby(self):
        # Crear ventana principal del E-Lobby con los datos reales del usuario
        self.root_window = tk.Tk()
        
        # Instanciar la interfaz gráfica real del chat
        app = ChatClientGUI(
            self.root_window,
            username=self.current_user,
            nickname=self.current_nick or self.current_user
        )

        # ¡LIGADURA DE RED! Le inyectamos el cliente de red al chat para que pueda enviar mensajes reales
        # Nota: Asegúrate de que en gui.app.ChatClientGUI exista el método set_network o la propiedad.
        if hasattr(app, 'set_network'):
            app.set_network(self.network)
        else:
            # Si no tiene un método, se lo inyectamos directamente como propiedad
            app.network = self.network

        # Redirigir la recepción de mensajes nuevos del socket hacia la pantalla de chat
        self.network.on_message_received = app.on_message_received if hasattr(app, 'on_message_received') else None
        self.network.on_elobby_update = app.on_elobby_update if hasattr(app, 'on_elobby_update') else None

        self.root_window.mainloop()

    # --- ENVIOS AL BACKEND (DESDE LAS VISTAS) ---

    def handle_login(self, user, pwd):
        """Este método se dispara cuando el usuario da clic en el botón de la GUI de Login"""
        self.current_user = user
        
        # Enviamos la solicitud real de inicio de sesión por TCP hacia C
        self.network.login(user, pwd)
        print(f"[CONTROLADOR] Petición de login enviada para {user}. Esperando respuesta del servidor...")

    def handle_register(self, user, pwd, nick):
        """Este método se dispara cuando el usuario da clic en el botón de la GUI de Registro"""
        self.current_user = user
        self.current_nick = nick

        # Si en tu networkClient.py implementaste el método register:
        if hasattr(self.network, 'register'):
            self.network.register(user, pwd, nick)
        else:
            # Construcción manual en caso de que no esté en networkClient todavía:
            # "REQ_REGISTER|user|pwd|nick\n"
            from frontend_desktop.network.protocol import Protocol
            trama = f"{Protocol.REQ_REGISTER}{Protocol.SEPARATOR}{user}{Protocol.SEPARATOR}{pwd}{Protocol.SEPARATOR}{nick}{Protocol.TERMINATOR}"
            if self.network.socket:
                try:
                    self.network.socket.sendall(trama.encode(Protocol.ENCODING))
                except Exception as e:
                    print(f"[RED] Error al enviar registro: {e}")

        print(f"[CONTROLADOR] Petición de registro enviada para {user}. Esperando confirmación...")

    # --- RESPUESTAS ASÍNCRONAS DEL SERVIDOR C (VÍA NETWORK CLIENT) ---

    def on_login_response_received(self, success, message):
        """Procesa el resultado del login devuelto por el hilo de red"""
        # Explicación Técnica: Como esta función es invocada desde el hilo de red (Thread), 
        # usamos .after() para forzar a Tkinter a ejecutar el cambio de pantalla en el hilo principal de la UI.
        if self.login_window and hasattr(self.login_window, 'root'):
            self.login_window.root.after(0, lambda: self._safe_handle_login_ui(success, message))

    def _safe_handle_login_ui(self, success, message):
        if success:
            print("[CONTROLADOR] ¡Login validado por el servidor C! Abriendo Lobby...")
            # 1. Destruir la ventana de Login
            if self.login_window and hasattr(self.login_window, 'root'):
                self.login_window.root.destroy()
            
            # 2. Desplegar el Lobby del Chat
            self.show_lobby()
        else:
            print(f"[CONTROLADOR] Rechazo de Login: {message}")
            # Mostrar error en la ventana de login utilizando el label de error nativo si existe
            if self.login_window and hasattr(self.login_window, 'lbl_error'):
                self.login_window.lbl_error.config(text=f"◆ {message}")
            else:
                messagebox.showerror("Error de Autenticación", message)

    def on_register_response_received(self, success, message):
        """Procesa el resultado del registro devuelto por el hilo de red"""
        if self.register_window and hasattr(self.register_window, 'root'):
            self.register_window.root.after(0, lambda: self._safe_handle_register_ui(success, message))

    def _safe_handle_register_ui(self, success, message):
        if success:
            messagebox.showinfo("Registro Exitoso", "Tu cuenta ha sido creada en el servidor de C.\nAhora puedes iniciar sesión.")
            if self.register_window and hasattr(self.register_window, 'root'):
                self.register_window.root.destroy()
            self.show_login()
        else:
            if self.register_window and hasattr(self.register_window, 'lbl_error'):
                self.register_window.lbl_error.config(text=f"◆ {message}")
            else:
                messagebox.showerror("Error de Registro", message)


# --- PUNTO DE ENTRADA ---
if __name__ == "__main__":
    controller = AppController()
    controller.run()