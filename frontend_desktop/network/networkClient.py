import socket
import threading
from .protocol import Protocol

class NetworkClient:
    def __init__(self):
        self.socket = None
        self.connected = False
        self.buffer = ""  # Buffer para acumular datos parciales de TCP

        # --- CALLBACKS (La GUI inyectará sus funciones aquí para reaccionar) ---
        self.on_login_response = None     # func(success: bool, message: str)
        self.on_register_response = None  # func(success: bool, message: str)
        self.on_message_received = None   # func(room: str, sender: str, message: str)
        self.on_elobby_update = None      # func(users: list, rooms: list)

    def connect(self, ip="127.0.0.1", port=5000):
        """Establece la conexión TCP con el servidor en C"""
        print(f"[RED] Conectando a {ip}:{port}...")
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((ip, port))
            self.connected = True
            print("[RED] ¡Conexión establecida con el servidor C!")
            
            # Arrancar inmediatamente el hilo de escucha asíncrono
            self.start_listening()
            return True
        except Exception as e:
            print(f"[RED] Error al conectar: {e}")
            self.connected = False
            return False

    def login(self, username, password):
        """Envía la petición de Login usando el formato del protocolo"""
        if not self.connected:
            print("[RED] Error: No conectado al servidor.")
            return
        
        print(f"[RED] Enviando login de: {username}")
        # Construye la trama: "REQ_LOGIN|username|password\n"
        trama = f"{Protocol.REQ_LOGIN}{Protocol.SEPARATOR}{username}{Protocol.SEPARATOR}{password}{Protocol.TERMINATOR}"
        try:
            self.socket.sendall(trama.encode(Protocol.ENCODING))
        except Exception as e:
            print(f"[RED] Error al enviar login: {e}")

    def send_message(self, room, message):
        """Envía un mensaje de chat a una sala específica"""
        if not self.connected: return
        
        print(f"[RED] Enviando mensaje a {room}: {message}")
        # Construye la trama: "REQ_CHAT_MSG|room|message\n"
        trama = f"{Protocol.REQ_CHAT_MSG}{Protocol.SEPARATOR}{room}{Protocol.SEPARATOR}{message}{Protocol.TERMINATOR}"
        try:
            self.socket.sendall(trama.encode(Protocol.ENCODING))
        except Exception as e:
            print(f"[RED] Error al enviar mensaje: {e}")

    def start_listening(self):
        """Inicia el hilo dedicado a recibir datos del servidor C"""
        print("[RED] Iniciando hilo para escuchar al servidor...")
        threading.Thread(target=self._listen_loop, daemon=True).start()

    def _listen_loop(self):
        """Loop infinito de lectura (corre en segundo plano)"""
        while self.connected:
            try:
                # Recibir bloques de bytes del servidor
                data = self.socket.recv(4096)
                if not data:
                    print("[RED] El servidor cerró la conexión.")
                    self.connected = False
                    break
                
                # Acumular en el buffer de texto
                self.buffer += data.decode(Protocol.ENCODING)
                
                # Procesar mensajes usando el método split_stream de tu protocol.py
                messages, remainder = Protocol.split_stream(self.buffer)
                self.buffer = remainder  # Guardar lo que quedó incompleto
                
                for raw_msg in messages:
                    # Parsear la trama individual: devuelve (comando, [args])
                    command, args = Protocol.parse(raw_msg)
                    if command:
                        self._process_server_command(command, args)
                        
            except Exception as e:
                print(f"[RED] Error en el loop de escucha: {e}")
                self.connected = False
                break

    def _process_server_command(self, command, args):
        """Mapea las respuestas del servidor C hacia los componentes de la GUI"""
        print(f"[RED] Procesando comando del servidor: {command} con argumentos {args}")
        
        # 1. Manejo de Inicio de Sesión
        if command == Protocol.RES_LOGIN_OK:
            if self.on_login_response:
                # El protocolo indica éxito
                self.on_login_response(True, "Login correcto")
                
        elif command == Protocol.RES_LOGIN_ERR:
            if self.on_login_response:
                reason = args[0] if len(args) > 0 else "Credenciales incorrectas"
                self.on_login_response(False, reason)
                
        # 2. Manejo de Mensajes Nuevos (Broadcasts del Servidor)
        elif command == Protocol.EVT_NEW_MSG:
            # Según la lógica común: args[0]=sala, args[1]=remitente, args[2]=mensaje
            if len(args) >= 3 and self.on_message_received:
                room, sender, msg = args[0], args[1], args[2]
                self.on_message_received(room, sender, msg)
                
        # 3. Actualizaciones del Lobby (Usuarios online / Salas creadas)
        elif command == Protocol.EVT_LOBBY_UPDATE:
            if self.on_elobby_update:
                # Aquí depende de cómo envíe el string tu backend en C. 
                # Si manda listas separadas, las parseas y se las mandas a app.py
                pass