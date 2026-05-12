from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
from mock_data import MockServer

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config['SECRET_KEY'] = 'pimentel_secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

# Diccionario para guardar una instancia de MockServer por cada conexión web
client_sessions = {}


@app.route('/')
def index():
    return render_template('index.html')


@socketio.on('connect')
def handle_connect():
    client_sessions[request.sid] = MockServer(current_user="temp", current_nick="temp")


@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in client_sessions:
        del client_sessions[request.sid]


# --- AUTENTICACIÓN ---

@socketio.on('login')
def handle_login(data):
    username = data.get('username', '').strip()
    if not username:
        emit('login_error', {'message': 'Username cannot be empty.'})
        return
    # AQUÍ IRÍA: verificación real contra el backend C
    client_sessions[request.sid] = MockServer(current_user=username, current_nick=username)
    emit('login_success', {'username': username, 'nickname': username})
    send_lobby_update(request.sid)


@socketio.on('register')
def handle_register(data):
    # AQUÍ IRÍA: network_client.send("AUTH_REGISTER", username, password, nickname)
    emit('register_success', {'nickname': data.get('nickname', '')})


# --- E-LOBBY Y SALAS ---

def send_lobby_update(sid):
    mock = client_sessions.get(sid)
    if mock:
        rooms     = mock.get_rooms()
        users     = mock.get_online_users()
        all_users = mock.get_all_users()
        emit('lobby_update', {
            'rooms':     rooms,
            'users':     users,
            'all_users': all_users
        }, to=sid)


@socketio.on('request_lobby_data')
def handle_lobby_data():
    send_lobby_update(request.sid)


@socketio.on('create_room')
def handle_create_room(data):
    mock = client_sessions.get(request.sid)
    if mock:
        name = data.get('name', '').strip()
        if not name or len(name) < 3:
            emit('create_room_error', {'message': 'Room name must be at least 3 characters.'})
            return
        # AQUÍ IRÍA: network_client.send("COORD_CREATE_ROOM", name)
        room = mock.create_room(name)
        send_lobby_update(request.sid)
        emit('room_created', {'room_id': room['id'], 'name': room['name']})


@socketio.on('request_join')
def handle_request_join(data):
    mock = client_sessions.get(request.sid)
    if mock:
        room_id = data.get('room_id')
        # AQUÍ IRÍA: network_client.send("LOBBY_JOIN_REQUEST", room_id)
        success = mock.request_join(room_id)
        emit('join_request_result', {'success': success, 'room_id': room_id})


@socketio.on('leave_room')
def handle_leave_room(data):
    mock = client_sessions.get(request.sid)
    if mock:
        room_id = data.get('room_id')
        # AQUÍ IRÍA: network_client.send("LOBBY_LEAVE_ROOM", room_id)
        mock.kick_user(room_id, mock.current_user)
        mock.messages.setdefault(room_id, []).append(
            ("__SYSTEM__", f"{mock.current_nick} has left the room.")
        )
        send_lobby_update(request.sid)
        emit('left_room', {'room_id': room_id})


# --- CHAT ---

@socketio.on('join_chat_view')
def handle_join_chat_view(data):
    mock = client_sessions.get(request.sid)
    if mock:
        room_id  = data.get('room_id')
        room     = mock.get_room(room_id)
        history  = mock.get_messages(room_id)
        is_coord = mock.is_coordinator(room_id)
        if room:
            emit('chat_view_data', {
                'room_id':  room_id,
                'name':     room['name'],
                'history':  history,
                'is_coord': is_coord,
                'members':  room['members']
            })


@socketio.on('send_message')
def handle_message(data):
    mock = client_sessions.get(request.sid)
    if mock:
        room_id = data.get('room_id')
        text    = data.get('text', '').strip()
        if text:
            # AQUÍ IRÍA: network_client.send("CHAT_SEND_MSG", room_id, text)
            mock.send_message(room_id, text)
            emit('new_message', {
                'room_id': room_id,
                'sender':  mock.current_nick,
                'text':    text
            })


# --- PERSISTENCIA DE MENSAJES SIMULADOS ---
# Guardan los mensajes generados client-side en el historial del servidor
# para que persistan al navegar entre salas.
# En el sistema real estos mensajes vendrían del servidor directamente.

