"""
protocol.py — Protocolo JSON/TCP para el cliente Python (web_server.py)
=======================================================================
Espejo exacto del protocol.h en C.

Cada función build_* construye el dict Python listo para json.dumps().
Cada función parse_* toma el JSON recibido del servidor C y retorna
un dict limpio o lanza ProtocolError si la trama es inválida.

Uso en web_server.py:
    from protocol import Protocol, ProtocolError

    # Enviar al servidor C
    sock.send(Protocol.build_login("jperez_root", "s3cr3t"))

    # Recibir del servidor C
    raw = sock.recv(4096).decode()
    frame = Protocol.parse(raw)
    if frame["cmd"] == Protocol.RES_LOGIN:
        ...
"""

import json
import time

# ── Separador de trama ───────────────────────────────────────────────
FRAME_SEP = "\n"

# ══════════════════════════════════════════════════════════════════════
# Nombres de comandos  (idénticos a los #define de protocol.h)
# ══════════════════════════════════════════════════════════════════════

class Protocol:

    # ── Cliente → Servidor (REQ_) ────────────────────────────────────
    REQ_LOGIN                = "REQ_LOGIN"
    REQ_LOGOUT               = "REQ_LOGOUT"
    REQ_LOBBY_LIST_USERS     = "REQ_LOBBY_LIST_USERS"
    REQ_LOBBY_LIST_ROOMS     = "REQ_LOBBY_LIST_ROOMS"
    REQ_CREATE_ROOM          = "REQ_CREATE_ROOM"
    REQ_JOIN_ROOM            = "REQ_JOIN_ROOM"
    REQ_LEAVE_ROOM           = "REQ_LEAVE_ROOM"
    REQ_CHAT_SEND_MSG        = "REQ_CHAT_SEND_MSG"
    REQ_CHAT_GET_HISTORY     = "REQ_CHAT_GET_HISTORY"
    REQ_COORD_LIST_REQUESTS  = "REQ_COORD_LIST_REQUESTS"
    REQ_COORD_ACCEPT_USER    = "REQ_COORD_ACCEPT_USER"
    REQ_COORD_REJECT_USER    = "REQ_COORD_REJECT_USER"
    REQ_COORD_KICK_USER      = "REQ_COORD_KICK_USER"
    REQ_COORD_LIST_MEMBERS   = "REQ_COORD_LIST_MEMBERS"
    REQ_COORD_DELETE_ROOM    = "REQ_COORD_DELETE_ROOM"

    # ── Servidor → Cliente: respuestas (RES_) ────────────────────────
    RES_LOGIN               = "RES_LOGIN"
    RES_LOGOUT              = "RES_LOGOUT"
    RES_LOBBY_USERS         = "RES_LOBBY_USERS"
    RES_LOBBY_ROOMS         = "RES_LOBBY_ROOMS"
    RES_CREATE_ROOM         = "RES_CREATE_ROOM"
    RES_JOIN_ROOM           = "RES_JOIN_ROOM"
    RES_LEAVE_ROOM          = "RES_LEAVE_ROOM"
    RES_CHAT_HISTORY        = "RES_CHAT_HISTORY"
    RES_COORD_REQUESTS      = "RES_COORD_REQUESTS"
    RES_COORD_ACCEPT        = "RES_COORD_ACCEPT"
    RES_COORD_REJECT        = "RES_COORD_REJECT"
    RES_COORD_KICK          = "RES_COORD_KICK"
    RES_COORD_MEMBERS       = "RES_COORD_MEMBERS"
    RES_COORD_DELETE_ROOM   = "RES_COORD_DELETE_ROOM"

    # ── Servidor → Cliente: eventos espontáneos (EVT_) ───────────────
    EVT_NEW_MSG         = "EVT_NEW_MSG"
    EVT_USER_JOINED     = "EVT_USER_JOINED"
    EVT_USER_LEFT       = "EVT_USER_LEFT"
    EVT_JOIN_APPROVED   = "EVT_JOIN_APPROVED"
    EVT_JOIN_REJECTED   = "EVT_JOIN_REJECTED"
    EVT_JOIN_REQUEST    = "EVT_JOIN_REQUEST"
    EVT_ROOM_DELETED    = "EVT_ROOM_DELETED"
    EVT_USER_ONLINE     = "EVT_USER_ONLINE"
    EVT_USER_OFFLINE    = "EVT_USER_OFFLINE"

    # ════════════════════════════════════════════════════════════════
    # BUILDERS  —  construyen bytes listos para sock.send()
    # ════════════════════════════════════════════════════════════════

    @staticmethod
    def _frame(cmd: str, payload: dict, status: str = "") -> bytes:
        """Serializa una trama JSON terminada en \\n."""
        obj = {"cmd": cmd, "payload": payload}
        if status:
            obj["status"] = status
        return (json.dumps(obj, ensure_ascii=False) + FRAME_SEP).encode("utf-8")

    # ── Autenticación ────────────────────────────────────────────────

    @staticmethod
    def build_login(username: str, password: str) -> bytes:
        """REQ_LOGIN"""
        return Protocol._frame(Protocol.REQ_LOGIN,
                               {"username": username, "password": password})

    @staticmethod
    def build_logout() -> bytes:
        """REQ_LOGOUT"""
        return Protocol._frame(Protocol.REQ_LOGOUT, {})

    # ── Lobby ────────────────────────────────────────────────────────

    @staticmethod
    def build_list_users() -> bytes:
        """REQ_LOBBY_LIST_USERS — solicita lista de usuarios online."""
        return Protocol._frame(Protocol.REQ_LOBBY_LIST_USERS, {})

    @staticmethod
    def build_list_rooms() -> bytes:
        """REQ_LOBBY_LIST_ROOMS — solicita lista de salas."""
        return Protocol._frame(Protocol.REQ_LOBBY_LIST_ROOMS, {})

    # ── Salas ────────────────────────────────────────────────────────

    @staticmethod
    def build_create_room(name: str) -> bytes:
        """REQ_CREATE_ROOM"""
        return Protocol._frame(Protocol.REQ_CREATE_ROOM, {"name": name})

    @staticmethod
    def build_join_room(room_id: str) -> bytes:
        """REQ_JOIN_ROOM — envía solicitud al coordinador."""
        return Protocol._frame(Protocol.REQ_JOIN_ROOM, {"room_id": room_id})

    @staticmethod
    def build_leave_room(room_id: str) -> bytes:
        """REQ_LEAVE_ROOM"""
        return Protocol._frame(Protocol.REQ_LEAVE_ROOM, {"room_id": room_id})

    # ── Chat ─────────────────────────────────────────────────────────

    @staticmethod
    def build_send_msg(room_id: str, text: str) -> bytes:
        """REQ_CHAT_SEND_MSG — texto en claro; el servidor lo cifra antes de guardar."""
        return Protocol._frame(Protocol.REQ_CHAT_SEND_MSG,
                               {"room_id": room_id, "text": text})

    @staticmethod
    def build_get_history(room_id: str) -> bytes:
        """REQ_CHAT_GET_HISTORY"""
        return Protocol._frame(Protocol.REQ_CHAT_GET_HISTORY,
                               {"room_id": room_id})

    # ── Coordinador ──────────────────────────────────────────────────

    @staticmethod
    def build_list_requests(room_id: str) -> bytes:
        """REQ_COORD_LIST_REQUESTS"""
        return Protocol._frame(Protocol.REQ_COORD_LIST_REQUESTS,
                               {"room_id": room_id})

    @staticmethod
    def build_accept_user(room_id: str, username: str) -> bytes:
        """REQ_COORD_ACCEPT_USER"""
        return Protocol._frame(Protocol.REQ_COORD_ACCEPT_USER,
                               {"room_id": room_id, "username": username})

    @staticmethod
    def build_reject_user(room_id: str, username: str) -> bytes:
        """REQ_COORD_REJECT_USER"""
        return Protocol._frame(Protocol.REQ_COORD_REJECT_USER,
                               {"room_id": room_id, "username": username})

    @staticmethod
    def build_kick_user(room_id: str, username: str) -> bytes:
        """REQ_COORD_KICK_USER"""
        return Protocol._frame(Protocol.REQ_COORD_KICK_USER,
                               {"room_id": room_id, "username": username})

    @staticmethod
    def build_list_members(room_id: str) -> bytes:
        """REQ_COORD_LIST_MEMBERS"""
        return Protocol._frame(Protocol.REQ_COORD_LIST_MEMBERS,
                               {"room_id": room_id})

    @staticmethod
    def build_delete_room(room_id: str) -> bytes:
        """REQ_COORD_DELETE_ROOM — solo si eres el único miembro."""
        return Protocol._frame(Protocol.REQ_COORD_DELETE_ROOM,
                               {"room_id": room_id})

    # ════════════════════════════════════════════════════════════════
    # PARSER  —  convierte JSON crudo en dict Python
    # ════════════════════════════════════════════════════════════════

    @staticmethod
    def parse(raw: str) -> dict:
        """
        Parsea una trama recibida del servidor C.

        Retorna:
            {
              "cmd":     str,
              "status":  str,   # "ok" | "error" | "" si no aplica
              "payload": dict,
            }

        Lanza ProtocolError si el JSON es inválido o falta "cmd".
        """
        raw = raw.strip()
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProtocolError(f"JSON inválido: {e}  raw={raw!r}")

        if "cmd" not in obj:
            raise ProtocolError(f"Trama sin 'cmd': {raw!r}")

        return {
            "cmd":     obj.get("cmd", ""),
            "status":  obj.get("status", ""),
            "payload": obj.get("payload", {}),
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
    Reemplaza la función listen_to_c_server() de web_server.py.
    Parsea cada trama recibida y emite el evento SocketIO correcto.

    Uso:
        dispatcher = ProtocolDispatcher(socketio)
        # Dentro del hilo de escucha:
        dispatcher.dispatch(sid, raw_line)
    """

    def __init__(self, socketio_instance):
        self.sio = socketio_instance

        # Mapeo: cmd → (evento_socketio, transformador_payload)
        self._handlers = {
            Protocol.RES_LOGIN:             self._on_login,
            Protocol.RES_LOBBY_USERS:       self._on_lobby_users,
            Protocol.RES_LOBBY_ROOMS:       self._on_lobby_rooms,
            Protocol.RES_CREATE_ROOM:       self._on_create_room,
            Protocol.RES_JOIN_ROOM:         self._on_join_room,
            Protocol.RES_LEAVE_ROOM:        self._on_leave_room,
            Protocol.RES_CHAT_HISTORY:      self._on_chat_history,
            Protocol.RES_COORD_REQUESTS:    self._on_coord_requests,
            Protocol.RES_COORD_ACCEPT:      self._on_coord_accept,
            Protocol.RES_COORD_REJECT:      self._on_coord_reject,
            Protocol.RES_COORD_KICK:        self._on_coord_kick,
            Protocol.RES_COORD_MEMBERS:     self._on_coord_members,
            Protocol.RES_COORD_DELETE_ROOM: self._on_delete_room,
            # Eventos espontáneos
            Protocol.EVT_NEW_MSG:           self._on_evt_new_msg,
            Protocol.EVT_USER_JOINED:       self._on_evt_user_joined,
            Protocol.EVT_USER_LEFT:         self._on_evt_user_left,
            Protocol.EVT_JOIN_APPROVED:     self._on_evt_join_approved,
            Protocol.EVT_JOIN_REJECTED:     self._on_evt_join_rejected,
            Protocol.EVT_JOIN_REQUEST:      self._on_evt_join_request,
            Protocol.EVT_ROOM_DELETED:      self._on_evt_room_deleted,
            Protocol.EVT_USER_ONLINE:       self._on_evt_user_online,
            Protocol.EVT_USER_OFFLINE:      self._on_evt_user_offline,
        }

    def dispatch(self, sid: str, raw: str):
        """Parsea raw y emite el evento SocketIO correspondiente al sid."""
        try:
            frame = Protocol.parse(raw)
        except ProtocolError as e:
            print(f"[dispatcher] {e}")
            return

        handler = self._handlers.get(frame["cmd"])
        if handler:
            handler(sid, frame["status"], frame["payload"])
        else:
            print(f"[dispatcher] Comando desconocido: {frame['cmd']}")

    # ── Handlers de respuestas ────────────────────────────────────────

    def _on_login(self, sid, status, p):
        if status == "ok":
            self.sio.emit("login_success",
                          {"username": p.get("username"),
                           "nickname": p.get("nickname")}, to=sid)
        else:
            self.sio.emit("login_error",
                          {"message": p.get("message", "Error desconocido")}, to=sid)

    def _on_lobby_users(self, sid, status, p):
        self.sio.emit("lobby_users", {"users": p.get("users", [])}, to=sid)

    def _on_lobby_rooms(self, sid, status, p):
        self.sio.emit("lobby_rooms", {"rooms": p.get("rooms", [])}, to=sid)

    def _on_create_room(self, sid, status, p):
        if status == "ok":
            self.sio.emit("room_created", p, to=sid)
        else:
            self.sio.emit("room_error",
                          {"message": p.get("message")}, to=sid)

    def _on_join_room(self, sid, status, p):
        # Solo acuse de recibo; la aprobación real llega como EVT_JOIN_APPROVED
        self.sio.emit("join_requested",
                      {"room_id": p.get("room_id"),
                       "message": p.get("message"),
                       "status":  status}, to=sid)

    def _on_leave_room(self, sid, status, p):
        self.sio.emit("room_left", {"room_id": p.get("room_id")}, to=sid)

    def _on_chat_history(self, sid, status, p):
        self.sio.emit("chat_history",
                      {"room_id":  p.get("room_id"),
                       "messages": p.get("messages", [])}, to=sid)

    def _on_coord_requests(self, sid, status, p):
        self.sio.emit("coord_requests",
                      {"room_id":  p.get("room_id"),
                       "requests": p.get("requests", [])}, to=sid)

    def _on_coord_accept(self, sid, status, p):
        self.sio.emit("coord_accept_ok",
                      {"room_id": p.get("room_id"),
                       "username": p.get("username")}, to=sid)

    def _on_coord_reject(self, sid, status, p):
        self.sio.emit("coord_reject_ok",
                      {"room_id": p.get("room_id"),
                       "username": p.get("username")}, to=sid)

    def _on_coord_kick(self, sid, status, p):
        self.sio.emit("coord_kick_ok",
                      {"room_id": p.get("room_id"),
                       "username": p.get("username")}, to=sid)

    def _on_coord_members(self, sid, status, p):
        self.sio.emit("coord_members",
                      {"room_id": p.get("room_id"),
                       "members": p.get("members", [])}, to=sid)

    def _on_delete_room(self, sid, status, p):
        if status == "ok":
            self.sio.emit("room_deleted", {"room_id": p.get("room_id")}, to=sid)
        else:
            self.sio.emit("room_error",
                          {"message": p.get("message")}, to=sid)

    # ── Handlers de eventos espontáneos ──────────────────────────────

    def _on_evt_new_msg(self, sid, status, p):
        self.sio.emit("new_message",
                      {"room_id": p.get("room_id"),
                       "sender":  p.get("sender"),
                       "text":    p.get("text"),
                       "ts":      p.get("ts")}, to=sid)

    def _on_evt_user_joined(self, sid, status, p):
        self.sio.emit("user_joined",
                      {"room_id":  p.get("room_id"),
                       "username": p.get("username"),
                       "nickname": p.get("nickname")}, to=sid)

    def _on_evt_user_left(self, sid, status, p):
        self.sio.emit("user_left",
                      {"room_id":  p.get("room_id"),
                       "username": p.get("username"),
                       "reason":   p.get("reason")}, to=sid)

    def _on_evt_join_approved(self, sid, status, p):
        self.sio.emit("join_approved",
                      {"room_id":   p.get("room_id"),
                       "room_name": p.get("room_name")}, to=sid)

    def _on_evt_join_rejected(self, sid, status, p):
        self.sio.emit("join_rejected",
                      {"room_id":   p.get("room_id"),
                       "room_name": p.get("room_name")}, to=sid)

    def _on_evt_join_request(self, sid, status, p):
        self.sio.emit("join_request_received",
                      {"room_id":  p.get("room_id"),
                       "username": p.get("username"),
                       "nickname": p.get("nickname")}, to=sid)

    def _on_evt_room_deleted(self, sid, status, p):
        self.sio.emit("room_deleted_broadcast",
                      {"room_id":   p.get("room_id"),
                       "room_name": p.get("room_name")}, to=sid)

    def _on_evt_user_online(self, sid, status, p):
        self.sio.emit("user_online",
                      {"username": p.get("username"),
                       "nickname": p.get("nickname")}, to=sid)

    def _on_evt_user_offline(self, sid, status, p):
        self.sio.emit("user_offline",
                      {"username": p.get("username"),
                       "nickname": p.get("nickname")}, to=sid)
