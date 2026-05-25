class Protocol:
    # --- CONFIGURACIÓN BÁSICA ---
    SEPARATOR = "|"
    TERMINATOR = "\n"
    ENCODING = "utf-8"

    # --- COMANDOS (CONSTANTES) ---

    # 1. Peticiones (Cliente -> Servidor C)
    REQ_LOGIN = "REQ_LOGIN"
    REQ_REGISTER = "REQ_REGISTER"
    REQ_CREATE_ROOM = "REQ_CREATE_ROOM"
    REQ_JOIN_ROOM = "REQ_JOIN_ROOM"
    REQ_LEAVE_ROOM = "REQ_LEAVE_ROOM"
    REQ_CHAT_MSG = "REQ_CHAT_MSG"
    REQ_COORD_ACTION = "REQ_COORD_ACTION"
    REQ_LOBBY_DATA = "REQ_LOBBY_DATA"

    # 2. Respuestas (Servidor C -> Cliente)
    RES_LOGIN_OK = "RES_LOGIN_OK"
    RES_LOGIN_ERR = "RES_LOGIN_ERR"
    RES_REGISTER_OK = "RES_REGISTER_OK"
    RES_REGISTER_ERR = "RES_REGISTER_ERR"
    RES_ROOM_CREATED = "RES_ROOM_CREATED"
    RES_JOIN_PENDING = "RES_JOIN_PENDING"
    RES_JOIN_OK = "RES_JOIN_OK"
    RES_ERROR = "RES_ERROR"

    # 3. Eventos (Servidor C -> Todos los Clientes afectados)
    EVT_NEW_MSG = "EVT_NEW_MSG"
    EVT_LOBBY_UPDATE = "EVT_LOBBY_UPDATE"
    EVT_USER_JOINED = "EVT_USER_JOINED"
    EVT_USER_LEFT = "EVT_USER_LEFT"
    EVT_SYSTEM_MSG = "EVT_SYSTEM_MSG"

    @staticmethod
    def build_message(command, *args):
        """
        Construye un mensaje codificado en bytes listo para enviar por el socket TCP.
        Ejemplo: Protocol.build_message(Protocol.REQ_LOGIN, "juan", "1234")
        """
        # Convertir todo a string y remover el separador o terminador de los datos del usuario
        # Esto evita que un usuario malicioso rompa el protocolo escribiendo "|" en el chat
        safe_args = []
        for arg in args:
            safe_arg = str(arg).replace(Protocol.SEPARATOR, "").replace(Protocol.TERMINATOR, "")
            safe_args.append(safe_arg)

        parts = [command] + safe_args
        message_str = Protocol.SEPARATOR.join(parts) + Protocol.TERMINATOR
        return message_str.encode(Protocol.ENCODING)

    @staticmethod
    def parse_message(raw_data):
        """
        Toma un mensaje individual (bytes o string) y lo convierte en una tupla (comando, argumentos).
        Retorna: (comando, [arg1, arg2, ...])
        """
        if not raw_data:
            return None, []

        # Si los datos vienen en bytes (lo normal al leer un socket), los decodificamos
        if isinstance(raw_data, bytes):
            try:
                raw_data = raw_data.decode(Protocol.ENCODING)
            except UnicodeDecodeError:
                return None, []

        clean_data = raw_data.strip(Protocol.TERMINATOR).strip()
        if not clean_data:
            return None, []

        parts = clean_data.split(Protocol.SEPARATOR)
        command = parts[0]
        args = parts[1:] if len(parts) > 1 else []

        return command, args

    @staticmethod
    def split_stream(buffer_str):
        """
        Utilidad vital para TCP: Separa un buffer que pueda contener múltiples mensajes pegados.
        Como TCP transmite flujos de datos, a veces llegan 2 o más mensajes juntos de golpe.
        Ejemplo buffer: "EVT_NEW_MSG|sala|A|hola\nEVT_NEW_MSG|sala|B|adios\n"

        Retorna: (lista_de_mensajes_completos, buffer_restante_incompleto)
        """
        if Protocol.TERMINATOR not in buffer_str:
            return [], buffer_str

        messages = buffer_str.split(Protocol.TERMINATOR)
        # El último elemento siempre es el resto del buffer
        # (será un string vacío "" si el paquete terminó en \n exacto)
        tail = messages.pop()

        return messages, tail