class NetworkClient:
    def __init__(self):
        # Aquí el equipo de redes guardará su socket
        self.socket = None

        # --- CALLBACKS (La GUI inyectará funciones aquí) ---
        self.on_login_response = None  # func(success: bool, message: str)
        self.on_message_received = None  # func(room: str, sender: str, message: str)
        self.on_elobby_update = None  # func(users: list, rooms: list)

    # --- MÉTODOS QUE TU GUI VA A LLAMAR ---

    def connect(self, ip, port):
        print(f"[RED] Conectando a {ip}:{port}...")
        # El equipo de redes pondrá aquí: self.socket.connect(...)
        return True

    def login(self, username, password):
        print(f"[RED] Enviando login de: {username}")
        # Simulamos que el servidor responde que sí después de 1 segundo
        if self.on_login_response:
            self.on_login_response(True, "Login exitoso")

    def send_message(self, room, message):
        print(f"[RED] Enviando mensaje a {room}: {message}")
        # El equipo de red enviará el encode_for_c aquí

    def start_listening(self):
        print("[RED] Iniciando hilo para escuchar al servidor...")
        # El equipo de red pondrá aquí su threading.Thread