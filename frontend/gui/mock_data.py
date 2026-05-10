# mock_data.py - Simulación del backend para pruebas sin servidor C
# Cuando el backend esté listo, este módulo se reemplaza por las llamadas reales a NetworkClient

# --- DATOS SIMULADOS ---

MOCK_USERS = [
    {"username": "jperez_root",  "nickname": "jperez.sys",   "online": True},
    {"username": "maria_p",      "nickname": "Maria_P",       "online": True},
    {"username": "admin_root",   "nickname": "Admin_Root",    "online": True},
    {"username": "juan_dev",     "nickname": "Juan_Dev",      "online": False},
    {"username": "ana_ops",      "nickname": "Ana_Ops",       "online": True},
]

MOCK_ROOMS = [
    {"id": "general",    "name": "general",    "coordinator": "admin_root", "members": ["admin_root", "maria_p", "juan_dev"], "notifications": 0},
    {"id": "root-access","name": "root-access","coordinator": "jperez_root","members": ["jperez_root", "ana_ops"],             "notifications": 1},
    {"id": "dev-ops",    "name": "dev-ops",    "coordinator": "maria_p",   "members": ["maria_p", "juan_dev", "ana_ops"],     "notifications": 3},
]

MOCK_MESSAGES = {
    "general":     [("Admin_Root", "Welcome to the general channel."), ("Maria_P", "Thanks!")],
    "root-access": [("Ana_Ops", "Server is up."), ("jperez.sys", "Copy that.")],
    "dev-ops":     [("Maria_P", "Deploy finished."), ("Juan_Dev", "Any errors?"), ("Ana_Ops", "All clear.")],
}

MOCK_JOIN_REQUESTS = {
    "root-access": [
        {"username": "juan_dev", "nickname": "Juan_Dev"},
    ],
    "dev-ops": [
        {"username": "admin_root", "nickname": "Admin_Root"},
        {"username": "new_user",   "nickname": "New_User"},
    ],
}


# --- CLASE MOCK SERVER ---
# Simula las respuestas del servidor C para pruebas sin backend

class MockServer:
    def __init__(self, current_user="jperez_root", current_nick="jperez.sys"):
        self.current_user = current_user
        self.current_nick = current_nick

        # Copias locales para poder modificar en runtime
        self.users   = list(MOCK_USERS)
        self.rooms   = list(MOCK_ROOMS)
        self.messages   = {k: list(v) for k, v in MOCK_MESSAGES.items()}
        self.requests   = {k: list(v) for k, v in MOCK_JOIN_REQUESTS.items()}

    # --- USUARIOS ---

    def get_online_users(self):
        # AQUÍ IRÍA: network_client.request("LOBBY_LIST_USERS")
        return [u for u in self.users if u["online"] and u["username"] != self.current_user]

    # --- CHATROOMS ---

    def get_rooms(self):
        # AQUÍ IRÍA: network_client.request("LOBBY_LIST_ROOMS")
        return self.rooms

    def get_my_rooms(self):
        return [r for r in self.rooms if self.current_user in r["members"]]

    def is_coordinator(self, room_id):
        room = self.get_room(room_id)
        return room and room["coordinator"] == self.current_user

    def get_room(self, room_id):
        for r in self.rooms:
            if r["id"] == room_id:
                return r
        return None

    def create_room(self, room_name):
        # AQUÍ IRÍA: network_client.send("COORD_CREATE_ROOM", room_name)
        room_id = room_name.lower().replace(" ", "-")
        new_room = {
            "id":          room_id,
            "name":        room_name,
            "coordinator": self.current_user,
            "members":     [self.current_user],
            "notifications": 0,
        }
        self.rooms.append(new_room)
        self.messages[room_id]  = []
        self.requests[room_id]  = []
        return new_room

    def request_join(self, room_id):
        # AQUÍ IRÍA: network_client.send("LOBBY_JOIN_REQUEST", room_id)
        room = self.get_room(room_id)
        if not room:
            return False
        if self.current_user in room["members"]:
            return False
        return True

    # --- MENSAJES ---

    def get_messages(self, room_id):
        # AQUÍ IRÍA: network_client.request("CHAT_GET_HISTORY", room_id)
        return self.messages.get(room_id, [])

    def send_message(self, room_id, text):
        # AQUÍ IRÍA: network_client.send("CHAT_SEND_MSG", room_id, text)
        if room_id not in self.messages:
            self.messages[room_id] = []
        self.messages[room_id].append((self.current_nick, text))

    # --- COORDINADOR ---

    def get_join_requests(self, room_id):
        # AQUÍ IRÍA: network_client.request("COORD_LIST_REQUESTS", room_id)
        return self.requests.get(room_id, [])

    def accept_request(self, room_id, username):
        # AQUÍ IRÍA: network_client.send("COORD_ACCEPT_USER", room_id, username)
        room = self.get_room(room_id)
        if room and username not in room["members"]:
            room["members"].append(username)
        self.requests[room_id] = [r for r in self.requests.get(room_id, []) if r["username"] != username]

    def reject_request(self, room_id, username):
        # AQUÍ IRÍA: network_client.send("COORD_REJECT_USER", room_id, username)
        self.requests[room_id] = [r for r in self.requests.get(room_id, []) if r["username"] != username]

    def kick_user(self, room_id, username):
        # AQUÍ IRÍA: network_client.send("COORD_KICK_USER", room_id, username)
        room = self.get_room(room_id)
        if room and username in room["members"]:
            room["members"].remove(username)

    def get_members(self, room_id):
        # AQUÍ IRÍA: network_client.request("COORD_LIST_MEMBERS", room_id)
        room = self.get_room(room_id)
        return room["members"] if room else []

    def delete_room(self, room_id):
        # AQUÍ IRÍA: network_client.send("COORD_DELETE_ROOM", room_id)
        room = self.get_room(room_id)
        if not room:
            return False
        # Solo se puede borrar si el coordinador es el único miembro
        if len(room["members"]) == 1 and room["members"][0] == self.current_user:
            self.rooms = [r for r in self.rooms if r["id"] != room_id]
            return True
        return False
