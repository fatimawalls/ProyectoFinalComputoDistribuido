import eventlet
eventlet.monkey_patch()

import socket
import sys
import hashlib
import time
from flask import Flask, render_template, request
from flask_socketio import SocketIO

# ── Importar el módulo de protocolo ─────────────────────────────────────
from protocol import Protocol, ProtocolDispatcher, ProtocolError

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config['SECRET_KEY'] = 'pimentel_secret!'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

# ── Configuración por línea de comandos ─────────────────────────────────
#
# Uso:
#   python web_server.py <C_IP> <C_PORT> [WEB_PORT] [WEB_HOST]
#
# Ejemplos:
#   python web_server.py 10.7.9.160 5006
#   python web_server.py 10.7.9.160 5006 8080
#   python web_server.py 10.7.9.160 5006 8080 127.0.0.1
#
C_SERVER_IP   = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
C_SERVER_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
WEB_PORT      = int(sys.argv[3]) if len(sys.argv) > 3 else 5100
WEB_HOST      = sys.argv[4]      if len(sys.argv) > 4 else "0.0.0.0"

# Mapa sid → socket TCP al servidor C
client_sockets: dict[str, socket.socket] = {}
# Mapa sid → IP local usada para conectar al servidor C
client_local_ips: dict[str, str] = {}

# Dispatcher global: parsea tramas y emite eventos SocketIO
dispatcher = ProtocolDispatcher(socketio)


# ════════════════════════════════════════════════════════════════════════
# UTILIDADES TCP
# ════════════════════════════════════════════════════════════════════════

def connect_to_c_server(sid: str) -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((C_SERVER_IP, C_SERVER_PORT))
        client_sockets[sid] = sock
        client_local_ips[sid] = sock.getsockname()[0]
        socketio.start_background_task(listen_to_c_server, sid, sock)
        return True
    except Exception as e:
        print(f"[web_server] Error conectando al servidor C: {e}")
        return False


def send_to_c(sid: str, data: bytes) -> bool:
    """Envía bytes al servidor C para el cliente sid."""
    sock = client_sockets.get(sid)
    if not sock:
        socketio.emit("server_error",
                      {"message": "Sin conexión con el servidor central."}, to=sid)
        return False
    try:
        sock.sendall(data)
        return True
    except Exception as e:
        print(f"[web_server] Error enviando al servidor C (sid={sid}): {e}")
        return False


def listen_to_c_server(sid: str, sock: socket.socket):
    """
    Hilo por cliente: lee líneas JSON del servidor C y las despacha.
    """
    buf = ""
    print(f"[tcp] Hilo TCP iniciado para sid={sid}")
    while True:
        try:
            print(f"[tcp] Esperando datos del servidor C (sid={sid})...")
            chunk = sock.recv(4096)
            if not chunk:
                print(f"[tcp] Conexión cerrada por servidor C (sid={sid})")
                break
            text = chunk.decode("utf-8", errors="replace")
            print(f"[tcp] Recibidos {len(chunk)} bytes (sid={sid}): {text[:80]!r}")
            buf += text
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                if line.strip():
                    dispatcher.dispatch(sid, line)
        except Exception as e:
            print(f"[tcp] ERROR en recv (sid={sid}): {e}")
            break

    print(f"[tcp] Hilo TCP terminado para sid={sid}")
    client_sockets.pop(sid, None)
    socketio.emit("server_disconnected",
                  {"message": "Conexión con el servidor perdida."}, to=sid)


# ════════════════════════════════════════════════════════════════════════
# LISTENER UDP — recibe push del servidor C y reenvía a browsers
# ════════════════════════════════════════════════════════════════════════

UDP_LISTEN_PORT = 5001
_udp_seen: dict[str, float] = {}   # dedup: hash → timestamp


def _is_duplicate_udp(raw: str) -> bool:
    """Devuelve True si este mensaje ya se procesó hace menos de 5 s."""
    h = hashlib.md5(raw.encode()).hexdigest()
    now = time.time()
    for k in list(_udp_seen.keys()):
        if now - _udp_seen[k] > 5.0:
            del _udp_seen[k]
    if h in _udp_seen:
        return True
    _udp_seen[h] = now
    return False


def udp_listener():
    """
    Tarea de fondo: escucha en UDP_LISTEN_PORT y reenvía cada mensaje
    a TODOS los browsers conectados via Socket.IO.

    El servidor C envía un datagrama por cada usuario web registrado
    (todos comparten el mismo IP: el de web_server.py), por eso
    deduplicamos antes de hacer broadcast a los sids.
    """
    try:
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        udp_sock.bind(("", UDP_LISTEN_PORT))
        print(f"[udp] Escuchando notificaciones UDP en puerto {UDP_LISTEN_PORT}")
    except Exception as e:
        print(f"[udp] ERROR: no se pudo abrir UDP {UDP_LISTEN_PORT}: {e}")
        return

    while True:
        try:
            data, addr = udp_sock.recvfrom(65536)
            raw = data.decode("utf-8", errors="replace").strip()
            if not raw:
                continue
            print(f"[udp] <- {addr}  {raw[:120]!r}")

            if _is_duplicate_udp(raw):
                print(f"[udp] Duplicado ignorado")
                continue

            # Reenviar a cada browser conectado
            sids = list(client_sockets.keys())
            print(f"[udp] Reenviando a {len(sids)} cliente(s) web")
            for sid in sids:
                try:
                    dispatcher.dispatch(sid, raw)
                except Exception as ex:
                    print(f"[udp] Error despachando a sid={sid}: {ex}")
        except Exception as e:
            print(f"[udp] Error en recv: {e}")
            eventlet.sleep(1)


