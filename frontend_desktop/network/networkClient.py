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

from cifrado import cifrar_texto, descifrar_texto

ENCODING = "utf-8"


class NetworkClient:
    def __init__(self):
        self.socket     = None
        self.connected  = False
        self._buf       = ""          # buffer TCP parcial
        self._sync_lock = threading.Event()  # se setea al terminar el sync
        self._send_lock = threading.Lock()   # protege connected + sendall

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
        self.on_all_users_loaded  = None  # ()
        self.on_all_rooms_loaded  = None  # ()
        

    # ═══════════════════════════════════════════════════════════════
    # CONEXIÓN
    # ═══════════════════════════════════════════════════════════════
    def ask_loadbalancer(self, lb_ip="127.0.0.1", lb_port=4000):
        print(f"[LB] Consultando load balancer {lb_ip}:{lb_port}...")

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as lb_socket:
                lb_socket.settimeout(5)
                lb_socket.connect((lb_ip, int(lb_port)))

                data = b""

                while b"\n" not in data:
                    chunk = lb_socket.recv(4096)

                    if not chunk:
                        break

                    data += chunk

            raw = data.decode(ENCODING, errors="replace").strip()

            print(f"[LB] RAW BYTES = {data}")
            print(f"[LB] RAW RECV  = [{raw}]")

            if not raw:
                print("[LB] Respuesta vacía. Revisa que estés conectando al load balancer correcto.")
                return None

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
        """Abre el socket TCP y el socket UDP de escucha."""
        print(f"[RED] Conectando a {ip}:{port}...")
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((ip, port))
            self.connected = True
            print("[RED] ¡Conexión TCP establecida!")
            threading.Thread(target=self._listen_loop, daemon=True).start()

            # --- NUEVO: HILO PARA ESCUCHAR BROADCASTS UDP ---
            try:
                self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                # IMPORTANTE: Permite que varios clientes en la misma PC escuchen el 5001
                self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if hasattr(socket, 'SO_REUSEPORT'):
                    self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                
                # Escuchamos en el puerto 5001 (en todas las interfaces "")
                self.udp_socket.bind(("", 5001))
                threading.Thread(target=self._udp_listen_loop, daemon=True).start()
                print("[RED] ¡Escuchando Broadcasts UDP en el puerto 5001!")
            except Exception as udp_e:
                print(f"[RED] Advertencia UDP: No se pudo iniciar la escucha: {udp_e}")
            # ------------------------------------------------

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
        with self._send_lock:
            if not self.connected:
                print("[RED] Error: no conectado.")
                return
            try:
                line = json.dumps(obj, ensure_ascii=False) + "\n"
                self.socket.sendall(line.encode(ENCODING))
                print(f"[RED] → SEND {obj.get('type', '?')}")
            except OSError as e:
                print(f"[RED] Error al enviar: {e}")
                self.connected = False

    def _get_udp_endpoint(self):
        """Devuelve (ip, port) del socket UDP local, para enviarlo al servidor en AUTH."""
        udp_ip = self._guess_udp_ip("")
        udp_port = 5001
        try:
            if hasattr(self, 'udp_socket') and self.udp_socket:
                udp_port = self.udp_socket.getsockname()[1]
        except Exception:
            pass
        return udp_ip, udp_port

    def login(self, username: str, password: str):
        """Envía AUTH al servidor con username y password cifrados."""
        udp_ip, udp_port = self._get_udp_endpoint()
        self._send({
            "type":     "AUTH",
            "username": cifrar_texto(username),
            "password": cifrar_texto(password),
            "udpIp":    udp_ip,
            "udpPort":  udp_port,
        })

    def register(self, username: str, password: str, nickname: str = None):
        """Envía CREATE_ACCOUNT al servidor con campos cifrados."""
        udp_ip, udp_port = self._get_udp_endpoint()
        self._send({
            "type":      "CREATE_ACCOUNT",
            "username":  cifrar_texto(username),
            "password":  cifrar_texto(password),
            "nickname":  cifrar_texto(nickname or username),
            "udpIp":     udp_ip,
            "udpPort":   udp_port,
        })

    def send_message(self, room_id: int, text: str):
        """Envía NEW_MESSAGE con texto cifrado."""
        self._send({
            "type":       "NEW_MESSAGE",
            "text":       cifrar_texto(text),
            "userId":     self.me.get("id"),
            "chatRoomId": room_id,
        })

    def create_room(self, name: str):
        """Crea una sala nueva con nombre cifrado."""
        self._send({
            "type":          "NEW_CHATROOM",
            "name":          cifrar_texto(name),
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

    def request_join_room(self, room_id: int):
        """Solicita unirse a una sala. La BD agrega mi id a requestIds."""
        self._send({
            "type":       "REQUEST",
            "chatRoomId": room_id,
            "userId":     self.me.get("id"),
        })

    def delete_join_request(self, room_id: int, user_id: int):
        """El coordinador rechaza/elimina un request pendiente."""
        self._send({
            "type":       "DELETE_REQUEST",
            "chatRoomId": room_id,
            "userId":     user_id,
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

    def request_join_room(self, room_id: int):
        """Solicita acceso a una sala privada."""
        self._send({
            "type": "REQUEST",
            "chatRoomId": room_id,
            "userId": self.me.get("id"),
        })

    def delete_join_request(self, room_id: int, user_id: int):
        """Rechaza/elimina una solicitud pendiente de acceso."""
        self._send({
            "type": "DELETE_REQUEST",
            "chatRoomId": room_id,
            "userId": user_id,
        })

    def send_system_message(self, room_id: int, text: str):
        """Envía mensaje persistente de sistema usando userId=0, con texto cifrado."""
        self._send({
            "type":       "NEW_MESSAGE",
            "text":       cifrar_texto(text),
            "userId":     0,
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
                    with self._send_lock:
                        self.connected = False
                    break
                self._buf += data.decode(ENCODING)
                self._process_buffer()
            except Exception as e:
                if self.connected:
                    print(f"[RED] Error en listen_loop: {e}")
                with self._send_lock:
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
            "REQUEST_RESPONSE":         self._on_request_response,
            "DELETE_REQUEST_RESPONSE":  self._on_delete_request_response,
            "DELETE_MESSAGE_RESPONSE":  self._on_delete_message_response,
            "DELETE_CHATROOM_RESPONSE": self._on_delete_chatroom_response,
            "REQUEST_RESPONSE":         self._on_request_response,
            "DELETE_REQUEST_RESPONSE":  self._on_delete_request_response,
            "USER_ONLINE":              self._on_user_online,
            "USER_OFFLINE":             self._on_user_offline,
          
        }

        handler = handlers.get(msg_type)
        if handler:
            handler(obj)
        else:
            print(f"[RED] Tipo desconocido: {msg_type}")

    # ═══════════════════════════════════════════════════════════════
    # HELPERS DE ESTADO LOCAL
    # ═══════════════════════════════════════════════════════════════

    def _display_name_from_user(self, user: dict) -> str:
        return (
            user.get("nickname")
            or user.get("name")
            or user.get("username")
            or str(user.get("id", "?"))
        )

    def _upsert_user(self, data: dict, online=None):
        if not data:
            return None

        user_id = data.get("id") or data.get("userId")
        if user_id is None:
            return None

        existing = self.users.get(user_id, {"id": user_id})

        username = data.get("username")
        if username is None:
            username = data.get("name")

        nickname = data.get("nickname")
        if nickname is None:
            nickname = data.get("name") or username

        if username is not None:
            username = descifrar_texto(username)
        if nickname is not None:
            nickname = descifrar_texto(nickname)

        existing["id"] = user_id

        if username is not None:
            existing["username"] = username

        if nickname is not None:
            existing["nickname"] = nickname
            existing["name"] = nickname
        elif username is not None and not existing.get("name"):
            existing["name"] = username

        if online is not None:
            existing["online"] = bool(online)
        else:
            existing.setdefault("online", False)

        self.users[user_id] = existing
        return existing

    def _normalize_room(self, cr: dict):
        if not cr:
            return None

        room_id = cr.get("id") or cr.get("chatRoomId")
        if room_id is None:
            return None

        existing = self.rooms.get(room_id, {})

        user_ids = list(cr.get("userIds", existing.get("userIds", [])))
        coordinator_id = cr.get("coordinatorId", existing.get("coordinatorId"))

        if coordinator_id is not None and coordinator_id not in user_ids:
            user_ids.append(coordinator_id)

        return {
            "id":            room_id,
            "name":          descifrar_texto(cr.get("name", existing.get("name", ""))),
            "coordinatorId": coordinator_id,
            "userIds":       user_ids,
            "messageIds":    list(cr.get("messageIds", existing.get("messageIds", []))),
            "requestIds":    list(cr.get("requestIds", existing.get("requestIds", []))),
            "notifications": existing.get("notifications", 0),
        }

    def _upsert_room(self, cr: dict):
        room = self._normalize_room(cr)

        if not room:
            return None

        self.rooms[room["id"]] = room
        self.messages.setdefault(room["id"], [])
        return room

    def _append_message_once(self, msg: dict) -> bool:
        """
        Agrega el mensaje solo si no existe todavía.
        Devuelve True si fue nuevo y False si era duplicado.
        """
        if not msg:
            return False

        room_id = msg.get("chatRoomId")
        msg_id = msg.get("id")

        if room_id is None or msg_id is None:
            return False

        room_messages = self.messages.setdefault(room_id, [])

        for existing in room_messages:
            if existing.get("id") == msg_id:
                return False

        room_messages.append(msg)

        room = self.rooms.get(room_id)
        if room is not None:
            message_ids = room.setdefault("messageIds", [])
            if msg_id not in message_ids:
                message_ids.append(msg_id)

        return True

    def _should_notify_ui(self, obj: dict) -> bool:
        """
        El broadcast puede llegar a todos.
        notifyUsers solo decide si esta GUI debe mostrar popup/badge/callback visual.
        Si notifyUsers no viene, permitimos el callback para respuestas TCP directas.
        """
        notify_users = obj.get("notifyUsers")

        if not isinstance(notify_users, list):
            return True

        return self.me.get("id") in notify_users


    # ═══════════════════════════════════════════════════════════════
    # HANDLERS — AUTH
    # ═══════════════════════════════════════════════════════════════

    def _on_auth_response(self, obj: dict):
        success = bool(obj.get("success"))
        if success:
            user = self._upsert_user(
                {
                    "id":       obj.get("userId"),
                    "username": obj.get("username", ""),
                    "nickname": obj.get("nickname") or obj.get("username", ""),
                },
                online=True
            )
            self.me = {
                "id":       user["id"],
                "username": user.get("username", ""),
                "nickname": user.get("nickname", ""),
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
        username = descifrar_texto(obj.get("username", ""))
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

        room = self._upsert_room(obj)

        if not room:
            return

        self._current_sync_room = room["id"]
        print(f"[RED]   SYNC sala #{room['id']}: {room.get('name')}")

    def _on_sync_chat_user(self, obj: dict):
        if not self._syncing:
            return

        user = self._upsert_user(obj, online=obj.get("online", False))

        if user:
            print(f"[RED]   SYNC usuario #{user['id']}: {self._display_name_from_user(user)}")

    def _on_sync_message(self, obj: dict):
        if not self._syncing:
            return

        room_id = obj.get("chatRoomId", self._current_sync_room)

        msg = {
            "id":         obj.get("id"),
            "userId":     obj.get("userId"),
            "chatRoomId": room_id,
            "text":       descifrar_texto(obj.get("text", "")),
        }

        if self._append_message_once(msg):
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
        Evento push cuando un usuario se conecta o se registra.
        """
        user_id  = obj.get("userId") or obj.get("id")
        username = obj.get("username") or obj.get("name", "")

        if user_id:
            data = {"id": user_id, "username": username}
            # Solo incluir nickname si el servidor lo mandó — evita sobreescribir
            # el nickname real (del sync) con el username cuando no viene el campo.
            if obj.get("nickname"):
                data["nickname"] = obj["nickname"]

            user = self._upsert_user(data, online=True)

            print(f"[RED] Usuario online: {self._display_name_from_user(user)} (#{user_id})")

            if self.on_user_online:
                self.on_user_online(user_id, self._display_name_from_user(user))

    def _on_user_offline(self, obj: dict):
        """
        Evento push cuando un usuario se desconecta.
        """
        user_id  = obj.get("userId") or obj.get("id")
        username = obj.get("username") or obj.get("name", "")

        if user_id:
            data = {"id": user_id, "username": username}
            if obj.get("nickname"):
                data["nickname"] = obj["nickname"]

            user = self._upsert_user(data, online=False)

            print(f"[RED] Usuario offline: {self._display_name_from_user(user)} (#{user_id})")

            if self.on_user_offline:
                self.on_user_offline(user_id, self._display_name_from_user(user))

    def _on_new_message_response(self, obj: dict):
        if not obj.get("success"):
            return

        msg_data = obj.get("message", {})
        room_id  = msg_data.get("chatRoomId")

        msg = {
            "id":         msg_data.get("id"),
            "userId":     msg_data.get("userId"),
            "chatRoomId": room_id,
            "text":       descifrar_texto(msg_data.get("text", "")),
        }

        was_new = self._append_message_once(msg)

        if not was_new:
            print(f"[RED] Mensaje duplicado ignorado #{msg.get('id')} en sala #{room_id}")
            return

        print(f"[RED] Nuevo mensaje #{msg['id']} en sala #{room_id}")

        if self.on_new_message and self._should_notify_ui(obj):
            self.on_new_message(room_id, msg)

    def _on_new_chatroom_response(self, obj: dict):
        if not obj.get("success"):
            return

        room = self._upsert_room(obj.get("chatRoom", {}))

        if not room:
            return

        print(f"[RED] Sala #{room['id']} actualizada/creada: {room['name']}")

        if self.on_room_created and self._should_notify_ui(obj):
            self.on_room_created(room)

    def _on_add_user_response(self, obj: dict):
        if not obj.get("success"):
            return

        room_id = obj.get("chatRoomId")
        user_id = obj.get("userId")
        chat_user = obj.get("chatUser", {})

        if chat_user:
            chat_user = dict(chat_user)
            chat_user.setdefault("id", user_id)
            self._upsert_user(chat_user)

        if obj.get("chatRoom"):
            self._upsert_room(obj.get("chatRoom"))
        else:
            room = self.rooms.get(room_id)

            if room and user_id:
                if user_id not in room.setdefault("userIds", []):
                    room["userIds"].append(user_id)

                if user_id in room.setdefault("requestIds", []):
                    room["requestIds"].remove(user_id)

        print(f"[RED] Usuario #{user_id} agregado a sala #{room_id}")

        if self.on_user_added and self._should_notify_ui(obj):
            self.on_user_added(room_id, self.users.get(user_id, {"id": user_id}))

    def _on_remove_user_response(self, obj: dict):
        if not obj.get("success"):
            return

        room_id = obj.get("chatRoomId")
        user_id = obj.get("userId")

        if obj.get("chatRoom"):
            self._upsert_room(obj.get("chatRoom"))
        else:
            room = self.rooms.get(room_id)

            if room and user_id in room.get("userIds", []):
                room["userIds"].remove(user_id)

        print(f"[RED] Usuario #{user_id} removido de sala #{room_id}")

        if self.on_user_removed and self._should_notify_ui(obj):
            self.on_user_removed(room_id, user_id)

    def _on_request_response(self, obj: dict):
        if not obj.get("success"):
            return

        room = self._upsert_room(obj.get("chatRoom", {}))
        user_id = obj.get("userId")

        if not room:
            room_id = obj.get("chatRoomId")
            room = self.rooms.get(room_id)

            if room and user_id not in room.setdefault("requestIds", []):
                room["requestIds"].append(user_id)

        room_id = room.get("id") if room else obj.get("chatRoomId")
        print(f"[RED] Request de usuario #{user_id} registrado en sala #{room_id}")

        if self.on_room_created and self._should_notify_ui(obj):
            self.on_room_created(room)

    def _on_delete_request_response(self, obj: dict):
        if not obj.get("success"):
            return

        room = self._upsert_room(obj.get("chatRoom", {}))
        user_id = obj.get("userId")

        if not room:
            room_id = obj.get("chatRoomId")
            room = self.rooms.get(room_id)

            if room and user_id in room.get("requestIds", []):
                room["requestIds"].remove(user_id)

        room_id = room.get("id") if room else obj.get("chatRoomId")
        print(f"[RED] Request de usuario #{user_id} eliminado de sala #{room_id}")

        if self.on_room_created and self._should_notify_ui(obj):
            self.on_room_created(room)

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

    def create_account(self, username, password):
        udp_ip, udp_port = self._get_udp_endpoint()
        payload = {
            "type":     "CREATE_ACCOUNT",
            "username": cifrar_texto(username),
            "password": cifrar_texto(password),
            "udpIp":    udp_ip,
            "udpPort":  udp_port,
        }
        self._send(payload)