@socketio.on('sim_message')
def handle_sim_message(data):
    # Persiste un mensaje simulado de chat en el historial del servidor
    mock = client_sessions.get(request.sid)
    if mock:
        room_id = data.get('room_id')
        sender  = data.get('sender', '')
        text    = data.get('text', '')
        if room_id and sender and text:
            mock.messages.setdefault(room_id, []).append((sender, text))


@socketio.on('sim_system')
def handle_sim_system(data):
    # Persiste un mensaje de sistema simulado en el historial del servidor
    mock = client_sessions.get(request.sid)
    if mock:
        room_id = data.get('room_id')
        text    = data.get('text', '')
        if room_id and text:
            mock.messages.setdefault(room_id, []).append(("__SYSTEM__", text))


@socketio.on('sim_leave')
def handle_sim_leave(data):
    # Simula que un usuario abandona voluntariamente la sala
    # Lo quita de los members para que el coordinator panel lo refleje correctamente
    # AQUÍ IRÍA: el servidor recibiría este evento del cliente que sale
    mock = client_sessions.get(request.sid)
    if mock:
        room_id  = data.get('room_id')
        username = data.get('username')
        if room_id and username:
            mock.kick_user(room_id, username)


# --- COORDINADOR ---

@socketio.on('get_coord_data')
def handle_coord_data(data):
    mock = client_sessions.get(request.sid)
    if mock:
        room_id   = data.get('room_id')
        requests  = mock.get_join_requests(room_id)
        members   = mock.get_members(room_id)
        all_users = mock.get_all_users()
        room      = mock.get_room(room_id)
        emit('coord_data', {
            'room_id':     room_id,
            'coordinator': room['coordinator'] if room else '',
            'requests':    requests,
            'members':     members,
            'all_users':   all_users
        })


@socketio.on('coord_action')
def handle_coord_action(data):
    mock = client_sessions.get(request.sid)
    if not mock:
        return

    action      = data.get('action')
    room_id     = data.get('room_id')
    target_user = data.get('target_user', '')
    target_nick = data.get('target_nick', target_user)

    if action == 'accept':
        # AQUÍ IRÍA: network_client.send("COORD_ACCEPT_USER", room_id, target_user)
        mock.accept_request(room_id, target_user)
        mock.messages.setdefault(room_id, []).append(
            ("__SYSTEM__", f"{target_nick} was accepted into the room.")
        )
        emit('system_event', {'room_id': room_id, 'text': f"{target_nick} was accepted into the room."})

    elif action == 'reject':
        # AQUÍ IRÍA: network_client.send("COORD_REJECT_USER", room_id, target_user)
        mock.reject_request(room_id, target_user)
        emit('system_event', {'room_id': room_id, 'text': f"{target_nick}'s request was rejected."})

    elif action == 'kick':
        # AQUÍ IRÍA: network_client.send("COORD_KICK_USER", room_id, target_user)
        mock.kick_user(room_id, target_user)
        mock.messages.setdefault(room_id, []).append(
            ("__SYSTEM__", f"{target_nick} was removed from the room.")
        )
        emit('system_event', {'room_id': room_id, 'text': f"{target_nick} was removed from the room."})

    elif action == 'add':
        # Añadir usuario directamente sin solicitud previa
        # AQUÍ IRÍA: network_client.send("COORD_INVITE_USER", room_id, target_user)
        room = mock.get_room(room_id)
        if room and target_user not in room['members']:
            room['members'].append(target_user)
        mock.reject_request(room_id, target_user)
        mock.messages.setdefault(room_id, []).append(
            ("__SYSTEM__", f"{target_nick} was added to the room.")
        )
        emit('system_event', {'room_id': room_id, 'text': f"{target_nick} was added to the room."})

    elif action == 'delete':
        # AQUÍ IRÍA: network_client.send("COORD_DELETE_ROOM", room_id)
        success = mock.delete_room(room_id)
        emit('room_deleted_result', {'success': success})
        if success:
            send_lobby_update(request.sid)
            return

    # Refrescar panel de coordinador y lobby
    handle_coord_data({'room_id': room_id})
    send_lobby_update(request.sid)


# --- PERFIL ---

@socketio.on('update_profile')
def handle_profile_update(data):
    mock = client_sessions.get(request.sid)
    if mock:
        new_nick = data.get('nickname', '').strip()
        if new_nick:
            # AQUÍ IRÍA: network_client.send("UPDATE_PROFILE", new_nick)
            mock.current_nick = new_nick
            emit('profile_updated', {'nickname': mock.current_nick})


if __name__ == '__main__':
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True, port=5100)