"""
networkClient.py — Cliente TCP para el servidor C (chatServerJson.c)
=====================================================================
Todo el estado del usuario se guarda en memoria como listas y dicts.
No se escribe ningún archivo.

Protocolo del servidor: JSON line-delimited (cada mensaje termina en \\n)

Flujo de sesión:
  1. connect()          → abre socket TCP
  2. login() o          → envía AUTH / CREATE_ACCOUNT
     register()
  3. Servidor responde  → AUTH_RESPONSE + SYNC_START ... SYNC_END
  4. _parse_sync()      → llena self.rooms, self.users, self.messages
  5. Eventos push       → NEW_MESSAGE_RESPONSE, ADD_USER_RESPONSE, etc.
                          actualizan las mismas estructuras en memoria

Estructuras en memoria
──────────────────────
self.me = {
    "id":       int,
    "username": str
}

self.rooms = {
    room_id (int): {
        "id":            int,
        "name":          str,
        "coordinatorId": int,
        "userIds":       [int, ...]
    }, ...
}

self.users = {
    user_id (int): {
        "id":   int,
        "name": str
    }, ...
}

self.messages = {
    room_id (int): [
        {"id": int, "userId": int, "chatRoomId": int, "text": str},
        ...
    ], ...
}

Callbacks que la GUI debe inyectar
───────────────────────────────────
on_login_response(success: bool, message: str)
on_register_response(success: bool, user_id: int, username: str)
on_sync_complete()                       ← sync inicial terminó
on_new_message(room_id, msg_dict)        ← mensaje nuevo en tiempo real
on_user_added(room_id, user_dict)        ← alguien fue agregado a sala
on_user_removed(room_id, user_id)        ← alguien fue removido de sala
on_room_created(room_dict)               ← sala nueva creada
on_message_deleted(room_id, message_id) ← mensaje eliminado
on_room_deleted(room_id)                 ← sala eliminada
on_server_disconnected()
"""

import json
import socket
import threading


ENCODING = "utf-8"


