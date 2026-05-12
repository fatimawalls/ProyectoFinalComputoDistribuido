import tkinter as tk
from gui.views import LoginView, RegisterView
from gui.app import ChatClientGUI
from network.client import NetworkClient


# --- CONTROLADOR PRINCIPAL DE LA APLICACIÓN ---
# Orquesta el flujo: Login → E-Lobby, Login → Registro → Login

class AppController:
    def __init__(self):
        # Cliente de red compartido en toda la app
        self.network = NetworkClient()

        # Datos del usuario autenticado (se llenan al hacer login o registro)
        self.current_user = None
        self.current_nick = None

    def run(self):
        # Punto de entrada: arrancar con la pantalla de login
        self.show_login()

    # --- NAVEGACIÓN ---

    def show_login(self):
        LoginView(
            on_login_success=self.handle_login,
            on_go_register=self.show_register
        )

    def show_register(self):
        RegisterView(
            on_register_success=self.handle_register,
            on_go_login=self.show_login
        )

    def show_lobby(self):
        # Crear ventana principal del E-Lobby con los datos reales del usuario
        root = tk.Tk()
        ChatClientGUI(
            root,
            username=self.current_user,
            nickname=self.current_nick or self.current_user
        )

        # AQUÍ se inyectaría el cliente de red cuando el backend esté listo
        # app.set_network(self.network)

        root.mainloop()

    # --- CALLBACKS DE AUTENTICACIÓN ---

    def handle_login(self, user, pwd):
        # Login exitoso: guardar usuario y abrir E-Lobby
        self.current_user = user
        # Si no tiene nick guardado del registro, usar el username como nick
        if not self.current_nick:
            self.current_nick = user

        # AQUÍ IRÍA LA VERIFICACIÓN REAL CON EL BACKEND C
        # self.network.connect("127.0.0.1", 8080)
        # self.network.login(user, pwd)

        self.show_lobby()

    def handle_register(self, user, pwd, nick):
        # Registro exitoso: guardar datos y volver al login
        self.current_user = user
        self.current_nick = nick

        # AQUÍ IRÍA EL ENVÍO AL BACKEND C
        # self.network.register(user, pwd, nick)

        # Regresar al login para que el usuario inicie sesión
        self.show_login()


# --- PUNTO DE ENTRADA ---
if __name__ == "__main__":
    controller = AppController()
    controller.run()