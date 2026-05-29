"""
networkClient.py — Cliente TCP para el servidor C (chatServerJson.c)
=====================================================================
Versión integrada con soporte de Load Balancer.

Flujo de sesión:
  1. ask_loadbalancer(lb_ip, lb_port)  → pregunta al LB a qué server ir
  2. connect(ip, port)                 → abre socket TCP con el server asignado
  3. login() / register()              → envía AUTH / CREATE_ACCOUNT (incluye udpPort)
  4. SYNC_START ... SYNC_END           → llena self.rooms, self.users, self.messages
  5. Eventos push (UDP + TCP)          → actualizan el estado en memoria

Callbacks que la GUI debe inyectar
───────────────────────────────────
on_login_response(success, message)
on_register_response(success, user_id, username)
on_sync_complete()
on_new_message(room_id, msg_dict)
on_user_added(room_id, user_dict)
on_user_removed(room_id, user_id)
on_room_created(room_dict)
on_message_deleted(room_id, message_id)
on_room_deleted(room_id)
on_join_requested(room_id, user_id)          ← nuevo
on_join_request_received(room_id, user_id, username)  ← nuevo
on_user_online(user_id, username)
on_user_offline(user_id, username)           ← conservado del github
on_server_disconnected()
on_all_users_loaded()                        ← conservado del github
on_all_rooms_loaded()                        ← conservado del github
"""

import json
import socket
import threading

ENCODING = "utf-8"


