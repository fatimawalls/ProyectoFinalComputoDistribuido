"""
mock_c_server.py — Simula el servidor C para probar el protocolo
================================================================
Levanta un servidor TCP en 127.0.0.1:5000 que responde con
los mismos JSON que mandaría el servidor real en C.

Uso:
    python mock_c_server.py          # en una terminal
    python web_server.py             # en otra terminal
    Abre http://localhost:5100       # en el navegador
"""

import socket
import threading
import json
import time
import hashlib

HOST = "127.0.0.1"
PORT = 5000

# ── Datos de prueba (espejo de mock_data.py) ─────────────────────────
USERS = {
    "jperez_root": {"password": "1234", "nickname": "jperez.sys",  "online": False},
    "maria_p":     {"password": "1234", "nickname": "Maria_P",     "online": False},
    "admin_root":  {"password": "1234", "nickname": "Admin_Root",  "online": False},
}

ROOMS = {
    "general": {
        "name": "general", "coordinator": "admin_root",
        "members": ["admin_root", "maria_p"], "notifications": 0,
    },
    "root-access": {
        "name": "root-access", "coordinator": "jperez_root",
        "members": ["jperez_root", "maria_p"], "notifications": 1,
    },
}

MESSAGES = {
    "general":     [{"sender": "Admin_Root", "text": "Welcome!", "ts": 1715000000}],
    "root-access": [{"sender": "jperez.sys", "text": "Server is up.", "ts": 1715000001}],
}

JOIN_REQUESTS = {
    "root-access": [{"username": "admin_root", "nickname": "Admin_Root"}],
}

# Mapa username → conn (para broadcasts)
online_clients: dict[str, socket.socket] = {}
lock = threading.Lock()


# ── Utilidades ───────────────────────────────────────────────────────

def send_frame(conn: socket.socket, cmd: str, payload: dict, status: str = ""):
    obj = {"cmd": cmd, "payload": payload}
    if status:
        obj["status"] = status
    line = json.dumps(obj) + "\n"
    try:
        conn.sendall(line.encode("utf-8"))
        print(f"  → SEND  {cmd}  {payload}")
    except Exception as e:
        print(f"  [send_frame] error: {e}")


def broadcast_to_room(room_id: str, cmd: str, payload: dict, exclude: str = ""):
    room = ROOMS.get(room_id)
    if not room:
        return
    with lock:
        for username in room["members"]:
            if username == exclude:
                continue
            conn = online_clients.get(username)
            if conn:
                send_frame(conn, cmd, payload)


# ── Handler de cada cliente ──────────────────────────────────────────

