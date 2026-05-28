"""
protocol.py — Protocolo JSON/TCP para el cliente Python (web_server.py)
=======================================================================
Mapea el protocolo real de chatServerJson.c / database_server.

Outgoing (cliente → servidor C):
  - AUTH, CREATE_ACCOUNT, NEW_MESSAGE, NEW_CHATROOM, ADD_USER,
    REMOVE_USER, DELETE_MESSAGE, DELETE_CHATROOM

Incoming (servidor C → cliente):
  - AUTH_RESPONSE + SYNC (SYNC_START / CHATROOM / CHAT_USER / MESSAGE / SYNC_END)
  - NEW_MESSAGE_RESPONSE, NEW_CHATROOM_RESPONSE, ADD_USER_RESPONSE,
    REMOVE_USER_RESPONSE, DELETE_CHATROOM_RESPONSE
  - USER_ONLINE (broadcast UDP)
"""

import json

FRAME_SEP = "\n"


# ══════════════════════════════════════════════════════════════════════
# CONSTANTES  —  valores wire que el servidor C entiende
# ══════════════════════════════════════════════════════════════════════

class Protocol:

    # ── Outgoing ────────────────────────────────────────────────────
    REQ_LOGIN       = "AUTH"
    REQ_LOGOUT      = "LOGOUT"
    REQ_CREATE_ROOM = "NEW_CHATROOM"
    REQ_SEND_MSG    = "NEW_MESSAGE"
    REQ_LEAVE_ROOM  = "REMOVE_USER"
    REQ_DELETE_ROOM = "DELETE_CHATROOM"
    REQ_ADD_USER    = "ADD_USER"
    REQ_JOIN_ROOM   = "JOIN_REQUEST"

    # ── Incoming: respuestas ────────────────────────────────────────
    RES_LOGIN       = "AUTH_RESPONSE"
    RES_CREATE_ROOM = "NEW_CHATROOM_RESPONSE"
    RES_SEND_MSG    = "NEW_MESSAGE_RESPONSE"
    RES_LEAVE_ROOM  = "REMOVE_USER_RESPONSE"
    RES_DELETE_ROOM = "DELETE_CHATROOM_RESPONSE"
    RES_ADD_USER    = "ADD_USER_RESPONSE"
    RES_JOIN_ROOM   = "REQUEST_RESPONSE"

    # ── Incoming: sync inicial ──────────────────────────────────────
    SYNC_START  = "SYNC_START"
    SYNC_END    = "SYNC_END"
    SYNC_ROOM   = "CHATROOM"
    SYNC_USER   = "CHAT_USER"
    SYNC_MSG    = "MESSAGE"

    # ── Incoming: eventos push ──────────────────────────────────────
    EVT_USER_ONLINE  = "USER_ONLINE"
    EVT_USER_OFFLINE = "USER_OFFLINE"

    # ════════════════════════════════════════════════════════════════
    # BUILDERS  —  JSON plano sin wrapper "payload"
    # ════════════════════════════════════════════════════════════════

    @staticmethod
    def _flat(obj: dict) -> bytes:
        raw = json.dumps(obj, ensure_ascii=False) + FRAME_SEP
        print(f"[proto] → SEND {obj.get('type','?')}  {raw.strip()}")
        return raw.encode("utf-8")

    @staticmethod
    def build_login(username: str, password: str) -> bytes:
        return Protocol._flat({"type": "AUTH",
                               "username": username, "password": password})

    @staticmethod
    def build_register(username: str, password: str) -> bytes:
        return Protocol._flat({"type": "CREATE_ACCOUNT",
                               "username": username, "password": password})

    @staticmethod
    def build_logout() -> bytes:
        return Protocol._flat({"type": "LOGOUT"})

    @staticmethod
    def build_create_room(name: str, coordinator_id: int) -> bytes:
        return Protocol._flat({"type": "NEW_CHATROOM",
                               "name": name, "coordinatorId": coordinator_id})

    @staticmethod
    def build_send_msg(room_id: int, text: str, user_id: int) -> bytes:
        return Protocol._flat({"type": "NEW_MESSAGE",
                               "text": text,
                               "userId": user_id,
                               "chatRoomId": room_id})

    @staticmethod
    def build_leave_room(room_id: int, user_id: int) -> bytes:
        return Protocol._flat({"type": "REMOVE_USER",
                               "chatRoomId": room_id, "userId": user_id})

    @staticmethod
    def build_add_user(room_id: int, user_id: int) -> bytes:
        return Protocol._flat({"type": "ADD_USER",
                               "chatRoomId": room_id, "userId": user_id})

    @staticmethod
    def build_request_join(room_id: int, user_id: int) -> bytes:
        return Protocol._flat({"type": "JOIN_REQUEST",
                               "chatRoomId": room_id, "userId": user_id})

    @staticmethod
    def build_delete_room(room_id: int) -> bytes:
        return Protocol._flat({"type": "DELETE_CHATROOM", "chatRoomId": room_id})

    # ════════════════════════════════════════════════════════════════
    # PARSER  —  maneja tanto JSON plano como con wrapper "payload"
    # ════════════════════════════════════════════════════════════════

    @staticmethod
    def parse(raw: str) -> dict:
        raw = raw.strip()
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProtocolError(f"JSON inválido: {e}  raw={raw!r}")

        if "type" not in obj:
            raise ProtocolError(f"Trama sin 'type': {raw!r}")

        if "payload" in obj:
            payload = obj["payload"]
        else:
            payload = {k: v for k, v in obj.items() if k not in ("type", "status")}

        return {
            "cmd":     obj["type"],
            "status":  obj.get("status", ""),
            "payload": payload,
        }