class NetworkClient:
    def __init__(self):
        self.socket     = None
        self.connected  = False
        self._buf       = ""          # buffer TCP parcial
        self._sync_lock = threading.Event()  # se setea al terminar el sync

        # ── Estado en memoria ────────────────────────────────────
        self.me       = {}            # {"id": int, "username": str}
        self.rooms    = {}            # {room_id: {id, name, coordinatorId, userIds}}
        self.users    = {}            # {user_id: {id, name}}
        self.messages = {}            # {room_id: [{id, userId, chatRoomId, text}]}

        # Estado interno del sync
        self._syncing            = False
        self._current_sync_room  = None  # room_id del último CHATROOM visto

        # ── Callbacks para la GUI ────────────────────────────────
        self.on_login_response    = None  # (success, message)
        self.on_register_response = None  # (success, user_id, username)
        self.on_sync_complete     = None  # ()
        self.on_new_message       = None  # (room_id, msg_dict)
        self.on_user_added        = None  # (room_id, user_dict)
        self.on_user_removed      = None  # (room_id, user_id)
        self.on_room_created      = None  # (room_dict)
        self.on_message_deleted   = None  # (room_id, message_id)
        self.on_room_deleted      = None  # (room_id)
        self.on_server_disconnected = None  # ()

    # ═══════════════════════════════════════════════════════════════
    # CONEXIÓN
    # ═══════════════════════════════════════════════════════════════

    def connect(self, ip="127.0.0.1", port=5000) -> bool:
        """Abre el socket TCP. No inicia el hilo de escucha todavía."""
        print(f"[RED] Conectando a {ip}:{port}...")
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((ip, port))
            self.connected = True
            print("[RED] ¡Conexión establecida!")
            threading.Thread(target=self._listen_loop, daemon=True).start()
            return True
        except Exception as e:
            print(f"[RED] Error al conectar: {e}")
            self.connected = False
            return False

    def disconnect(self):
        self.connected = False
        try:
            self.socket.close()
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════
    # ENVÍOS AL SERVIDOR
    # ═══════════════════════════════════════════════════════════════

    def _send(self, obj: dict):
        """Serializa un dict como JSON y lo envía con \\n final."""
        if not self.connected:
            print("[RED] Error: no conectado.")
            return
        try:
            line = json.dumps(obj, ensure_ascii=False) + "\n"
            self.socket.sendall(line.encode(ENCODING))
            print(f"[RED] → SEND {obj.get('type', '?')}")
        except Exception as e:
            print(f"[RED] Error al enviar: {e}")

    def login(self, username: str, password: str):
        """Envía AUTH al servidor."""
        self._send({
            "type":     "AUTH",
            "username": username,
            "password": password,
        })

    def register(self, username: str, password: str):
        """Envía CREATE_ACCOUNT al servidor."""
        self._send({
            "type":     "CREATE_ACCOUNT",
            "username": username,
            "password": password,
        })

    def send_message(self, room_id: int, text: str):
        """Envía NEW_MESSAGE. El servidor actualiza la DB y hace broadcast."""
        self._send({
            "type":       "NEW_MESSAGE",
            "text":       text,
            "userId":     self.me.get("id"),
            "chatRoomId": room_id,
        })

    def create_room(self, name: str):
        """Crea una sala nueva. El coordinador es el usuario actual."""
        self._send({
            "type":          "NEW_CHATROOM",
            "name":          name,
            "coordinatorId": self.me.get("id"),
        })

    def add_user_to_room(self, user_id: int, room_id: int):
        """Agrega un usuario a una sala (acción de coordinador)."""
        self._send({
            "type":       "ADD_USER",
            "userId":     user_id,
            "chatRoomId": room_id,
        })

    def remove_user_from_room(self, user_id: int, room_id: int):
        """Elimina un usuario de una sala (acción de coordinador)."""
        self._send({
            "type":       "REMOVE_USER",
            "userId":     user_id,
            "chatRoomId": room_id,
        })

    def delete_message(self, message_id: int):
        """Elimina un mensaje por ID."""
        self._send({
            "type":      "DELETE_MESSAGE",
            "messageId": message_id,
        })

    def delete_room(self, room_id: int):
        """Elimina una sala (solo si el coordinador es el único miembro)."""
        self._send({
            "type":       "DELETE_CHATROOM",
            "chatRoomId": room_id,
        })

    # ═══════════════════════════════════════════════════════════════
    # ACCESORES DE CONVENIENCIA (lectura del estado en memoria)
    # ═══════════════════════════════════════════════════════════════

    def get_my_rooms(self) -> list:
        """Lista de salas donde el usuario actual es miembro."""
        my_id = self.me.get("id")
        return [r for r in self.rooms.values() if my_id in r.get("userIds", [])]

    def get_room_messages(self, room_id: int) -> list:
        """Historial en memoria de una sala."""
        return self.messages.get(room_id, [])

    def get_room_users(self, room_id: int) -> list:
        """Dicts de usuarios miembros de una sala."""
        room = self.rooms.get(room_id)
        if not room:
            return []
        return [self.users[uid] for uid in room.get("userIds", []) if uid in self.users]

    def is_coordinator(self, room_id: int) -> bool:
        room = self.rooms.get(room_id)
        return room is not None and room.get("coordinatorId") == self.me.get("id")

    # ═══════════════════════════════════════════════════════════════
    # HILO DE ESCUCHA TCP
    # ═══════════════════════════════════════════════════════════════

    def _listen_loop(self):
        while self.connected:
            try:
                data = self.socket.recv(4096)
                if not data:
                    print("[RED] Servidor cerró la conexión.")
                    self.connected = False
                    break
                self._buf += data.decode(ENCODING)
                self._process_buffer()
            except Exception as e:
                if self.connected:
                    print(f"[RED] Error en listen_loop: {e}")
                self.connected = False
                break

        if self.on_server_disconnected:
            self.on_server_disconnected()

    def _process_buffer(self):
        """Extrae líneas completas del buffer y las despacha."""
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.strip()
            if line:
                self._dispatch(line)

    # ═══════════════════════════════════════════════════════════════
    # DESPACHADOR DE MENSAJES JSON
    # ═══════════════════════════════════════════════════════════════

    def _dispatch(self, raw: str):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            print(f"[RED] JSON inválido recibido: {raw!r}")
            return

        msg_type = obj.get("type", "")
        print(f"[RED] ← RECV {msg_type}")

        handlers = {
            "AUTH_RESPONSE":           self._on_auth_response,
            "CREATE_ACCOUNT_RESPONSE": self._on_register_response,
            "SYNC_START":              self._on_sync_start,
            "SYNC_END":                self._on_sync_end,
            "CHATROOM":                self._on_sync_chatroom,
            "CHAT_USER":               self._on_sync_chat_user,
            "MESSAGE":                 self._on_sync_message,
            "NEW_MESSAGE_RESPONSE":    self._on_new_message_response,
            "NEW_CHATROOM_RESPONSE":   self._on_new_chatroom_response,
            "ADD_USER_RESPONSE":       self._on_add_user_response,
            "REMOVE_USER_RESPONSE":    self._on_remove_user_response,
            "DELETE_MESSAGE_RESPONSE": self._on_delete_message_response,
            "DELETE_CHATROOM_RESPONSE":self._on_delete_chatroom_response,
        }

        handler = handlers.get(msg_type)
        if handler:
            handler(obj)
        else:
            print(f"[RED] Tipo desconocido: {msg_type}")

    # ═══════════════════════════════════════════════════════════════
    # HANDLERS — AUTH
    # ═══════════════════════════════════════════════════════════════

    def _on_auth_response(self, obj: dict):
        success = bool(obj.get("success"))
        if success:
            self.me = {
                "id":       obj.get("userId"),
                "username": obj.get("username", ""),
            }
            print(f"[RED] Login OK → id={self.me['id']} username={self.me['username']}")
            if self.on_login_response:
                self.on_login_response(True, "Login correcto")
        else:
            print("[RED] Login fallido")
            if self.on_login_response:
                self.on_login_response(False, "Credenciales incorrectas")

    def _on_register_response(self, obj: dict):
        success = bool(obj.get("success"))
        user_id  = obj.get("userId", -1)
        username = obj.get("username", "")
        print(f"[RED] Register {'OK' if success else 'FAIL'}")
        if self.on_register_response:
            self.on_register_response(success, user_id, username)

    # ═══════════════════════════════════════════════════════════════
    # HANDLERS — SYNC INICIAL
    # El servidor envía exactamente:
    #   SYNC_START
    #   CHATROOM  (para cada sala del usuario)
    #   CHAT_USER (para cada miembro de esa sala)
    #   MESSAGE   (para cada mensaje de esa sala)
    #   ...siguiente sala...
    #   SYNC_END
    # ═══════════════════════════════════════════════════════════════

    def _on_sync_start(self, obj: dict):
        print("[RED] Sync iniciado — limpiando estado en memoria")
        self.rooms    = {}
        self.users    = {}
        self.messages = {}
        self._syncing           = True
        self._current_sync_room = None

    def _on_sync_chatroom(self, obj: dict):
        """Un CHATROOM durante el sync define la sala actual para los siguientes CHAT_USER y MESSAGE."""
        if not self._syncing:
            return
        room_id = obj["id"]
        self.rooms[room_id] = {
            "id":            room_id,
            "name":          obj.get("name", ""),
            "coordinatorId": obj.get("coordinatorId"),
            "userIds":       list(obj.get("userIds", [])),
        }
        if room_id not in self.messages:
            self.messages[room_id] = []
        self._current_sync_room = room_id
        print(f"[RED]   SYNC sala #{room_id}: {obj.get('name')}")

    def _on_sync_chat_user(self, obj: dict):
        """Un CHAT_USER durante el sync registra al usuario en self.users."""
        if not self._syncing:
            return
        user_id = obj["id"]
        self.users[user_id] = {
            "id":   user_id,
            "name": obj.get("name", ""),
        }
        print(f"[RED]   SYNC usuario #{user_id}: {obj.get('name')}")

    def _on_sync_message(self, obj: dict):
        """Un MESSAGE durante el sync se añade al historial de la sala actual."""
        if not self._syncing or self._current_sync_room is None:
            return
        room_id = obj.get("chatRoomId", self._current_sync_room)
        msg = {
            "id":         obj["id"],
            "userId":     obj.get("userId"),
            "chatRoomId": room_id,
            "text":       obj.get("text", ""),
        }
        self.messages.setdefault(room_id, []).append(msg)
        print(f"[RED]   SYNC mensaje #{msg['id']} en sala #{room_id}")

    def _on_sync_end(self, obj: dict):
        self._syncing           = False
        self._current_sync_room = None
        print(f"[RED] Sync completo — "
              f"{len(self.rooms)} salas, "
              f"{len(self.users)} usuarios, "
              f"{sum(len(v) for v in self.messages.values())} mensajes")
        self._sync_lock.set()
        if self.on_sync_complete:
            self.on_sync_complete()

    # ═══════════════════════════════════════════════════════════════
    # HANDLERS — EVENTOS EN TIEMPO REAL
    # Estos llegan como broadcasts cuando otros usuarios hacen cosas.
    # La respuesta lleva notifyUsers: [id1, id2, ...] — el servidor
    # la manda a todos los afectados, incluido el remitente.
    # ═══════════════════════════════════════════════════════════════

    def _on_new_message_response(self, obj: dict):
        """
        Llega cuando alguien (incluyendo yo) manda un mensaje.
        Actualiza self.messages en memoria y dispara on_new_message.
        """
        if not obj.get("success"):
            return
        msg_data    = obj.get("message", {})
        room_id     = msg_data.get("chatRoomId")
        msg = {
            "id":         msg_data.get("id"),
            "userId":     msg_data.get("userId"),
            "chatRoomId": room_id,
            "text":       msg_data.get("text", ""),
        }
        self.messages.setdefault(room_id, []).append(msg)
        print(f"[RED] Nuevo mensaje #{msg['id']} en sala #{room_id}")
        if self.on_new_message:
            self.on_new_message(room_id, msg)

    def _on_new_chatroom_response(self, obj: dict):
        """
        Llega cuando se crea una sala nueva.
        La agrega a self.rooms.
        """
        if not obj.get("success"):
            return
        cr = obj.get("chatRoom", {})
        room_id = cr.get("id")
        coordinator_id = cr.get("coordinatorId")
        room = {
            "id":            room_id,
            "name":          cr.get("name", ""),
            "coordinatorId": coordinator_id,
            "userIds":       [coordinator_id] if coordinator_id else [],
        }
        self.rooms[room_id] = room
        self.messages.setdefault(room_id, [])
        print(f"[RED] Sala nueva #{room_id}: {room['name']}")
        if self.on_room_created:
            self.on_room_created(room)

    def _on_add_user_response(self, obj: dict):
        """
        Llega cuando alguien es agregado a una sala.
        Actualiza self.rooms[room_id]["userIds"] y self.users.
        """
        if not obj.get("success"):
            return
        room_id = obj.get("chatRoomId")
        user_id = obj.get("userId")
        chat_user = obj.get("chatUser", {})

        # Registrar usuario si es nuevo
        if user_id and chat_user:
            self.users[user_id] = {
                "id":   user_id,
                "name": chat_user.get("username", ""),
            }

        # Agregar a la sala en memoria
        room = self.rooms.get(room_id)
        if room and user_id and user_id not in room["userIds"]:
            room["userIds"].append(user_id)

        print(f"[RED] Usuario #{user_id} agregado a sala #{room_id}")
        if self.on_user_added:
            self.on_user_added(room_id, self.users.get(user_id, {"id": user_id}))

    def _on_remove_user_response(self, obj: dict):
        """
        Llega cuando alguien es removido de una sala.
        Lo elimina de self.rooms[room_id]["userIds"].
        """
        if not obj.get("success"):
            return
        room_id = obj.get("chatRoomId")
        user_id = obj.get("userId")
        room = self.rooms.get(room_id)
        if room and user_id in room.get("userIds", []):
            room["userIds"].remove(user_id)
        print(f"[RED] Usuario #{user_id} removido de sala #{room_id}")
        if self.on_user_removed:
            self.on_user_removed(room_id, user_id)

    def _on_delete_message_response(self, obj: dict):
        """
        Llega cuando se elimina un mensaje.
        Lo borra del historial en memoria.
        """
        if not obj.get("success"):
            return
        message_id = obj.get("messageId")
        for room_id, msgs in self.messages.items():
            for i, m in enumerate(msgs):
                if m["id"] == message_id:
                    msgs.pop(i)
                    print(f"[RED] Mensaje #{message_id} eliminado de sala #{room_id}")
                    if self.on_message_deleted:
                        self.on_message_deleted(room_id, message_id)
                    return

    def _on_delete_chatroom_response(self, obj: dict):
        """
        Llega cuando se elimina una sala.
        La borra de self.rooms y self.messages.
        """
        if not obj.get("success"):
            return
        room_id = obj.get("chatRoomId")
        self.rooms.pop(room_id, None)
        self.messages.pop(room_id, None)
        print(f"[RED] Sala #{room_id} eliminada de memoria")
        if self.on_room_deleted:
            self.on_room_deleted(room_id)

    # ─────────────────────────────────────────────────────────────
    # MÉTODOS DE PETICIÓN (Basados en handbookRequestDB.txt)
    # ─────────────────────────────────────────────────────────────

    def remove_user(self, chat_room_id: int, user_id: int):
        """
        Petición para expulsar a un usuario de una sala.
        """
        payload = {
            "type": "REMOVE_USER",
            "chatRoomId": chat_room_id,
            "userId": user_id
        }
        self._send(payload)

    def delete_chatroom(self, chat_room_id: int):
        """
        Petición para eliminar una sala de chat completa.
        """
        payload = {
            "type": "DELETE_CHATROOM",
            "chatRoomId": chat_room_id
        }
        self._send(payload)

    def delete_message(self, message_id: int):
        """
        Petición para eliminar un mensaje específico.
        """
        payload = {
            "type": "DELETE_MESSAGE",
            "messageId": message_id
        }
        self._send(payload)

    def create_account(self, username, password):
        """
        Petición para crear una cuenta nueva.
        """
        payload = {
            "type": "CREATE_ACCOUNT",
            "username": username,
            "password": password
        }
        self._send(payload)