"""
networkClient.py — Cliente TCP para el servidor C (chatServerJson.c)
=====================================================================
Todo el estado del usuario se guarda en memoria como listas y dicts.
No se escribe ningún archivo.

Protocolo del servidor: JSON line-delimited (cada mensaje termina en \n)

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
on_sync_complete()       * sync inicial terminó
on_new_message(room_id, msg_dict)        * mensaje nuevo en tiempo real
on_user_added(room_id, user_dict)        * alguien fue agregado a sala
on_user_removed(room_id, user_id)        * alguien fue removido de sala
on_room_created(room_dict)               * sala nueva creada
on_message_deleted(room_id, message_id) * mensaje eliminado
on_room_deleted(room_id)                 * sala eliminada
on_user_online(user_id, username)        * usuario nuevo conectado/registrado
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

        # UDP callback info reported to chatServerJson after TCP connects.
        self.udp_socket = None
        self.udp_ip     = ""
        self.udp_port   = 0

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
        self.on_server_disconnected = None  # ()
        

    # ═══════════════════════════════════════════════════════════════
    # CONEXIÓN
    # ═══════════════════════════════════════════════════════════════

    def ask_loadbalancer(self, lb_ip: str = "127.0.0.1", lb_port: int = 4000) -> tuple[str, int] | None:
        """
        Pregunta al Load Balancer qué chatServer usar.

        El LB responde:
            {"success":1,"ip":"...","port":5006}

        Returns:
            (ip, port) si hay servidor disponible, None si falla.
        """
        print(f"[LB] Consultando load balancer {lb_ip}:{lb_port}...")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as lb_socket:
                lb_socket.settimeout(5)
                lb_socket.connect((lb_ip, lb_port))

                data = b""
                while b"\n" not in data:
                    chunk = lb_socket.recv(4096)
                    if not chunk:
                        break
                    data += chunk

            raw = data.decode(ENCODING, errors="replace").strip()
            print(f"[LB] Respuesta: {raw}")

            obj = json.loads(raw)
            if not obj.get("success"):
                print(f"[LB] Sin servidor disponible: {obj.get('error', 'error desconocido')}")
                return None

            return obj["ip"], int(obj["port"])

        except Exception as e:
            print(f"[LB] Error consultando load balancer: {e}")
            return None

    def _guess_udp_ip(self, server_ip: str) -> str:
        """
        IP que el server usará para devolver eventos UDP.

        Para servidores LAN normalmente es la IP local de salida.
        En localhost/Docker puede requerir ajuste manual, pero este valor
        es mejor que hardcodear 127.0.0.1 para todos los casos.
        """
        try:
            if self.socket:
                local_ip = self.socket.getsockname()[0]
                if local_ip:
                    return local_ip
        except Exception:
            pass

        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.connect((server_ip, 9))
            local_ip = probe.getsockname()[0]
            probe.close()
            return local_ip
        except Exception:
            return "127.0.0.1"

    def connect(self, ip="127.0.0.1", port=5000) -> bool:
        """Abre el socket TCP y prepara el socket UDP para eventos push."""
        print(f"[RED] Conectando a {ip}:{port}...")
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((ip, port))
            self.connected = True
            print("[RED] ¡Conexión TCP establecida!")

            # UDP push listener.
            # Puerto dinámico para permitir varios clientes en la misma máquina.
            try:
                self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if hasattr(socket, "SO_REUSEPORT"):
                    self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

                self.udp_socket.bind(("", 0))
                self.udp_port = self.udp_socket.getsockname()[1]
                self.udp_ip = self._guess_udp_ip(ip)

                threading.Thread(target=self._udp_listen_loop, daemon=True).start()
                print(f"[RED-UDP] Escuchando en {self.udp_ip}:{self.udp_port}")
            except Exception as udp_e:
                print(f"[RED] Advertencia UDP: No se pudo iniciar la escucha: {udp_e}")
                self.udp_socket = None
                self.udp_ip = ""
                self.udp_port = 0

            threading.Thread(target=self._listen_loop, daemon=True).start()
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
            
        # NUEVO: Cerramos también UDP
        try:
            if hasattr(self, 'udp_socket') and self.udp_socket:
                self.udp_socket.close()
        except Exception:
            pass

    def request_all_users(self):
        """Solicita al servidor la lista global de todos los usuarios registrados."""
        payload = {
            "type": "GET_USERS"
        }
        print("[RED] → Solicitando catálogo global de usuarios (GET_USERS)")
        self._send(payload)

    def request_all_rooms(self):
        """Solicita al servidor la lista global de todas las salas de chat disponibles."""
        payload = {
            "type": "GET_ROOMS"
        }
        print("[RED] → Solicitando catálogo global de salas (GET_ROOMS)")
        self._send(payload)


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

    def _is_notify_target(self, obj: dict) -> bool:
        """
        True only when this client should show a visual notification.

        Important:
        - Broadcasts may be received by all connected clients.
        - notifyUsers decides who should see toast/badge/system UI feedback.
        - If notifyUsers is missing, we do NOT show visual notifications by default.
        """
        my_id = self.me.get("id")
        notify_users = obj.get("notifyUsers", [])

        if my_id is None or not isinstance(notify_users, list):
            return False

        return my_id in notify_users

    def login(self, username: str, password: str):
        """Envía AUTH al servidor."""
        self._send({
            "type":     "AUTH",
            "username": username,
            "password": password,
            "udpIp":    self.udp_ip,
            "udpPort":  self.udp_port,
        })

    def register(self, username: str, password: str, nickname: str | None = None):
        """Envía CREATE_ACCOUNT al servidor."""
        self._send({
            "type":     "CREATE_ACCOUNT",
            "username": username,
            "password": password,
            "nickname": nickname or username,
            "udpIp":    self.udp_ip,
            "udpPort":  self.udp_port,
        })

    def send_message(self, room_id: int, text: str, user_id: int | None = None):
        """Envía NEW_MESSAGE. El servidor actualiza la DB y hace broadcast."""
        self._send({
            "type":       "NEW_MESSAGE",
            "text":       text,
            "userId":     self.me.get("id") if user_id is None else user_id,
            "chatRoomId": room_id,
        })

    def send_system_message(self, room_id: int, text: str):
        """
        Guarda un mensaje de sistema en la BD.

        Convention:
        - userId = 0 means SYSTEM.
        - The GUI renders it with the same system-message style.
        """
        self.send_message(
            room_id,
            text,
            user_id=0
        )

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

    def _on_get_users_end(self, obj: dict):
        print(f"[RED] GET_USERS completo — {len(self.users)} usuarios totales")
        if self.on_all_users_loaded:
            self.on_all_users_loaded()

    def _on_get_rooms_end(self, obj: dict):
        print(f"[RED] GET_ROOMS completo — {len(self.rooms)} salas totales")
        if self.on_all_rooms_loaded:
            self.on_all_rooms_loaded()

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

    def _udp_listen_loop(self):
        """Escucha mensajes de Broadcast UDP en segundo plano."""
        while self.connected and hasattr(self, 'udp_socket') and self.udp_socket:
            try:
                # Esperamos recibir un datagrama UDP (máx 4096 bytes)
                data, addr = self.udp_socket.recvfrom(4096)
                raw_msg = data.decode(ENCODING).strip()
                
                if raw_msg:
                    print(f"[RED-UDP] 📢 Broadcast recibido de {addr}: {raw_msg}")
                    # El mensaje ya viene en formato JSON completo ("USER_ONLINE")
                    # Se lo pasamos al despachador igual que si viniera por TCP
                    self._dispatch(raw_msg)
            except Exception as e:
                if self.connected:
                    print(f"[RED-UDP] Error de escucha UDP: {e}")
                break

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
            "AUTH_RESPONSE":            self._on_auth_response,
            "CREATE_ACCOUNT_RESPONSE":  self._on_register_response,
            "SYNC_START":               self._on_sync_start,
            "SYNC_END":                 self._on_sync_end,
            "GET_USERS_END":  self._on_get_users_end,
            "GET_ROOMS_END":  self._on_get_rooms_end,
            "CHAT_USER":      self._on_sync_chat_user,   
            "CHATROOM":       self._on_sync_chatroom,     
            "MESSAGE":                  self._on_sync_message,
            "NEW_MESSAGE_RESPONSE":     self._on_new_message_response,
            "NEW_CHATROOM_RESPONSE":    self._on_new_chatroom_response,
            "ADD_USER_RESPONSE":        self._on_add_user_response,
            "REMOVE_USER_RESPONSE":     self._on_remove_user_response,
            "DELETE_MESSAGE_RESPONSE":  self._on_delete_message_response,
            "DELETE_CHATROOM_RESPONSE": self._on_delete_chatroom_response,
            "USER_ONLINE":              self._on_user_online,  # ← Mapeo del evento dinámico
          
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
    # ═══════════════════════════════════════════════════════════════

    def _on_sync_start(self, obj: dict):
        print("[RED] Sync iniciado — limpiando estado en memoria")
        self.rooms    = {}
        self.users    = {}
        self.messages = {}
        self._syncing           = True
        self._current_sync_room = None

    def _on_sync_chatroom(self, obj: dict):
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
        if not self._syncing:
            return
        user_id = obj["id"]
        self.users[user_id] = {
            "id":   user_id,
            "name": obj.get("name", ""),
        }
        print(f"[RED]   SYNC usuario #{user_id}: {obj.get('name')}")

    def _on_sync_message(self, obj: dict):
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
    # ═══════════════════════════════════════════════════════════════

    def _on_user_online(self, obj: dict):
        """
        Llega como un evento push dinámico cuando un usuario inicia sesión 
        o se registra de forma global en la plataforma.
        """
        user_id = obj.get("userId")
        username = obj.get("username")
        
        if user_id and username:
            # Lo agregamos al diccionario global de usuarios si no está registrado previamente
            if user_id not in self.users:
                self.users[user_id] = {"id": user_id, "name": username}
                print(f"[RED] Nuevo usuario conectado/registrado en el server: {username} (#{user_id})")
            
            # Disparamos el callback hacia el Controlador de la Interfaz
            if self.on_user_online:
                self.on_user_online(user_id, username)

    def _on_new_message_response(self, obj: dict):
        if not obj.get("success"):
            return

        msg_data = obj.get("message", {})
        room_id = msg_data.get("chatRoomId")

        msg = {
            "id":         msg_data.get("id"),
            "userId":     msg_data.get("userId"),
            "chatRoomId": room_id,
            "text":       msg_data.get("text", ""),
        }

        # Avoid duplicates when the same event arrives via TCP response and UDP broadcast.
        room_messages = self.messages.setdefault(room_id, [])
        if not any(existing.get("id") == msg["id"] for existing in room_messages):
            room_messages.append(msg)

        print(f"[RED] Nuevo mensaje #{msg['id']} en sala #{room_id}")

        # Only users included in notifyUsers show UI notification/toast.
        if self.on_new_message and self._is_notify_target(obj):
            self.on_new_message(room_id, msg)

    def _on_new_chatroom_response(self, obj: dict):
        if not obj.get("success"):
            return

        cr = obj.get("chatRoom", {})
        room_id = cr.get("id")
        coordinator_id = cr.get("coordinatorId")

        user_ids = list(cr.get("userIds", []))
        if coordinator_id and coordinator_id not in user_ids:
            user_ids.append(coordinator_id)

        room = {
            "id":            room_id,
            "name":          cr.get("name", ""),
            "coordinatorId": coordinator_id,
            "userIds":       user_ids,
            "messageIds":    list(cr.get("messageIds", [])),
            "requestIds":    list(cr.get("requestIds", [])),
        }

        self.rooms[room_id] = room
        self.messages.setdefault(room_id, [])

        print(f"[RED] Sala nueva/actualizada #{room_id}: {room['name']}")

        # Room creation changes global state, so every client can refresh the sidebar.
        if self.on_room_created:
            self.on_room_created(room)

    def _on_add_user_response(self, obj: dict):
        if not obj.get("success"):
            return

        room_id = obj.get("chatRoomId")
        user_id = obj.get("userId")
        chat_user = obj.get("chatUser", {})

        if user_id and chat_user:
            self.users[user_id] = {
                "id":       user_id,
                "name":     chat_user.get("nickname") or chat_user.get("username", ""),
                "username": chat_user.get("username", ""),
                "nickname": chat_user.get("nickname") or chat_user.get("username", ""),
            }

        cr = obj.get("chatRoom")
        if cr:
            room_id = cr.get("id", room_id)
            self.rooms[room_id] = {
                "id":            room_id,
                "name":          cr.get("name", ""),
                "coordinatorId": cr.get("coordinatorId"),
                "userIds":       list(cr.get("userIds", [])),
                "messageIds":    list(cr.get("messageIds", [])),
                "requestIds":    list(cr.get("requestIds", [])),
            }
        else:
            room = self.rooms.get(room_id)
            if room and user_id and user_id not in room.get("userIds", []):
                room.setdefault("userIds", []).append(user_id)

        print(f"[RED] Usuario #{user_id} agregado a sala #{room_id}")

        # This callback refreshes UI. System text is persisted separately as userId=0 message.
        if self.on_user_added:
            self.on_user_added(room_id, self.users.get(user_id, {"id": user_id}))

    def _on_remove_user_response(self, obj: dict):
        if not obj.get("success"):
            return

        room_id = obj.get("chatRoomId")
        user_id = obj.get("userId")

        cr = obj.get("chatRoom")
        if cr:
            room_id = cr.get("id", room_id)
            self.rooms[room_id] = {
                "id":            room_id,
                "name":          cr.get("name", ""),
                "coordinatorId": cr.get("coordinatorId"),
                "userIds":       list(cr.get("userIds", [])),
                "messageIds":    list(cr.get("messageIds", [])),
                "requestIds":    list(cr.get("requestIds", [])),
            }
        else:
            room = self.rooms.get(room_id)
            if room and user_id in room.get("userIds", []):
                room["userIds"].remove(user_id)

        print(f"[RED] Usuario #{user_id} removido de sala #{room_id}")

        # This callback refreshes UI. System text is persisted separately as userId=0 message.
        if self.on_user_removed:
            self.on_user_removed(room_id, user_id)

    def _on_delete_message_response(self, obj: dict):
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
        if not obj.get("success"):
            return
        room_id = obj.get("chatRoomId")
        self.rooms.pop(room_id, None)
        self.messages.pop(room_id, None)
        print(f"[RED] Sala #{room_id} eliminada de memoria")
        if self.on_room_deleted:
            self.on_room_deleted(room_id)

    # ─────────────────────────────────────────────────────────────
    # MÉTODOS DE PETICIÓN
    # ─────────────────────────────────────────────────────────────

    def remove_user(self, chat_room_id: int, user_id: int):
        payload = {
            "type": "REMOVE_USER",
            "chatRoomId": chat_room_id,
            "userId": user_id
        }
        self._send(payload)

    def delete_chatroom(self, chat_room_id: int):
        payload = {
            "type": "DELETE_CHATROOM",
            "chatRoomId": chat_room_id
        }
        self._send(payload)

    def delete_message(self, message_id: int):
        payload = {
            "type": "DELETE_MESSAGE",
            "messageId": message_id
        }
        self._send(payload)

    def create_account(self, username, password):
        payload = {
            "type": "CREATE_ACCOUNT",
            "username": username,
            "password": password
        }
        self._send(payload)