class NetworkClient:
    def __init__(self):
        self.socket    = None
        self.connected = False
        self._buf      = ""
        self._sync_lock = threading.Event()

        # ── Estado en memoria ────────────────────────────────────
        self._udp_port = 0
        self._local_ip = ""
        self.me        = {}   # {"id": int, "username": str}
        self.rooms     = {}   # {room_id: {id, name, coordinatorId, userIds, requestIds}}
        self.users     = {}   # {user_id: {id, name}}
        self.messages  = {}   # {room_id: [{id, userId, chatRoomId, text}]}

        # Estado interno del sync
        self._syncing           = False
        self._current_sync_room = None

        # ── Callbacks para la GUI ────────────────────────────────
        self.on_login_response      = None  # (success, message)
        self.on_register_response   = None  # (success, user_id, username)
        self.on_sync_complete       = None  # ()
        self.on_new_message         = None  # (room_id, msg_dict)
        self.on_user_added          = None  # (room_id, user_dict)
        self.on_user_removed        = None  # (room_id, user_id)
        self.on_room_created        = None  # (room_dict)
        self.on_message_deleted     = None  # (room_id, message_id)
        self.on_room_deleted        = None  # (room_id)
        self.on_join_requested      = None  # (room_id, user_id)
        self.on_join_request_received = None  # (room_id, user_id, username)
        self.on_user_online         = None  # (user_id, username)
        self.on_user_offline        = None  # (user_id, username)  ← del github
        self.on_server_disconnected = None  # ()
        self.on_all_users_loaded    = None  # ()  ← del github
        self.on_all_rooms_loaded    = None  # ()  ← del github

    # ═══════════════════════════════════════════════════════════════
    # LOAD BALANCER
    # ═══════════════════════════════════════════════════════════════

    # ═══════════════════════════════════════════════════════════════
    # LOAD BALANCER
    # ═══════════════════════════════════════════════════════════════

    def ask_loadbalancer(self, lb_ip: str, lb_port: int) -> tuple:
        """
        Pregunta al load balancer a qué ChatServer conectarse.
        Retorna (ip, port) del server elegido.
        Si el LB no responde o rechaza, retorna (None, None) para activar el fallback en AppController.
        """
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect((lb_ip, lb_port))
            data = s.recv(1024).decode("utf-8").strip()
            s.close()
            
            obj = json.loads(data)
            if obj.get("success"):
                ip   = obj["ip"]
                port = obj["port"]
                print(f"[RED] LB asignó servidor → {ip}:{port}")
                return (ip, port)
            else:
                print(f"[RED] LB sin servers disponibles: {obj.get('error')}")
        except Exception as e:
            print(f"[RED] LB no alcanzable: {e}")
            
        # CORRECCIÓN: Devolver None, None en lugar de (lb_ip, lb_port)
        # Esto le avisa al AppController que debe usar su Plan B (servidores por defecto)
        return (None, None)

    # ═══════════════════════════════════════════════════════════════
    # CONEXIÓN
    # ═══════════════════════════════════════════════════════════════

    def connect(self, ip="127.0.0.1", port=5000) -> bool:
        """Abre el socket TCP al ChatServer y el socket UDP de escucha."""
        print(f"[RED] Conectando a {ip}:{port}...")
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((ip, port))
            self.connected = True
            self._local_ip = self.socket.getsockname()[0]
            print(f"[RED] ¡Conexión TCP establecida! (IP local: {self._local_ip})")
            threading.Thread(target=self._listen_loop, daemon=True).start()

            # ── Socket UDP efímero para recibir broadcasts/unicasts del servidor ──
            try:
                self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if hasattr(socket, "SO_REUSEPORT"):
                    self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                # Puerto 0 → el SO asigna uno libre (evita conflictos entre clientes)
                self.udp_socket.bind(("", 0))
                self._udp_port = self.udp_socket.getsockname()[1]
                print(f"[RED] UDP escuchando en puerto dinámico: {self._udp_port}")
                threading.Thread(target=self._udp_listen_loop, daemon=True).start()
            except Exception as udp_e:
                print(f"[RED] Advertencia UDP: No se pudo iniciar la escucha: {udp_e}")

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
            if hasattr(self, "udp_socket") and self.udp_socket:
                self.udp_socket.close()
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
        """Envía AUTH al servidor (incluye udpPort y udpIp para notificaciones push)."""
        self._send({
            "type":     "AUTH",
            "username": username,
            "password": password,
            "udpPort":  self._udp_port,
            "udpIp":    self._local_ip,
        })

    def register(self, username: str, password: str, nickname: str = None):
        """Envía CREATE_ACCOUNT al servidor."""
        self._send({
            "type":     "CREATE_ACCOUNT",
            "username": username,
            "password": password,
            "nickname": nickname or username,
            "udpPort":  self._udp_port,
            "udpIp":    self._local_ip,
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

    def request_join_room(self, room_id: int):
        self._send({
            "type":       "REQUEST",
            "userId":     self.me.get("id"),
            "chatRoomId": room_id,
        })

    def delete_join_request(self, room_id: int, user_id: int):
        self._send({
            "type":       "DELETE_REQUEST",
            "chatRoomId": room_id,
            "userId":     user_id,
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

    # Aliases de compatibilidad con código viejo
    def remove_user(self, chat_room_id: int, user_id: int):
        self.remove_user_from_room(user_id, chat_room_id)

    def delete_chatroom(self, chat_room_id: int):
        self.delete_room(chat_room_id)

    def create_account(self, username: str, password: str, nickname: str = None):
        self.register(username, password, nickname)

    def request_all_users(self):
        self._send({"type": "GET_USERS"})

    def request_all_rooms(self):
        self._send({"type": "GET_ROOMS"})

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
    # HILOS DE ESCUCHA
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
        """Escucha mensajes UDP (broadcasts y unicasts del ChatServer)."""
        while self.connected and hasattr(self, "udp_socket") and self.udp_socket:
            try:
                data, addr = self.udp_socket.recvfrom(4096)
                raw_msg = data.decode(ENCODING).strip()
                if raw_msg:
                    print(f"[RED-UDP] Recibido de {addr}: {raw_msg[:80]}")
                    self._dispatch(raw_msg)
            except Exception as e:
                if self.connected:
                    print(f"[RED-UDP] Error de escucha UDP: {e}")
                break

    def _process_buffer(self):
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.strip()
            if line:
                self._dispatch(line)

    # ═══════════════════════════════════════════════════════════════
    # DESPACHADOR
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
            "GET_USERS_END":            self._on_get_users_end,
            "GET_ROOMS_END":            self._on_get_rooms_end,
            "NEW_MESSAGE_RESPONSE":     self._on_new_message_response,
            "NEW_CHATROOM_RESPONSE":    self._on_new_chatroom_response,
            "REQUEST_RESPONSE":         self._on_request_response,
            "DELETE_REQUEST_RESPONSE":  self._on_delete_request_response,
            "ADD_USER_RESPONSE":        self._on_add_user_response,
            "REMOVE_USER_RESPONSE":     self._on_remove_user_response,
            "DELETE_MESSAGE_RESPONSE":  self._on_delete_message_response,
            "DELETE_CHATROOM_RESPONSE": self._on_delete_chatroom_response,
            "USER_ONLINE":              self._on_user_online,
            "USER_OFFLINE":             self._on_user_offline,
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
                "nickname": obj.get("nickname", obj.get("username", "")),
            }
            print(f"[RED] Login OK → id={self.me['id']} username={self.me['username']}")
            if self.on_login_response:
                self.on_login_response(True, "Login correcto")
        else:
            print("[RED] Login fallido")
            if self.on_login_response:
                self.on_login_response(False, "Credenciales incorrectas")

    def _on_register_response(self, obj: dict):
        success  = bool(obj.get("success"))
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
            "messageIds":    list(obj.get("messageIds", [])),
            "requestIds":    list(obj.get("requestIds", [])),
        }
        self.messages.setdefault(room_id, [])
        self._current_sync_room = room_id
        print(f"[RED]   SYNC sala #{room_id}: {obj.get('name')}")

    def _on_sync_chat_user(self, obj: dict):
        if not self._syncing:
            return
        user_id = obj["id"]
        self.users[user_id] = {
            "id":       user_id,
            "name":     obj.get("name", obj.get("username", "")),
            "nickname": obj.get("nickname", obj.get("name", obj.get("username", ""))),
        }
        print(f"[RED]   SYNC usuario #{user_id}: {self.users[user_id]['name']}")

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

    def _on_get_users_end(self, obj: dict):
        print(f"[RED] GET_USERS completo — {len(self.users)} usuarios totales")
        if self.on_all_users_loaded:
            self.on_all_users_loaded()

    def _on_get_rooms_end(self, obj: dict):
        print(f"[RED] GET_ROOMS completo — {len(self.rooms)} salas totales")
        if self.on_all_rooms_loaded:
            self.on_all_rooms_loaded()

    # ═══════════════════════════════════════════════════════════════
    # HANDLERS — EVENTOS EN TIEMPO REAL
    # ═══════════════════════════════════════════════════════════════

    def _on_user_online(self, obj: dict):
        user_id  = obj.get("userId")
        username = obj.get("username")
        if user_id and username:
            if user_id not in self.users:
                self.users[user_id] = {"id": user_id, "name": username, "nickname": username}
            print(f"[RED] USER_ONLINE: {username} (#{user_id})")
            if self.on_user_online:
                self.on_user_online(user_id, username)

    def _on_user_offline(self, obj: dict):
        user_id  = obj.get("userId")
        username = obj.get("username", "")
        if user_id:
            self.users.pop(user_id, None)
        print(f"[RED] USER_OFFLINE: {username} (#{user_id})")
        if self.on_user_offline:
            self.on_user_offline(user_id, username)

    # ── Helper: upsert sala desde un payload chatRoom ────────────
    def _upsert_chatroom_from_payload(self, cr: dict):
        if not cr:
            return None
        room_id = cr.get("id")
        if room_id is None:
            return None
        room = {
            "id":            room_id,
            "name":          cr.get("name", ""),
            "coordinatorId": cr.get("coordinatorId"),
            "userIds":       list(cr.get("userIds", [])),
            "messageIds":    list(cr.get("messageIds", [])),
            "requestIds":    list(cr.get("requestIds", [])),
        }
        self.rooms[room_id] = room
        self.messages.setdefault(room_id, [])
        return room

    def _on_new_message_response(self, obj: dict):
        if not obj.get("success"):
            return
        msg_data = obj.get("message", {})
        room_id  = msg_data.get("chatRoomId")
        msg_id   = msg_data.get("id")
        # Dedup: evitar duplicar si el remitente ya lo insertó
        if any(m.get("id") == msg_id for m in self.messages.get(room_id, [])):
            return
        msg = {
            "id":         msg_id,
            "userId":     msg_data.get("userId"),
            "chatRoomId": room_id,
            "text":       msg_data.get("text", ""),
        }
        self.messages.setdefault(room_id, []).append(msg)
        print(f"[RED] Nuevo mensaje #{msg['id']} en sala #{room_id}")
        if self.on_new_message:
            self.on_new_message(room_id, msg)

    def _on_new_chatroom_response(self, obj: dict):
        if not obj.get("success"):
            return
        room = self._upsert_chatroom_from_payload(obj.get("chatRoom", {}))
        if not room:
            return
        print(f"[RED] Sala nueva/actualizada #{room['id']}: {room['name']}")
        if self.on_room_created:
            self.on_room_created(room)

    def _on_request_response(self, obj: dict):
        if not obj.get("success"):
            return
        room     = self._upsert_chatroom_from_payload(obj.get("chatRoom", {}))
        room_id  = room["id"] if room else obj.get("chatRoomId")
        user_id  = obj.get("userId")
        chat_user = obj.get("chatUser", {})
        if user_id and chat_user:
            self.users[user_id] = {
                "id":       user_id,
                "name":     chat_user.get("username", chat_user.get("name", "")),
                "nickname": chat_user.get("nickname", chat_user.get("username", "")),
            }
        print(f"[RED] Solicitud de usuario #{user_id} para sala #{room_id}")
        if self.on_join_requested:
            self.on_join_requested(room_id, user_id)

    def _on_delete_request_response(self, obj: dict):
        if not obj.get("success"):
            return
        cr = obj.get("chatRoom")
        if cr:
            self._upsert_chatroom_from_payload(cr)
        room_id = cr.get("id") if cr else obj.get("chatRoomId")
        user_id = obj.get("userId")
        print(f"[RED] DELETE_REQUEST: usuario #{user_id} removido de pendientes en sala #{room_id}")
        if self.on_join_request_received:
            self.on_join_request_received(room_id, user_id, "")

    def _on_add_user_response(self, obj: dict):
        if not obj.get("success"):
            return
        room    = self._upsert_chatroom_from_payload(obj.get("chatRoom", {}))
        room_id = obj.get("chatRoomId")
        user_id = obj.get("userId")
        chat_user = obj.get("chatUser", {})
        if user_id and chat_user:
            self.users[user_id] = {
                "id":       user_id,
                "name":     chat_user.get("username", chat_user.get("name", "")),
                "nickname": chat_user.get("nickname", chat_user.get("username", "")),
            }
        if not room:
            room = self.rooms.get(room_id)
            if room and user_id:
                if user_id not in room.get("userIds", []):
                    room.setdefault("userIds", []).append(user_id)
                if user_id in room.get("requestIds", []):
                    room["requestIds"].remove(user_id)
        print(f"[RED] Usuario #{user_id} agregado a sala #{room_id}")
        if self.on_user_added:
            self.on_user_added(room_id, self.users.get(user_id, {"id": user_id}))

    def _on_remove_user_response(self, obj: dict):
        if not obj.get("success"):
            return
        room    = self._upsert_chatroom_from_payload(obj.get("chatRoom", {}))
        room_id = obj.get("chatRoomId")
        user_id = obj.get("userId")
        if not room:
            room = self.rooms.get(room_id)
            if room and user_id in room.get("userIds", []):
                room["userIds"].remove(user_id)
        print(f"[RED] Usuario #{user_id} removido de sala #{room_id}")
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