# ══════════════════════════════════════════════════════════════════════
# Excepción propia del protocolo
# ══════════════════════════════════════════════════════════════════════

class ProtocolError(Exception):
    pass


# ══════════════════════════════════════════════════════════════════════
# DISPATCHER  —  integración directa con web_server.py
# ══════════════════════════════════════════════════════════════════════

class ProtocolDispatcher:
    """
    Parsea cada trama recibida del servidor C y emite el evento
    SocketIO correcto al browser del cliente correspondiente.

    Estado en memoria por sid (igual que NetworkClient del desktop):
      _user_ids  {sid: int}                         userId autenticado
      _rooms     {sid: {room_id: room_dict}}        salas del usuario
      _users     {sid: {user_id: username_str}}     todos los usuarios conocidos
      _messages  {sid: {room_id: [msg_dict, ...]}}  historial en memoria
      _sync      {sid: dict}                        buffer temporal del SYNC inicial
    """

    def __init__(self, socketio_instance):
        self.sio = socketio_instance

        self._user_ids: dict[str, int]              = {}
        self._rooms:    dict[str, dict]             = {}
        self._users:    dict[str, dict]             = {}
        self._messages: dict[str, dict]             = {}
        self._sync:     dict[str, dict]             = {}

        self._handlers = {
            Protocol.RES_LOGIN:            self._on_login,
            "CREATE_ACCOUNT_RESPONSE":     self._on_register,
            Protocol.SYNC_START:      self._on_sync_start,
            Protocol.SYNC_ROOM:       self._on_sync_room,
            Protocol.SYNC_USER:       self._on_sync_user,
            Protocol.SYNC_MSG:        self._on_sync_msg,
            Protocol.SYNC_END:        self._on_sync_end,
            Protocol.RES_CREATE_ROOM: self._on_create_room,
            Protocol.RES_SEND_MSG:    self._on_new_message,
            Protocol.RES_LEAVE_ROOM:  self._on_leave_room,
            Protocol.RES_ADD_USER:    self._on_add_user,
            Protocol.RES_DELETE_ROOM: self._on_delete_room,
            Protocol.RES_JOIN_ROOM:        self._on_join_request_response,
            "JOIN_REQUEST_RESPONSE":       self._on_join_request_response,
            "DELETE_REQUEST_RESPONSE":     self._on_join_request_response,
            Protocol.EVT_USER_ONLINE:  self._on_user_online,
            Protocol.EVT_USER_OFFLINE: self._on_user_offline,
        }

    # ── sid helpers ──────────────────────────────────────────────────

    def get_user_id(self, sid: str) -> int:
        return self._user_ids.get(sid, 0)

    def get_user_id_by_name(self, sid: str, username: str) -> int:
        for uid, name in self._users.get(sid, {}).items():
            if name == username:
                return uid
        return 0

    def remove_sid(self, sid: str):
        self._user_ids.pop(sid, None)
        self._sync.pop(sid, None)
        self._rooms.pop(sid, None)
        self._users.pop(sid, None)
        self._messages.pop(sid, None)

    def _username(self, sid: str, user_id) -> str:
        """Resuelve un userId a username; fallback al string del ID."""
        return self._users.get(sid, {}).get(user_id, str(user_id))

    # ── dispatch ─────────────────────────────────────────────────────

    def dispatch(self, sid: str, raw: str):
        print(f"[dispatcher] ← RAW  {raw[:160]}")
        try:
            frame = Protocol.parse(raw)
        except ProtocolError as e:
            print(f"[dispatcher] ERROR parse: {e}")
            return

        print(f"[dispatcher] ← RECV {frame['cmd']}")
        handler = self._handlers.get(frame["cmd"])
        if handler:
            try:
                handler(sid, frame["status"], frame["payload"])
            except Exception as e:
                import traceback
                print(f"[dispatcher] ERROR en handler {frame['cmd']}: {e}")
                traceback.print_exc()
        else:
            print(f"[dispatcher] Comando desconocido: {frame['cmd']}")

    # ── Auth ─────────────────────────────────────────────────────────

    def _on_login(self, sid, status, p):
        if p.get("success") == 1:
            user_id  = p.get("userId", 0)
            username = p.get("username", "")
            self._user_ids[sid] = user_id
            self._rooms[sid]    = {}
            # Pre-carga el propio usuario para que member_names lo resuelva aunque
            # el servidor no mande CHAT_USER para el usuario logueado
            self._users[sid]    = {user_id: username}
            self._messages[sid] = {}
            self._sync[sid]     = {
                "rooms":    {},
                "users":    {user_id: username},
                "messages": {},
            }
            print(f"[dispatcher] LOGIN OK → userId={user_id} username={username}")
            self.sio.emit("login_success",
                          {"username": username, "nickname": username,
                           "userId": user_id}, to=sid)
        else:
            print(f"[dispatcher] LOGIN FAIL  payload={p}")
            self.sio.emit("login_error",
                          {"message": "Credenciales inválidas"}, to=sid)

    def _on_register(self, sid, status, p):
        if p.get("success") == 1:
            user_id  = p.get("userId", 0)
            username = p.get("username", "")
            # Inicializa sesión igual que login — el C server ya está en Phase 2
            self._user_ids[sid] = user_id
            self._users[sid]    = {user_id: username}
            self._rooms[sid]    = {}
            self._messages[sid] = {}
            self._sync[sid]     = {"rooms": {}, "users": {user_id: username}, "messages": {}}
            print(f"[dispatcher] REGISTER OK → userId={user_id} username={username}")
            self.sio.emit("register_success", {"username": username}, to=sid)
        else:
            print(f"[dispatcher] REGISTER FAIL  payload={p}")
            self.sio.emit("register_error",
                          {"message": "El usuario ya existe o los datos son inválidos"}, to=sid)

    # ── Sync inicial ─────────────────────────────────────────────────

    def _on_sync_start(self, sid, status, p):
        my_id    = self._user_ids.get(sid, 0)
        my_name  = self._users.get(sid, {}).get(my_id, "")
        self._sync[sid] = {
            "rooms":    {},
            "users":    {my_id: my_name} if my_id else {},
            "messages": {},
        }
        print(f"[dispatcher] SYNC_START (my_id={my_id} my_name={my_name!r})")

    def _on_sync_room(self, sid, status, p):
        buf = self._sync.get(sid)
        if buf is None:
            return
        room_id = p.get("id")
        buf["rooms"][room_id] = {
            "id":            room_id,
            "name":          p.get("name", ""),
            "coordinatorId": p.get("coordinatorId"),
            "userIds":       p.get("userIds", []),
        }
        print(f"[dispatcher]   SYNC sala #{room_id}: {p.get('name')}")

    def _on_sync_user(self, sid, status, p):
        buf = self._sync.get(sid)
        if buf is None:
            return
        uid  = p.get("id")
        name = p.get("name") or p.get("username", "")
        buf["users"][uid] = name
        print(f"[dispatcher]   SYNC usuario #{uid}: {name}")

    def _on_sync_msg(self, sid, status, p):
        buf = self._sync.get(sid)
        if buf is None:
            return
        room_id = p.get("chatRoomId")
        buf["messages"].setdefault(room_id, []).append({
            "user_id": p.get("userId"),
            "text":    p.get("text", ""),
            "ts":      p.get("id", 0),
        })

    def _on_sync_end(self, sid, status, p):
        buf     = self._sync.pop(sid, {"rooms": {}, "users": {}, "messages": {}})
        users   = buf["users"]
        my_id   = self._user_ids.get(sid)

        # Persiste el estado para que join_chat_view y coord pueda leerlo
        self._rooms[sid]    = buf["rooms"]
        self._users[sid]    = users
        self._messages[sid] = buf["messages"]

        rooms_list = []
        for r in buf["rooms"].values():
            member_names = [users.get(uid, str(uid)) for uid in r.get("userIds", [])]
            rooms_list.append({
                "id":            r["id"],
                "name":          r["name"],
                "notifications": 0,
                "members":       member_names,
            })

        all_users = [
            {"username": name, "nickname": name, "online": True}
            for uid, name in users.items()
            if uid != my_id
        ]

        print(f"[dispatcher] SYNC_END → {len(rooms_list)} salas, {len(users)} usuarios")
        self.sio.emit("lobby_update", {
            "rooms":     rooms_list,
            "users":     all_users,
            "all_users": all_users,
        }, to=sid)

    # ── join_chat_view (solicitud desde el browser) ───────────────────

    def handle_join_chat_view(self, sid: str, room_id: int):
        rooms    = self._rooms.get(sid, {})
        users    = self._users.get(sid, {})
        messages = self._messages.get(sid, {})
        my_id    = self._user_ids.get(sid)

        room = rooms.get(room_id)
        if not room:
            print(f"[dispatcher] join_chat_view: sala #{room_id} no encontrada (sid={sid})")
            print(f"[dispatcher]   salas conocidas: {list(rooms.keys())}")
            return

        coord_id = room.get("coordinatorId")
        history  = [
            [self._username(sid, m["user_id"]), m["text"]]
            for m in messages.get(room_id, [])
        ]

        print(f"[dispatcher] join_chat_view sala #{room_id} '{room['name']}' "
              f"coord={my_id == coord_id} hist={len(history)}")

        self.sio.emit("chat_view_data", {
            "room_id":  room_id,
            "name":     room["name"],
            "is_coord": my_id == coord_id,
            "history":  history,
        }, to=sid)

    # ── coord panel ───────────────────────────────────────────────────

    def handle_get_coord_data(self, sid: str, room_id: int):
        rooms  = self._rooms.get(sid, {})
        users  = self._users.get(sid, {})
        room   = rooms.get(room_id)
        if not room:
            print(f"[dispatcher] get_coord_data: sala #{room_id} no encontrada")
            return

        coord_id   = room.get("coordinatorId")
        coord_name = users.get(coord_id, str(coord_id))
        members    = [users.get(uid, str(uid)) for uid in room.get("userIds", [])]

        all_users = [
            {"username": name, "nickname": name, "online": True}
            for uid, name in users.items()
        ]

        self.sio.emit("coord_data", {
            "room_id":     room_id,
            "coordinator": coord_name,
            "members":     members,
            "requests":    [],
            "all_users":   all_users,
        }, to=sid)

    # ── members panel ─────────────────────────────────────────────────

    def handle_get_members_data(self, sid: str, room_id: int):
        rooms = self._rooms.get(sid, {})
        users = self._users.get(sid, {})
        room  = rooms.get(room_id)
        if not room:
            print(f"[dispatcher] get_members_data: sala #{room_id} no encontrada")
            return

        coord_id    = room.get("coordinatorId")
        member_list = [
            {
                "username": users.get(uid, str(uid)),
                "nickname": users.get(uid, str(uid)),
                "online":   True,
                "is_coord": uid == coord_id,
            }
            for uid in room.get("userIds", [])
        ]

        self.sio.emit("members_data", {
            "room_id": room_id,
            "name":    room["name"],
            "members": member_list,
        }, to=sid)

    # ── Operaciones de sala ───────────────────────────────────────────

    def _on_create_room(self, sid, status, p):
        if p.get("success") == 1:
            cr      = p.get("chatRoom", p)
            room_id = cr.get("id")
            my_id   = self._user_ids.get(sid)

            # Actualiza estado local
            if room_id is not None:
                self._rooms.setdefault(sid, {})[room_id] = {
                    "id":            room_id,
                    "name":          cr.get("name", ""),
                    "coordinatorId": cr.get("coordinatorId", my_id),
                    "userIds":       list(cr.get("userIds", [my_id])),
                }
                self._messages.setdefault(sid, {})[room_id] = []

            print(f"[dispatcher] room_created #{room_id}: {cr.get('name')}")
            self.sio.emit("room_created",
                          {"room_id": room_id, "name": cr.get("name")}, to=sid)
        else:
            print(f"[dispatcher] room_created FAIL  payload={p}")
            self.sio.emit("room_error", {"message": "No se pudo crear la sala"}, to=sid)

    def _on_new_message(self, sid, status, p):
        if not p.get("success"):
            print(f"[dispatcher] new_message FAIL  payload={p}")
            return

        msg     = p.get("message", p)
        user_id = msg.get("userId")
        room_id = msg.get("chatRoomId")
        text    = msg.get("text", "")
        ts      = msg.get("id", 0)

        sender = self._username(sid, user_id)

        # Persiste en memoria
        self._messages.setdefault(sid, {}).setdefault(room_id, []).append({
            "user_id": user_id,
            "text":    text,
            "ts":      ts,
        })

        print(f"[dispatcher] new_message sala #{room_id} de {sender!r}: {text[:40]!r}")
        self.sio.emit("new_message", {
            "room_id": room_id,
            "sender":  sender,
            "text":    text,
            "ts":      ts,
        }, to=sid)

    def _on_leave_room(self, sid, status, p):
        room_id = p.get("chatRoomId")
        user_id = p.get("userId")
        my_id   = self._user_ids.get(sid)

        # Actualiza userIds en estado local
        rooms = self._rooms.get(sid, {})
        if room_id in rooms:
            uids = rooms[room_id].get("userIds", [])
            if user_id in uids:
                uids.remove(user_id)

        if user_id == my_id:
            print(f"[dispatcher] room_left #{room_id}")
            self.sio.emit("room_left", {"room_id": room_id}, to=sid)
        else:
            username = self._username(sid, user_id)
            print(f"[dispatcher] {username} salió de sala #{room_id}")
            self.sio.emit("user_left", {"room_id": room_id, "username": username}, to=sid)

    def _on_add_user(self, sid, status, p):
        if p.get("success") == 1:
            room_id = p.get("chatRoomId")
            user_id = p.get("userId")

            # Actualiza userIds en estado local
            rooms = self._rooms.get(sid, {})
            if room_id in rooms:
                uids = rooms[room_id].get("userIds", [])
                if user_id not in uids:
                    uids.append(user_id)

            username = self._username(sid, user_id)
            print(f"[dispatcher] user_joined sala #{room_id}: {username}")
            self.sio.emit("user_joined", {
                "room_id":  room_id,
                "username": username,
            }, to=sid)

    def _on_join_request_response(self, sid, status, p):
        success = p.get("success") == 1
        room_id = p.get("chatRoomId")
        print(f"[dispatcher] JOIN_REQUEST_RESPONSE sala #{room_id} success={success}")
        self.sio.emit("join_request_response", {
            "room_id": room_id,
            "success": success,
        }, to=sid)

    def _on_delete_room(self, sid, status, p):
        room_id = p.get("chatRoomId")
        if p.get("success") == 1:
            self._rooms.get(sid, {}).pop(room_id, None)
            self._messages.get(sid, {}).pop(room_id, None)
            print(f"[dispatcher] room_deleted #{room_id}")
            self.sio.emit("room_deleted", {"room_id": room_id}, to=sid)
        else:
            print(f"[dispatcher] delete_room FAIL  payload={p}")
            self.sio.emit("room_error",
                          {"message": "Solo puedes eliminar si eres el único miembro"}, to=sid)

    # ── Eventos push ─────────────────────────────────────────────────

    def _on_user_online(self, sid, status, p):
        username = p.get("username") or p.get("name", "")
        user_id  = p.get("userId") or p.get("id")

        if user_id and sid in self._users:
            self._users[sid][user_id] = username

        print(f"[dispatcher] USER_ONLINE: {username} (#{user_id})")
        self.sio.emit("user_online",
                      {"username": username, "nickname": username}, to=sid)

    def _on_user_offline(self, sid, status, p):
        username = p.get("username") or p.get("name", "")
        print(f"[dispatcher] USER_OFFLINE: {username}")
        self.sio.emit("user_offline",
                      {"username": username, "nickname": username}, to=sid)