def handle_client(conn: socket.socket, addr):
    print(f"\n[mock] Cliente conectado: {addr}")
    current_user = None
    buf = ""

    try:
        while True:
            chunk = conn.recv(4096).decode("utf-8")
            if not chunk:
                break
            buf += chunk

            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line:
                    continue

                try:
                    frame = json.loads(line)
                except json.JSONDecodeError:
                    print(f"  [mock] JSON inválido: {line!r}")
                    continue

                cmd     = frame.get("cmd", "")
                payload = frame.get("payload", {})
                print(f"  ← RECV  {cmd}  {payload}")

                # ── REQ_LOGIN ────────────────────────────────────────
                if cmd == "REQ_LOGIN":
                    username = payload.get("username", "")
                    password = payload.get("password", "")
                    user = USERS.get(username)
                    if user and user["password"] == password:
                        current_user = username
                        with lock:
                            online_clients[username] = conn
                            USERS[username]["online"] = True
                        send_frame(conn, "RES_LOGIN", {
                            "username": username,
                            "nickname": user["nickname"],
                        }, status="ok")
                        # Notificar a otros que está online
                        for uname, c in online_clients.items():
                            if uname != username:
                                send_frame(c, "EVT_USER_ONLINE", {
                                    "username": username,
                                    "nickname": user["nickname"],
                                })
                    else:
                        send_frame(conn, "RES_LOGIN",
                                   {"message": "Credenciales inválidas"},
                                   status="error")

                # ── REQ_LOGOUT ───────────────────────────────────────
                elif cmd == "REQ_LOGOUT":
                    send_frame(conn, "RES_LOGOUT", {}, status="ok")
                    break

                # ── REQ_LOBBY_LIST_USERS ─────────────────────────────
                elif cmd == "REQ_LOBBY_LIST_USERS":
                    users_list = [
                        {"username": u, "nickname": d["nickname"],
                         "online": d["online"]}
                        for u, d in USERS.items()
                        if u != current_user
                    ]
                    send_frame(conn, "RES_LOBBY_USERS",
                               {"users": users_list}, status="ok")

                # ── REQ_LOBBY_LIST_ROOMS ─────────────────────────────
                elif cmd == "REQ_LOBBY_LIST_ROOMS":
                    rooms_list = [
                        {"id": rid, "name": r["name"],
                         "coordinator": r["coordinator"],
                         "member_count": len(r["members"]),
                         "notifications": r["notifications"]}
                        for rid, r in ROOMS.items()
                    ]
                    send_frame(conn, "RES_LOBBY_ROOMS",
                               {"rooms": rooms_list}, status="ok")

                # ── REQ_CREATE_ROOM ──────────────────────────────────
                elif cmd == "REQ_CREATE_ROOM":
                    name    = payload.get("name", "")
                    room_id = name.lower().replace(" ", "-")
                    if room_id in ROOMS:
                        send_frame(conn, "RES_CREATE_ROOM",
                                   {"message": "Nombre ya en uso"}, status="error")
                    else:
                        ROOMS[room_id] = {
                            "name": name, "coordinator": current_user,
                            "members": [current_user], "notifications": 0,
                        }
                        MESSAGES[room_id] = []
                        JOIN_REQUESTS[room_id] = []
                        send_frame(conn, "RES_CREATE_ROOM", {
                            "id": room_id, "name": name,
                            "coordinator": current_user,
                        }, status="ok")

                # ── REQ_JOIN_ROOM ────────────────────────────────────
                elif cmd == "REQ_JOIN_ROOM":
                    room_id = payload.get("room_id", "")
                    room = ROOMS.get(room_id)
                    if not room:
                        send_frame(conn, "RES_JOIN_ROOM",
                                   {"message": "Sala no encontrada"}, status="error")
                    elif current_user in room["members"]:
                        send_frame(conn, "RES_JOIN_ROOM",
                                   {"message": "Ya eres miembro"}, status="error")
                    else:
                        # Guardar solicitud
                        JOIN_REQUESTS.setdefault(room_id, []).append({
                            "username": current_user,
                            "nickname": USERS[current_user]["nickname"],
                        })
                        send_frame(conn, "RES_JOIN_ROOM", {
                            "room_id": room_id,
                            "message": "Solicitud enviada al coordinador",
                        }, status="ok")
                        # Notificar al coordinador
                        coord_conn = online_clients.get(room["coordinator"])
                        if coord_conn:
                            send_frame(coord_conn, "EVT_JOIN_REQUEST", {
                                "room_id":  room_id,
                                "username": current_user,
                                "nickname": USERS[current_user]["nickname"],
                            })

                # ── REQ_LEAVE_ROOM ───────────────────────────────────
                elif cmd == "REQ_LEAVE_ROOM":
                    room_id = payload.get("room_id", "")
                    room = ROOMS.get(room_id)
                    if room and current_user in room["members"]:
                        room["members"].remove(current_user)
                    send_frame(conn, "RES_LEAVE_ROOM",
                               {"room_id": room_id}, status="ok")
                    broadcast_to_room(room_id, "EVT_USER_LEFT", {
                        "room_id":  room_id,
                        "username": current_user,
                        "reason":   "left",
                    })

                # ── REQ_CHAT_GET_HISTORY ─────────────────────────────
                elif cmd == "REQ_CHAT_GET_HISTORY":
                    room_id = payload.get("room_id", "")
                    msgs = MESSAGES.get(room_id, [])
                    send_frame(conn, "RES_CHAT_HISTORY", {
                        "room_id":  room_id,
                        "messages": msgs,
                    }, status="ok")

                # ── REQ_CHAT_SEND_MSG ────────────────────────────────
                elif cmd == "REQ_CHAT_SEND_MSG":
                    room_id = payload.get("room_id", "")
                    text    = payload.get("text", "")
                    ts      = int(time.time())
                    nickname = USERS[current_user]["nickname"]
                    msg = {"sender": nickname, "text": text, "ts": ts}
                    MESSAGES.setdefault(room_id, []).append(msg)
                    # Broadcast a todos en la sala (incluido el remitente)
                    broadcast_to_room(room_id, "EVT_NEW_MSG", {
                        "room_id": room_id,
                        "sender":  nickname,
                        "text":    text,
                        "ts":      ts,
                    })

                # ── REQ_COORD_LIST_REQUESTS ──────────────────────────
                elif cmd == "REQ_COORD_LIST_REQUESTS":
                    room_id = payload.get("room_id", "")
                    reqs = JOIN_REQUESTS.get(room_id, [])
                    send_frame(conn, "RES_COORD_REQUESTS", {
                        "room_id":  room_id,
                        "requests": reqs,
                    }, status="ok")

                # ── REQ_COORD_ACCEPT_USER ────────────────────────────
                elif cmd == "REQ_COORD_ACCEPT_USER":
                    room_id  = payload.get("room_id", "")
                    username = payload.get("username", "")
                    room = ROOMS.get(room_id)
                    if room and username not in room["members"]:
                        room["members"].append(username)
                    JOIN_REQUESTS[room_id] = [
                        r for r in JOIN_REQUESTS.get(room_id, [])
                        if r["username"] != username
                    ]
                    send_frame(conn, "RES_COORD_ACCEPT",
                               {"room_id": room_id, "username": username},
                               status="ok")
                    # Notificar al nuevo miembro
                    new_conn = online_clients.get(username)
                    if new_conn:
                        send_frame(new_conn, "EVT_JOIN_APPROVED", {
                            "room_id":   room_id,
                            "room_name": ROOMS[room_id]["name"],
                        })
                    # Broadcast a sala
                    broadcast_to_room(room_id, "EVT_USER_JOINED", {
                        "room_id":  room_id,
                        "username": username,
                        "nickname": USERS.get(username, {}).get("nickname", username),
                    }, exclude=username)

                # ── REQ_COORD_REJECT_USER ────────────────────────────
                elif cmd == "REQ_COORD_REJECT_USER":
                    room_id  = payload.get("room_id", "")
                    username = payload.get("username", "")
                    JOIN_REQUESTS[room_id] = [
                        r for r in JOIN_REQUESTS.get(room_id, [])
                        if r["username"] != username
                    ]
                    send_frame(conn, "RES_COORD_REJECT",
                               {"room_id": room_id, "username": username},
                               status="ok")
                    rejected_conn = online_clients.get(username)
                    if rejected_conn:
                        send_frame(rejected_conn, "EVT_JOIN_REJECTED", {
                            "room_id":   room_id,
                            "room_name": ROOMS[room_id]["name"],
                        })

                # ── REQ_COORD_KICK_USER ──────────────────────────────
                elif cmd == "REQ_COORD_KICK_USER":
                    room_id  = payload.get("room_id", "")
                    username = payload.get("username", "")
                    room = ROOMS.get(room_id)
                    if room and username in room["members"]:
                        room["members"].remove(username)
                    send_frame(conn, "RES_COORD_KICK",
                               {"room_id": room_id, "username": username},
                               status="ok")
                    kicked_conn = online_clients.get(username)
                    if kicked_conn:
                        send_frame(kicked_conn, "EVT_USER_LEFT", {
                            "room_id":  room_id,
                            "username": username,
                            "reason":   "kicked",
                        })

                # ── REQ_COORD_LIST_MEMBERS ───────────────────────────
                elif cmd == "REQ_COORD_LIST_MEMBERS":
                    room_id = payload.get("room_id", "")
                    room = ROOMS.get(room_id, {})
                    members = [
                        {"username": u,
                         "nickname": USERS.get(u, {}).get("nickname", u),
                         "online":   USERS.get(u, {}).get("online", False)}
                        for u in room.get("members", [])
                    ]
                    send_frame(conn, "RES_COORD_MEMBERS",
                               {"room_id": room_id, "members": members},
                               status="ok")

                # ── REQ_COORD_DELETE_ROOM ────────────────────────────
                elif cmd == "REQ_COORD_DELETE_ROOM":
                    room_id = payload.get("room_id", "")
                    room = ROOMS.get(room_id)
                    if not room:
                        send_frame(conn, "RES_COORD_DELETE_ROOM",
                                   {"message": "Sala no existe"}, status="error")
                    elif len(room["members"]) > 1:
                        send_frame(conn, "RES_COORD_DELETE_ROOM",
                                   {"message": "Sala tiene más miembros"},
                                   status="error")
                    else:
                        name = room["name"]
                        del ROOMS[room_id]
                        send_frame(conn, "RES_COORD_DELETE_ROOM",
                                   {"room_id": room_id}, status="ok")
                        broadcast_to_room(room_id, "EVT_ROOM_DELETED", {
                            "room_id": room_id, "room_name": name,
                        })

                else:
                    print(f"  [mock] Comando no manejado: {cmd}")

    except Exception as e:
        print(f"[mock] Error con cliente {addr}: {e}")
    finally:
        if current_user:
            with lock:
                online_clients.pop(current_user, None)
                if current_user in USERS:
                    USERS[current_user]["online"] = False
            # Notificar offline
            nick = USERS.get(current_user, {}).get("nickname", current_user)
            for c in online_clients.values():
                send_frame(c, "EVT_USER_OFFLINE",
                           {"username": current_user, "nickname": nick})
        conn.close()
        print(f"[mock] Cliente desconectado: {addr}")


# ── Servidor principal ───────────────────────────────────────────────

def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(10)
    print(f"[mock] Servidor C simulado escuchando en {HOST}:{PORT}")
    print(f"[mock] Usuarios de prueba (password=1234): {list(USERS.keys())}\n")

    while True:
        conn, addr = srv.accept()
        threading.Thread(target=handle_client,
                         args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    main()
