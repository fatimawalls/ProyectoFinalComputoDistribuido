"""
networkClient.py — Cliente TCP para el servidor C (chatServerJson.c)
=====================================================================
Todo el estado del usuario se guarda en memoria como listas y dicts.
No se escribe ningún archivo.

Protocolo del servidor: JSON line-delimited (cada mensaje termina en \n)

SOLUCIÓN UDP:
  - Al conectar, se abre un socket UDP en puerto DINÁMICO (OS elige uno libre).
  - El puerto asignado se envía al servidor en el campo "udpPort" del AUTH/CREATE_ACCOUNT.
  - El servidor guarda ip:puerto por cliente en ShmUser y hace unicast directo.
  - Esto permite múltiples clientes en la misma máquina sin conflicto de puertos
    y elimina el broadcast a 255.255.255.255 que no sale de la red bridge de Docker.

Flujo de sesión:
  1. connect()          → abre socket TCP + socket UDP dinámico
  2. login() o          → envía AUTH / CREATE_ACCOUNT con udpPort incluido
     register()
  3. Servidor responde  → AUTH_RESPONSE + SYNC_START ... SYNC_END
  4. _parse_sync()      → llena self.rooms, self.users, self.messages
  5. Eventos push       → NEW_MESSAGE_RESPONSE, ADD_USER_RESPONSE, etc.
                          actualizan las mismas estructuras en memoria
  6. Eventos UDP        → NEW_MESSAGE_RESPONSE, USER_ONLINE, etc.
                          llegan al hilo _udp_listen_loop y se despachan igual que TCP

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
on_sync_complete()       * sync inicial terminó
on_new_message(room_id, msg_dict)        * mensaje nuevo en tiempo real
on_user_added(room_id, user_dict)        * alguien fue agregado a sala
on_user_removed(room_id, user_id)        * alguien fue removido de sala
on_room_created(room_dict)               * sala nueva creada
on_message_deleted(room_id, message_id) * mensaje eliminado
on_room_deleted(room_id)                 * sala eliminada
on_user_online(user_id, username)        * usuario nuevo conectado/registrado
on_user_offline(user_id, username)       * usuario desconectado
on_server_disconnected()
"""

import json
import socket
import threading

try:
    from gui import local_DB as local_db
except ImportError:
    import local_DB as local_db

ENCODING = "utf-8"


