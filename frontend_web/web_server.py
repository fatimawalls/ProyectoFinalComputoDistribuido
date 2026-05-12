from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
from mock_data import MockServer

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config['SECRET_KEY'] = 'pimentel_secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

# Diccionario para guardar una instancia de MockServer por cada conexión web (simulando los clientes aislados)
client_sessions = {}


@app.route('/')
def index():
    return render_template('index.html')


@socketio.on('connect')
def handle_connect():
    # Inicializa una sesión temporal
    client_sessions[request.sid] = MockServer(current_user="temp", current_nick="temp")


@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in client_sessions:
        del client_sessions[request.sid]


# --- AUTENTICACIÓN ---

@socketio.on('login')
def handle_login(data):
    username = data.get('username')
    # Simulamos login exitoso y seteamos el mock para este usuario
    client_sessions[request.sid] = MockServer(current_user=username, current_nick=username)
    emit('login_success', {'username': username, 'nickname': username})
    send_lobby_update(request.sid)


@socketio.on('register')
def handle_register(data):
    # En un entorno real aquí guardarías en la BD
    emit('register_success', {'nickname': data.get('nickname')})


# --- E-LOBBY Y SALAS ---

def send_lobby_update(sid):
    mock = client_sessions.get(sid)
    if mock:
        rooms = mock.get_rooms()
        users = mock.get_online_users()
        emit('lobby_update', {'rooms': rooms, 'users': users}, to=sid)


@socketio.on('request_lobby_data')
def handle_lobby_data():
    send_lobby_update(request.sid)


@socketio.on('create_room')
def handle_create_room(data):
    mock = client_sessions.get(request.sid)
    if mock:
        room = mock.create_room(data.get('name'))
        send_lobby_update(request.sid)
        emit('room_created', {'room_id': room['id'], 'name': room['name']})


@socketio.on('request_join')
def handle_request_join(data):
    mock = client_sessions.get(request.sid)
    if mock:
        success = mock.request_join(data.get('room_id'))
        emit('join_request_result', {'success': success, 'room_id': data.get('room_id')})


@socketio.on('leave_room')
def handle_leave_room(data):
    mock = client_sessions.get(request.sid)
    if mock:
        mock.kick_user(data.get('room_id'), mock.current_user)
        send_lobby_update(request.sid)


# --- CHAT ---

@socketio.on('join_chat_view')
def handle_join_chat_view(data):
    mock = client_sessions.get(request.sid)
    if mock:
        room_id = data.get('room_id')
        history = mock.get_messages(room_id)
        is_coord = mock.is_coordinator(room_id)
        room = mock.get_room(room_id)
        emit('chat_view_data', {
            'room_id': room_id, 'name': room['name'],
            'history': history, 'is_coord': is_coord
        })


@socketio.on('send_message')
def handle_message(data):
    mock = client_sessions.get(request.sid)
    if mock:
        room_id = data.get('room_id')
        text = data.get('text')
        mock.send_message(room_id, text)
        # En el Mock actual no hay broadcast real entre SIDs, así que nos lo re-enviamos para la UI
        emit('new_message', {'room_id': room_id, 'sender': mock.current_nick, 'text': text})


# --- COORDINADOR ---

@socketio.on('get_coord_data')
def handle_coord_data(data):
    mock = client_sessions.get(request.sid)
    if mock:
        room_id = data.get('room_id')
        requests = mock.get_join_requests(room_id)
        members = mock.get_members(room_id)
        all_users = mock.get_all_users()
        emit('coord_data', {'room_id': room_id, 'requests': requests, 'members': members, 'all_users': all_users})


@socketio.on('coord_action')
def handle_coord_action(data):
    mock = client_sessions.get(request.sid)
    if mock:
        action = data.get('action')
        room_id = data.get('room_id')
        target_user = data.get('target_user')

        if action == 'accept':
            mock.accept_request(room_id, target_user)
        elif action == 'reject':
            mock.reject_request(room_id, target_user)
        elif action == 'kick':
            mock.kick_user(room_id, target_user)
        elif action == 'delete':
            success = mock.delete_room(room_id)
            emit('room_deleted_result', {'success': success})
            if success: send_lobby_update(request.sid)
            return

        # Refrescar panel de coordinador
        handle_coord_data({'room_id': room_id})


# --- PERFIL ---

@socketio.on('update_profile')
def handle_profile_update(data):
    mock = client_sessions.get(request.sid)
    if mock:
        mock.current_nick = data.get('nickname')
        emit('profile_updated', {'nickname': mock.current_nick})


if __name__ == '__main__':
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True, port=5100)