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

        # Datos del usuario autenticado
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
        # Crear ventana principal del E-Lobby y arrancar su mainloop
        root = tk.Tk()
        app = ChatClientGUI(root)

        # AQUÍ se inyectarían los datos del usuario real al lobby
        # app.set_user(self.current_user, self.current_nick)
        # app.set_network(self.network)

        root.mainloop()

    # --- CALLBACKS DE AUTENTICACIÓN ---

    def handle_login(self, user, pwd):
        # Login exitoso: guardar sesión y abrir el E-Lobby
        self.current_user = user

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