# ════════════════════════════════════════════════════════════════════════
# RUTAS FLASK
# ════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


# ════════════════════════════════════════════════════════════════════════
# EVENTOS SOCKET.IO  —  Navegador → web_server → servidor C
# ════════════════════════════════════════════════════════════════════════

@socketio.on("connect")
def handle_connect():
    print(f"[web_server] Cliente web conectado: {request.sid}")
    connect_to_c_server(request.sid)


@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    sock = client_sockets.pop(sid, None)
    client_local_ips.pop(sid, None)
    if sock:
        try:
            send_to_c(sid, Protocol.build_logout())
        except Exception:
            pass
        sock.close()
    dispatcher.remove_sid(sid)
    print(f"[web_server] Cliente web desconectado: {sid}")


# ── Autenticación ────────────────────────────────────────────────────────

@socketio.on("login")
def handle_login(data):
    sid      = request.sid
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    udp_ip   = client_local_ips.get(sid, "")
    print(f"[web_server] login sid={sid} user={username!r} udp={udp_ip}:{UDP_LISTEN_PORT}")
    send_to_c(sid, Protocol.build_login(username, password, UDP_LISTEN_PORT, udp_ip))


@socketio.on("register")
def handle_register(data):
    sid      = request.sid
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    udp_ip   = client_local_ips.get(sid, "")
    print(f"[web_server] register sid={sid} user={username!r} udp={udp_ip}:{UDP_LISTEN_PORT}")
    send_to_c(sid, Protocol.build_register(username, password, UDP_LISTEN_PORT, udp_ip))


# ── Navegación de sala ────────────────────────────────────────────────────

@socketio.on("join_chat_view")
def handle_join_chat_view(data):
    sid     = request.sid
    room_id = data.get("room_id")
    print(f"[web_server] join_chat_view sid={sid} room={room_id}")
    if room_id is not None:
        dispatcher.handle_join_chat_view(sid, int(room_id))


@socketio.on("get_coord_data")
def handle_get_coord_data(data):
    sid     = request.sid
    room_id = data.get("room_id")
    if room_id is not None:
        dispatcher.handle_get_coord_data(sid, int(room_id))


@socketio.on("get_members_data")
def handle_get_members_data(data):
    sid     = request.sid
    room_id = data.get("room_id")
    if room_id is not None:
        dispatcher.handle_get_members_data(sid, int(room_id))


# ── Salas ────────────────────────────────────────────────────────────────

@socketio.on("create_room")
def handle_create_room(data):
    sid  = request.sid
    name = data.get("name", "").strip()
    uid  = dispatcher.get_user_id(sid)
    print(f"[web_server] create_room sid={sid} name={name!r} uid={uid}")
    if name and uid:
        send_to_c(sid, Protocol.build_create_room(name, uid))


@socketio.on("request_join")
def handle_request_join(data):
    sid     = request.sid
    uid     = dispatcher.get_user_id(sid)
    room_id = data.get("room_id")
    print(f"[web_server] request_join sid={sid} room={room_id} uid={uid}")
    if room_id is not None and uid:
        send_to_c(sid, Protocol.build_request_join(int(room_id), uid))


@socketio.on("leave_room")
def handle_leave_room(data):
    sid     = request.sid
    uid     = dispatcher.get_user_id(sid)
    room_id = data.get("room_id")
    print(f"[web_server] leave_room sid={sid} room={room_id} uid={uid}")
    if room_id is not None and uid:
        send_to_c(sid, Protocol.build_leave_room(int(room_id), uid))


# ── Chat ─────────────────────────────────────────────────────────────────

@socketio.on("send_message")
def handle_message(data):
    sid     = request.sid
    uid     = dispatcher.get_user_id(sid)
    room_id = data.get("room_id")
    text    = data.get("text", "").strip()
    print(f"[web_server] send_message sid={sid} room={room_id} uid={uid} text={text[:30]!r}")
    if room_id is not None and text and uid:
        send_to_c(sid, Protocol.build_send_msg(int(room_id), text, uid))


# ── Coordinador ──────────────────────────────────────────────────────────

@socketio.on("coord_action")
def handle_coord_action(data):
    sid         = request.sid
    action      = data.get("action", "")
    room_id     = data.get("room_id")
    target_user = data.get("target_user", "")
    print(f"[web_server] coord_action sid={sid} action={action} room={room_id} target={target_user!r}")

    if room_id is None:
        return
    room_id = int(room_id)
    user_id = dispatcher.get_user_id_by_name(sid, target_user)

    if action in ("add", "accept") and user_id:
        send_to_c(sid, Protocol.build_add_user(room_id, user_id))
    elif action == "kick" and user_id:
        send_to_c(sid, Protocol.build_leave_room(room_id, user_id))
    elif not user_id:
        print(f"[web_server] coord_action: usuario {target_user!r} no encontrado")


@socketio.on("delete_room")
def handle_delete_room(data):
    sid     = request.sid
    room_id = data.get("room_id")
    print(f"[web_server] delete_room sid={sid} room={room_id}")
    if room_id is not None:
        send_to_c(sid, Protocol.build_delete_room(int(room_id)))


# ════════════════════════════════════════════════════════════════════════
# INICIO
# ════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"[web_server] Backend C    -> {C_SERVER_IP}:{C_SERVER_PORT}")
    print(f"[web_server] Web listening -> http://{WEB_HOST}:{WEB_PORT}")
    print(f"[web_server] UDP listener  -> :{UDP_LISTEN_PORT}")
    socketio.start_background_task(udp_listener)
    socketio.run(app, host=WEB_HOST, port=WEB_PORT,
                 debug=True, use_reloader=False, allow_unsafe_werkzeug=True)