class NetworkClient:
    def __init__(self):
        self.socket     = None
        self.connected  = False
        self._buf       = ""          # buffer TCP parcial
        self._sync_lock = threading.Event()  # se setea al terminar el sync

        # ── Puerto UDP dinámico ──────────────────────────────────
        # Se asigna en connect(). El OS elige un puerto libre,
        # lo que evita conflictos entre múltiples clientes en la misma máquina.
        self.udp_socket  = None
        self._udp_port   = 0          # puerto UDP que el OS nos asignó

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
        self.on_user_online       = None  # (user_id, username)
        self.on_user_offline      = None  # (user_id, username)
        self.on_server_disconnected = None  # ()
        self.on_join_request_sent     = None  # (room_id, success)
        self.on_join_request_received = None  # (room_id, requester_id, requester_name)

        # Solicitudes de ingreso pendientes que el coordinador ha recibido
        self.pending_join_requests: dict[int, list] = {}

        # La base de datos local es la fuente de verdad del cliente.
        self._sync_compat_from_db()

    # ═══════════════════════════════════════════════════════════════
    # PUENTE CON BASE DE DATOS LOCAL
    # ═══════════════════════════════════════════════════════════════

    def _sync_compat_from_db(self):
        self.users = {
            friend.id: {
                "id": friend.id,
                "name": friend.username,
            }
            for friend in local_db.friends
        }

        self.rooms = {
            room.id: {
                "id": room.id,
                "name": room.name,
                "coordinatorId": room.coordinatorId,
                "userIds": list(room.userIds),
                "messageIds": list(room.messageIds),
                "notifications": room.unreadCount,
            }
            for room in local_db.chatRooms
        }

        self.messages = {}
        for message in local_db.messages:
            self.messages.setdefault(message.chatRoomId, []).append({
                "id": message.id,
                "userId": message.userId,
                "chatRoomId": message.chatRoomId,
                "text": message.text,
            })

    def _apply_server_obj_to_db(self, obj: dict):
        local_db.applyServerJson(
            json.dumps(obj, ensure_ascii=False)
        )
        self._sync_compat_from_db()

    # ═══════════════════════════════════════════════════════════════
    # CONEXIÓN
    # ═══════════════════════════════════════════════════════════════

    def connect(self, ip="127.0.0.1", port=5000) -> bool:
        """
        Abre el socket TCP y el socket UDP dinámico.

        El socket UDP se abre con bind("", 0) para que el OS asigne
        un puerto libre automáticamente. Este puerto se guarda en
        self._udp_port y se incluirá en el próximo AUTH/CREATE_ACCOUNT,
        de modo que el servidor sepa exactamente a dónde enviar los
        paquetes UDP de notificación para este cliente.
        """
        print(f"[RED] Conectando a {ip}:{port}...")
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((ip, port))
            self.connected = True
            print("[RED] ¡Conexión TCP establecida!")
            threading.Thread(target=self._listen_loop, daemon=True).start()

            # ── Socket UDP dinámico ──────────────────────────────
            # bind("", 0) hace que el OS elija un puerto libre.
            # Múltiples instancias del cliente en la misma máquina
            # obtendrán puertos distintos sin conflicto.
            try:
                self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.udp_socket.bind(("", 0))
                self._udp_port = self.udp_socket.getsockname()[1]
                threading.Thread(target=self._udp_listen_loop, daemon=True).start()
                print(f"[RED] Escuchando UDP en puerto dinámico: {self._udp_port}")
            except Exception as udp_e:
                self._udp_port = 0
                print(f"[RED] Advertencia UDP: No se pudo iniciar escucha UDP: {udp_e}")

            return True
        except Exception as e:
            print(f"[RED] Error al conectar: {e}")
            self.connected = False
            return False

    def disconnect(self):
        self.connected = False
        try:
            if self.socket:
                self.socket.close()
        except Exception:
            pass
        try:
            if self.udp_socket:
                self.udp_socket.close()
                self.udp_socket = None
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════
    # ENVÍOS AL SERVIDOR
    # ═══════════════════════════════════════════════════════════════

    def _send(self, obj: dict):
        """Serializa un dict como JSON y lo envía con \n final."""
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
        """
        Envía AUTH al servidor.
        Incluye udpPort para que el servidor registre el puerto UDP
        dinámico de este cliente y pueda hacerle unicast directo.
        """
        self._send({
            "type":     "AUTH",
            "username": username,
            "password": password,
            "udpPort":  self._udp_port,   # puerto UDP dinámico asignado por el OS
        })

    def register(self, username: str, password: str):
        """
        Envía CREATE_ACCOUNT al servidor.
        Incluye udpPort por la misma razón que login().
        """
        self._send({
            "type":     "CREATE_ACCOUNT",
            "username": username,
            "password": password,
            "udpPort":  self._udp_port,   # puerto UDP dinámico asignado por el OS
        })

    def send_message(self, room_id: int, text: str):
        self._send({
            "type":       "NEW_MESSAGE",
            "text":       text,
            "userId":     self.me.get("id"),
            "chatRoomId": room_id,
        })

    def create_room(self, name: str):
        self._send({
            "type":          "NEW_CHATROOM",
            "name":          name,
            "coordinatorId": self.me.get("id"),
        })

    def add_user_to_room(self, user_id: int, room_id: int):
        self._send({
            "type":       "ADD_USER",
            "userId":     user_id,
            "chatRoomId": room_id,
        })

    def remove_user_from_room(self, user_id: int, room_id: int):
        self._send({
            "type":       "REMOVE_USER",
            "userId":     user_id,
            "chatRoomId": room_id,
        })

    def leave_room(self, room_id: int):
        self._send({
            "type":       "REMOVE_USER",
            "userId":     self.me.get("id"),
            "chatRoomId": room_id,
        })

    def request_join_room(self, chat_room_id: int):
        self._send({
            "type":       "JOIN_REQUEST",
            "chatRoomId": chat_room_id,
            "userId":     self.me.get("id"),
        })

    def delete_message(self, message_id: int):
        self._send({
            "type":      "DELETE_MESSAGE",
            "messageId": message_id,
        })

    def delete_room(self, room_id: int):
        self._send({
            "type":       "DELETE_CHATROOM",
            "chatRoomId": room_id,
        })

    def remove_user(self, chat_room_id: int, user_id: int):
        self._send({
            "type":       "REMOVE_USER",
            "chatRoomId": chat_room_id,
            "userId":     user_id,
        })

    def delete_chatroom(self, chat_room_id: int):
        self._send({
            "type":       "DELETE_CHATROOM",
            "chatRoomId": chat_room_id,
        })

    def create_account(self, username: str, password: str):
        self._send({
            "type":     "CREATE_ACCOUNT",
            "username": username,
            "password": password,
            "udpPort":  self._udp_port,
        })

    # ═══════════════════════════════════════════════════════════════
    # ACCESORES DE CONVENIENCIA
    # ═══════════════════════════════════════════════════════════════

    def get_my_rooms(self) -> list:
        my_id = self.me.get("id")
        return [r for r in self.rooms.values() if my_id in r.get("userIds", [])]

    def get_room_messages(self, room_id: int) -> list:
        return self.messages.get(room_id, [])

    def get_room_users(self, room_id: int) -> list:
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

    # ═══════════════════════════════════════════════════════════════
    # HILO DE ESCUCHA UDP (notificaciones push del servidor)
    # ═══════════════════════════════════════════════════════════════

    def _udp_listen_loop(self):
        """
        Escucha paquetes UDP unicast del servidor en el puerto dinámico
        que el OS nos asignó. El servidor C sabe a qué puerto enviar
        porque se lo comunicamos en el campo udpPort del AUTH.

        Los mensajes recibidos se despachan exactamente igual que los
        mensajes TCP: pasan por _dispatch() y activan los mismos callbacks.
        """
        print(f"[RED-UDP] Hilo UDP activo en puerto {self._udp_port}")
        while self.connected and self.udp_socket:
            try:
                data, addr = self.udp_socket.recvfrom(65536)
                raw_msg = data.decode(ENCODING).strip()
                if raw_msg:
                    print(f"[RED-UDP] Recibido de {addr}: {raw_msg}")
                    # Puede haber múltiples JSONs en un solo datagrama (separados por \n)
                    for line in raw_msg.split("\n"):
                        line = line.strip()
                        if line:
                            self._dispatch(line)
            except Exception as e:
                if self.connected:
                    print(f"[RED-UDP] Error: {e}")
                break
        print(f"[RED-UDP] Hilo UDP finalizado (puerto {self._udp_port})")

    def _process_buffer(self):
        """Extrae líneas completas del buffer TCP y las despacha."""
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.strip()
            if line:
                self._dispatch(line)

    # ═══════════════════════════════════════════════════════════════
    # DESPACHADOR DE MENSAJES JSON
    # (usado tanto por TCP como por UDP — misma lógica)
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
            "AUTH_RESPONSE":            self._on_auth_response,
            "CREATE_ACCOUNT_RESPONSE":  self._on_register_response,
            "SYNC_START":               self._on_sync_start,
            "SYNC_END":                 self._on_sync_end,
            "CHAT_USER":                self._on_sync_chat_user,
            "CHATROOM":                 self._on_sync_chatroom,
            "MESSAGE":                  self._on_sync_message,
            "NEW_MESSAGE_RESPONSE":     self._on_new_message_response,
            "NEW_CHATROOM_RESPONSE":    self._on_new_chatroom_response,
            "ADD_USER_RESPONSE":        self._on_add_user_response,
            "REMOVE_USER_RESPONSE":     self._on_remove_user_response,
            "DELETE_MESSAGE_RESPONSE":  self._on_delete_message_response,
            "DELETE_CHATROOM_RESPONSE": self._on_delete_chatroom_response,
            "USER_ONLINE":              self._on_user_online,
            "USER_OFFLINE":             self._on_user_offline,
            "JOIN_REQUEST_RESPONSE":    self._on_join_request_response,
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
            print(f"[RED] Login OK → id={self.me['id']} username={self.me['username']} udpPort={self._udp_port}")
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
    # ═══════════════════════════════════════════════════════════════

    def _on_sync_start(self, obj: dict):
        print("[RED] Sync iniciado — limpiando base de datos local")
        local_db.clearState()
        self._sync_compat_from_db()
        self._syncing = True
        self._current_sync_room = None
        self._sync_lock.clear()

    def _on_sync_chatroom(self, obj: dict):
        if not self._syncing:
            return
        self._apply_server_obj_to_db(obj)
        self._current_sync_room = obj.get("id")
        print(f"[RED]   SYNC sala #{obj.get('id')}: {obj.get('name')}")

    def _on_sync_chat_user(self, obj: dict):
        if not self._syncing:
            return
        self._apply_server_obj_to_db(obj)
        print(f"[RED]   SYNC usuario #{obj.get('id')}: {obj.get('name')}")

    def _on_sync_message(self, obj: dict):
        if not self._syncing:
            return
        if obj.get("chatRoomId") is None and self._current_sync_room is not None:
            obj["chatRoomId"] = self._current_sync_room
        self._apply_server_obj_to_db(obj)
        print(f"[RED]   SYNC mensaje #{obj.get('id')} en sala #{obj.get('chatRoomId')}")

    def _on_sync_end(self, obj: dict):
        self._syncing = False
        self._current_sync_room = None
        self._sync_compat_from_db()

        print(f"[RED] Sync completo — "
              f"{len(local_db.chatRooms)} salas, "
              f"{len(local_db.friends)} usuarios, "
              f"{len(local_db.messages)} mensajes")

        self._sync_lock.set()

        if self.on_sync_complete:
            self.on_sync_complete()

    # ═══════════════════════════════════════════════════════════════
    # HANDLERS — EVENTOS EN TIEMPO REAL
    # (llegan por TCP o por UDP — el despachador es el mismo)
    # ═══════════════════════════════════════════════════════════════

    def _on_user_online(self, obj: dict):
        """Usuario conectado/registrado — notificación push."""
        user_id  = obj.get("userId") or obj.get("id")
        username = obj.get("username") or obj.get("name")

        if user_id and username:
            self._apply_server_obj_to_db({
                "type": "CHAT_USER",
                "id":   user_id,
                "name": username,
            })
            print(f"[RED] Usuario conectado: {username} (#{user_id})")
            if self.on_user_online:
                self.on_user_online(user_id, username)

    def _on_user_offline(self, obj: dict):
        """Usuario desconectado — notificación push."""
        user_id  = obj.get("userId") or obj.get("id")
        username = obj.get("username") or obj.get("name", "")
        print(f"[RED] Usuario desconectado: {username} (#{user_id})")
        if self.on_user_offline:
            self.on_user_offline(user_id, username)

    def _on_new_message_response(self, obj: dict):
        if not obj.get("success"):
            return

        msg_data = obj.get("message", {})
        room_id  = msg_data.get("chatRoomId")

        self._apply_server_obj_to_db(obj)

        msg = {
            "id":         msg_data.get("id"),
            "userId":     msg_data.get("userId"),
            "chatRoomId": room_id,
            "text":       msg_data.get("text", ""),
        }

        print(f"[RED] Nuevo mensaje #{msg['id']} en sala #{room_id}")

        if self.on_new_message:
            self.on_new_message(room_id, msg)

    def _on_new_chatroom_response(self, obj: dict):
        if not obj.get("success"):
            return

        self._apply_server_obj_to_db(obj)

        cr      = obj.get("chatRoom", {})
        room_id = cr.get("id")
        room    = self.rooms.get(room_id, {
            "id":            room_id,
            "name":          cr.get("name", ""),
            "coordinatorId": cr.get("coordinatorId"),
            "userIds":       list(cr.get("userIds", [])),
        })

        print(f"[RED] Sala nueva #{room_id}: {room.get('name')}")

        if self.on_room_created:
            self.on_room_created(room)

    def _on_add_user_response(self, obj: dict):
        if not obj.get("success"):
            return

        self._apply_server_obj_to_db(obj)

        room_id = obj.get("chatRoomId")
        user_id = obj.get("userId")

        print(f"[RED] Usuario #{user_id} agregado a sala #{room_id}")

        if self.on_user_added:
            self.on_user_added(room_id, self.users.get(user_id, {"id": user_id}))

    def _on_remove_user_response(self, obj: dict):
        if not obj.get("success"):
            return

        self._apply_server_obj_to_db(obj)

        room_id = obj.get("chatRoomId")
        user_id = obj.get("userId")

        print(f"[RED] Usuario #{user_id} removido de sala #{room_id}")

        if self.on_user_removed:
            self.on_user_removed(room_id, user_id)

    def _on_delete_message_response(self, obj: dict):
        if not obj.get("success"):
            return

        message_id = obj.get("messageId")
        deleted    = local_db.deleteMessage(message_id)
        room_id    = deleted.chatRoomId if deleted else None

        self._sync_compat_from_db()

        if room_id is not None:
            print(f"[RED] Mensaje #{message_id} eliminado de sala #{room_id}")
            if self.on_message_deleted:
                self.on_message_deleted(room_id, message_id)

    def _on_delete_chatroom_response(self, obj: dict):
        if not obj.get("success"):
            return

        room_id = obj.get("chatRoomId")
        local_db.deleteChatRoom(room_id)
        self._sync_compat_from_db()

        print(f"[RED] Sala #{room_id} eliminada de memoria local")

        if self.on_room_deleted:
            self.on_room_deleted(room_id)

    def _on_join_request_response(self, obj: dict):
        success        = bool(obj.get("success"))
        room_id        = obj.get("chatRoomId")
        requester_id   = obj.get("requesterId")
        requester_name = obj.get("requesterName", f"User_{requester_id}")
        my_id          = self.me.get("id")

        if requester_id == my_id:
            print(f"[RED] Join request {'enviada' if success else 'fallida'} para sala #{room_id}")
            if self.on_join_request_sent:
                self.on_join_request_sent(room_id, success)
        else:
            self.pending_join_requests.setdefault(room_id, []).append({
                "requesterId":   requester_id,
                "requesterName": requester_name,
            })
            print(f"[RED] Solicitud de ingreso: {requester_name} (#{requester_id}) → sala #{room_id}")
            if self.on_join_request_received:
                self.on_join_request_received(room_id, requester_id, requester_name)