import socket
import threading
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

# ── Importar el módulo de protocolo ─────────────────────────────────────
from protocol import Protocol, ProtocolDispatcher, ProtocolError

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config['SECRET_KEY'] = 'pimentel_secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

# ── Configuración del backend C ──────────────────────────────────────────
C_SERVER_IP   = "127.0.0.1"
C_SERVER_PORT = 5000

# Mapa sid → socket TCP al servidor C
client_sockets: dict[str, socket.socket] = {}

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
        threading.Thread(target=listen_to_c_server,
                         args=(sid, sock), daemon=True).start()
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
    Reemplaza la lógica manual del web_server original.
    """
    buf = ""
    while True:
        try:
            chunk = sock.recv(4096).decode("utf-8")
            if not chunk:
                break
            buf += chunk
            # Puede haber múltiples tramas en un solo recv
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                if line.strip():
                    dispatcher.dispatch(sid, line)
        except Exception as e:
            print(f"[web_server] listen error (sid={sid}): {e}")
            break

    client_sockets.pop(sid, None)
    socketio.emit("server_disconnected",
                  {"message": "Conexión con el servidor perdida."}, to=sid)


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
    if sock:
        try:
            send_to_c(sid, Protocol.build_logout())
        except Exception:
            pass
        sock.close()
    print(f"[web_server] Cliente web desconectado: {sid}")


# ── Autenticación ────────────────────────────────────────────────────────

@socketio.on("login")
def handle_login(data):
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    send_to_c(request.sid, Protocol.build_login(username, password))


# ── Lobby ────────────────────────────────────────────────────────────────

@socketio.on("request_users")
def handle_request_users():
    send_to_c(request.sid, Protocol.build_list_users())


@socketio.on("request_rooms")
def handle_request_rooms():
    send_to_c(request.sid, Protocol.build_list_rooms())


# ── Salas ────────────────────────────────────────────────────────────────

@socketio.on("create_room")
def handle_create_room(data):
    name = data.get("name", "").strip()
    if name:
        send_to_c(request.sid, Protocol.build_create_room(name))


@socketio.on("request_join")
def handle_request_join(data):
    room_id = data.get("room_id", "").strip()
    if room_id:
        send_to_c(request.sid, Protocol.build_join_room(room_id))


@socketio.on("leave_room")
def handle_leave_room(data):
    room_id = data.get("room_id", "").strip()
    if room_id:
        send_to_c(request.sid, Protocol.build_leave_room(room_id))


# ── Chat ─────────────────────────────────────────────────────────────────

@socketio.on("send_message")
def handle_message(data):
    room_id = data.get("room_id", "").strip()
    text    = data.get("text", "").strip()
    if room_id and text:
        send_to_c(request.sid, Protocol.build_send_msg(room_id, text))


@socketio.on("get_history")
def handle_get_history(data):
    room_id = data.get("room_id", "").strip()
    if room_id:
        send_to_c(request.sid, Protocol.build_get_history(room_id))


# ── Coordinador ──────────────────────────────────────────────────────────

@socketio.on("get_join_requests")
def handle_get_join_requests(data):
    room_id = data.get("room_id", "").strip()
    if room_id:
        send_to_c(request.sid, Protocol.build_list_requests(room_id))


@socketio.on("accept_user")
def handle_accept_user(data):
    room_id  = data.get("room_id", "").strip()
    username = data.get("username", "").strip()
    if room_id and username:
        send_to_c(request.sid, Protocol.build_accept_user(room_id, username))


@socketio.on("reject_user")
def handle_reject_user(data):
    room_id  = data.get("room_id", "").strip()
    username = data.get("username", "").strip()
    if room_id and username:
        send_to_c(request.sid, Protocol.build_reject_user(room_id, username))


@socketio.on("kick_user")
def handle_kick_user(data):
    room_id  = data.get("room_id", "").strip()
    username = data.get("username", "").strip()
    if room_id and username:
        send_to_c(request.sid, Protocol.build_kick_user(room_id, username))


@socketio.on("get_members")
def handle_get_members(data):
    room_id = data.get("room_id", "").strip()
    if room_id:
        send_to_c(request.sid, Protocol.build_list_members(room_id))


@socketio.on("delete_room")
def handle_delete_room(data):
    room_id = data.get("room_id", "").strip()
    if room_id:
        send_to_c(request.sid, Protocol.build_delete_room(room_id))


# ════════════════════════════════════════════════════════════════════════
# INICIO
# ════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5100,
                 debug=True, allow_unsafe_werkzeug=True)