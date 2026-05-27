// ═══════════════════════════════════════════════════════════════
//  main.js — PIMENTEL CO. Web Frontend
// ═══════════════════════════════════════════════════════════════

const socket = io();

// --- ESTADO GLOBAL ---
let currentUser     = "";
let currentNickname = "";
let activeRoom      = null;
let isCoordinator   = false;
let lobbyData       = { rooms: [], users: [], all_users: [] };
let allUsersMap     = {};
let pendingRooms    = new Set();
let simLeft         = {};
let activeToasts    = [];

// Nombres de salas para la simulación de creación
const SIM_ROOM_NAMES = ["ops-team", "security", "backend", "qa-testing", "design", "infra", "alerts"];


// ═══════════════════════════════════════════════════════════════
//  NAVEGACIÓN
// ═══════════════════════════════════════════════════════════════

function switchView(viewId) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.getElementById(viewId).classList.add('active');
}

function switchScreen(screenId) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById(screenId).classList.add('active');
}


// ═══════════════════════════════════════════════════════════════
//  CUSTOM DIALOGS
// ═══════════════════════════════════════════════════════════════

function customConfirm(title, message, onConfirm, onCancel) {
    document.getElementById('confirm-title').innerText = title;
    document.getElementById('confirm-msg').innerText   = message;
    document.querySelectorAll('.modal').forEach(m => m.style.display = 'none');

    document.getElementById('confirm-ok').onclick = () => {
        document.getElementById('modal-bg').style.display    = 'none';
        document.getElementById('modal-confirm').style.display = 'none';
        if (onConfirm) onConfirm();
    };
    document.getElementById('confirm-cancel').onclick = () => {
        document.getElementById('modal-bg').style.display    = 'none';
        document.getElementById('modal-confirm').style.display = 'none';
        if (onCancel) onCancel();
    };
    document.getElementById('modal-bg').style.display      = 'block';
    document.getElementById('modal-confirm').style.display = 'block';
}

function customInfo(title, message, color) {
    color = color || 'var(--accent)';
    document.getElementById('info-title').innerText      = title;
    document.getElementById('info-msg').innerText        = message;
    document.getElementById('info-top').style.background = color;
    document.getElementById('info-ok').style.background  = color;
    document.querySelectorAll('.modal').forEach(m => m.style.display = 'none');

    document.getElementById('info-ok').onclick = () => {
        document.getElementById('modal-bg').style.display   = 'none';
        document.getElementById('modal-info').style.display = 'none';
    };
    document.getElementById('modal-bg').style.display   = 'block';
    document.getElementById('modal-info').style.display = 'block';
}


// ═══════════════════════════════════════════════════════════════
//  AUTENTICACIÓN
// ═══════════════════════════════════════════════════════════════

document.getElementById('btn-login').onclick = () => {
    const user = document.getElementById('log-user').value.trim();
    const pass = document.getElementById('log-pass').value.trim();
    const err  = document.getElementById('log-error');
    if (!user) { err.innerText = "◆ Username cannot be empty."; return; }
    if (!pass) { err.innerText = "◆ Password cannot be empty."; return; }
    err.innerText = "";
    socket.emit('login', { username: user, password: pass });
};

document.getElementById('log-user').addEventListener('keypress', e => { if (e.key === 'Enter') document.getElementById('log-pass').focus(); });
document.getElementById('log-pass').addEventListener('keypress', e => { if (e.key === 'Enter') document.getElementById('btn-login').click(); });

socket.on('login_success', data => {
    currentUser     = data.username;
    currentNickname = data.nickname;
    document.getElementById('current-user-nick').innerText = currentNickname;
    document.getElementById('welcome-nick').innerText      = `Welcome, ${currentNickname}.`;
    switchView('app-view');
    startSimulations();
});

socket.on('login_error', data => {
    document.getElementById('log-error').innerText = `◆ ${data.message}`;
});

document.getElementById('btn-register').onclick = () => {
    const user    = document.getElementById('reg-user').value.trim();
    const nick    = document.getElementById('reg-nick').value.trim();
    const pass    = document.getElementById('reg-pass').value;
    const confirm = document.getElementById('reg-confirm').value;
    const err     = document.getElementById('reg-error');

    if (!user)           { err.innerText = "◆ Username cannot be empty.";                return; }
    if (user.length < 3) { err.innerText = "◆ Username must be at least 3 characters.";  return; }
    if (!nick)           { err.innerText = "◆ Display name cannot be empty.";            return; }
    if (!pass)           { err.innerText = "◆ Password cannot be empty.";                return; }
    if (pass.length < 6) { err.innerText = "◆ Password must be at least 6 characters."; return; }
    if (pass !== confirm) { err.innerText = "◆ Passwords do not match."; document.getElementById('reg-confirm').value = ''; return; }
    err.innerText = "";
    socket.emit('register', { username: user, nickname: nick, password: pass });
};

['reg-user','reg-nick','reg-pass','reg-confirm'].forEach((id, i, arr) => {
    document.getElementById(id).addEventListener('keypress', e => {
        if (e.key === 'Enter') {
            if (i < arr.length - 1) document.getElementById(arr[i + 1]).focus();
            else document.getElementById('btn-register').click();
        }
    });
});

socket.on('register_success', data => {
    customInfo('ACCOUNT CREATED', `Welcome, ${data.nickname}. You can now sign in.`);
    switchView('login-view');
});


// ═══════════════════════════════════════════════════════════════
//  LOBBY DATA
// ═══════════════════════════════════════════════════════════════

socket.on('lobby_update', data => {
    lobbyData = data;
    allUsersMap = {};
    if (data.all_users) {
        data.all_users.forEach(u => { allUsersMap[u.username] = u; });
    }
    updateChannelList();
    updateUsersList();
});

function updateChannelList() {
    const cl = document.getElementById('channel-list');
    cl.innerHTML = '';
    lobbyData.rooms.forEach(r => {
        const li    = document.createElement('li');
        const notif = r.notifications > 0 ? ` [${r.notifications}]` : '';
        li.innerText = `# ${r.name}${notif}`;
        if (r.notifications > 0) li.classList.add('has-notif');
        li.onclick = () => selectRoom(r);
        cl.appendChild(li);
    });
}

function updateUsersList() {
    // Muestra TODOS los usuarios (online y offline) con dots de color
    const ul = document.getElementById('users-list');
    ul.innerHTML = '';
    const allUsers = lobbyData.all_users || lobbyData.users || [];
    allUsers.forEach(u => {
        const li      = document.createElement('li');
        const dotCls  = u.online ? 'online-dot' : 'offline-dot';
        li.innerHTML  = `<span class="status-dot ${dotCls}">●</span> ${u.nickname}`;
        ul.appendChild(li);
    });
}

function selectRoom(r) {
    activeRoom = r.id;
    r.notifications = 0;
    updateChannelList();

    if (r.members && r.members.includes(currentUser)) {
        socket.emit('join_chat_view', { room_id: r.id });
    } else {
        document.getElementById('private-title').innerText = `# ${r.name}`;
        const isPending = pendingRooms.has(r.id);
        document.getElementById('private-not-requested').style.display = isPending ? 'none' : 'flex';
        document.getElementById('private-pending').style.display       = isPending ? 'block' : 'none';
        switchScreen('private-room-screen');
    }
}


// ═══════════════════════════════════════════════════════════════
//  CHAT
// ═══════════════════════════════════════════════════════════════

socket.on('chat_view_data', data => {
    activeRoom    = data.room_id;
    isCoordinator = data.is_coord;

    document.getElementById('chat-title').innerText = `# ${data.name}`;

    const roleEl     = document.getElementById('role-indicator');
    roleEl.innerText = data.is_coord ? 'COORDINATOR' : 'MEMBER';
    roleEl.className = `role-badge ${data.is_coord ? 'role-coord' : 'role-member'}`;

    // Botones según rol
    document.getElementById('btn-manage').style.display  = data.is_coord ? 'inline-block' : 'none';
    document.getElementById('btn-leave').style.display   = data.is_coord ? 'none' : 'inline-block';
    document.getElementById('btn-members').style.display = data.is_coord ? 'none' : 'inline-block';

    const hist = document.getElementById('chat-history');
    hist.innerHTML = '<div class="sys-msg">◆ Connected to node.</div>';
    if (data.history) data.history.forEach(m => appendMsg(m[0], m[1]));

    switchScreen('chat-screen');
    document.getElementById('chat-input').focus();
});

document.getElementById('btn-send').onclick = sendMessage;
document.getElementById('chat-input').addEventListener('keypress', e => { if (e.key === 'Enter') sendMessage(); });

function sendMessage() {
    const inp  = document.getElementById('chat-input');
    const text = inp.value.trim();
    if (text && activeRoom) {
        socket.emit('send_message', { room_id: activeRoom, text });
        inp.value = '';
    }
}

socket.on('new_message', data => {
    if (data.room_id === activeRoom) {
        appendMsg(data.sender, data.text);
    } else {
        const room = lobbyData.rooms.find(r => r.id === data.room_id);
        if (room) {
            room.notifications = (room.notifications || 0) + 1;
            updateChannelList();
            showToast(data.room_id, room.name, data.sender, data.text);
        }
    }
});

socket.on('system_event', data => {
    if (data.room_id === activeRoom) appendMsg('__SYSTEM__', data.text);
});

function appendMsg(sender, text) {
    const hist = document.getElementById('chat-history');
    if (sender === '__SYSTEM__') {
        hist.innerHTML += `<div class="sys-msg">◆ ${text}</div>`;
    } else {
        hist.innerHTML += `<div class="msg"><span class="msg-sender">[${sender}]</span> <span class="msg-text">${text}</span></div>`;
    }
    hist.scrollTop = hist.scrollHeight;
}


// ═══════════════════════════════════════════════════════════════
//  MEMBERS PANEL (para usuarios no coordinadores)
// ═══════════════════════════════════════════════════════════════

function openMembersPanel() {
    if (!activeRoom) return;
    socket.emit('get_members_data', { room_id: activeRoom });
    openModal('modal-members');
}

socket.on('members_data', data => {
    document.getElementById('members-title').innerText = `# ${data.name}`;
    document.getElementById('members-count').innerText = `${data.members.length} member(s)`;

    const list = document.getElementById('members-list');
    list.innerHTML = '';

    data.members.forEach(m => {
        const dotCls = m.online ? 'online-dot' : 'offline-dot';
        let label    = m.nickname;
        if (m.is_coord)              label += ' <span class="muted-text">[COORD]</span>';
        if (m.username === currentUser) label += ' <span class="muted-text">(you)</span>';

        const row = document.createElement('div');
        row.className = 'coord-row';
        row.innerHTML = `
            <div style="display:flex; align-items:center; gap:8px;">
                <span class="status-dot ${dotCls}">●</span>
                <span>${label}</span>
            </div>`;
        list.appendChild(row);
    });
});


// ═══════════════════════════════════════════════════════════════
//  ACCIONES DE SALA
// ═══════════════════════════════════════════════════════════════

function requestJoinRoom() {
    if (!activeRoom) return;
    socket.emit('request_join', { room_id: activeRoom });
}

socket.on('join_requested', data => {
    if (data.status === 'ok') {
        pendingRooms.add(data.room_id);
        document.getElementById('private-not-requested').style.display = 'none';
        document.getElementById('private-pending').style.display       = 'block';
    } else {
        customInfo('WARNING', data.message || 'Could not send join request.', 'var(--warning)');
    }
});

function leaveRoom() {
    if (!activeRoom) return;
    customConfirm('LEAVE ROOM', 'Are you sure you want to leave this room?', () => {
        socket.emit('leave_room', { room_id: activeRoom });
    });
}

socket.on('left_room', () => { activeRoom = null; switchScreen('welcome-screen'); });


// ═══════════════════════════════════════════════════════════════
//  CREATE ROOM
// ═══════════════════════════════════════════════════════════════

function createRoom() {
    const name  = document.getElementById('new-room-name').value.trim();
    const errEl = document.getElementById('create-room-error');
    if (!name)           { errEl.innerText = "◆ Room name cannot be empty.";               return; }
    if (name.length < 3) { errEl.innerText = "◆ Room name must be at least 3 characters."; return; }
    errEl.innerText = "";
    socket.emit('create_room', { name });
    document.getElementById('new-room-name').value = '';
    closeModals();
}

document.getElementById('new-room-name').addEventListener('keypress', e => { if (e.key === 'Enter') createRoom(); });

socket.on('room_created', data => {
    activeRoom = data.room_id;
    socket.emit('join_chat_view', { room_id: data.room_id });
});

socket.on('create_room_error', data => {
    document.getElementById('create-room-error').innerText = `◆ ${data.message}`;
});


// ═══════════════════════════════════════════════════════════════
//  COORDINATOR PANEL
// ═══════════════════════════════════════════════════════════════

function openCoordPanel() {
    if (!activeRoom) return;
    socket.emit('get_coord_data', { room_id: activeRoom });
    openModal('modal-coord');
}

socket.on('coord_data', data => {
    const room = lobbyData.rooms.find(r => r.id === data.room_id);
    document.getElementById('coord-title').innerText = `# ${room ? room.name : data.room_id}`;

    // PENDING REQUESTS
    const reqDiv = document.getElementById('coord-requests');
    reqDiv.innerHTML = '';
    if (!data.requests || data.requests.length === 0) {
        reqDiv.innerHTML = '<p class="muted-text" style="font-size:13px; padding:5px 0;">No pending requests.</p>';
    } else {
        data.requests.forEach(r => {
            const row = document.createElement('div');
            row.className = 'coord-row';
            row.innerHTML = `
                <span>● ${r.nickname}</span>
                <div>
                    <span class="coord-btn success-text" onclick="coordAction('accept','${r.username}','${r.nickname}')">✓</span>
                    <span class="coord-btn error-text" style="margin-left:10px;" onclick="coordAction('reject','${r.username}','${r.nickname}')">✕</span>
                </div>`;
            reqDiv.appendChild(row);
        });
    }

    // ALL USERS
    const usrDiv = document.getElementById('coord-users');
    usrDiv.innerHTML = '';
    if (!data.all_users || data.all_users.length === 0) {
        usrDiv.innerHTML = '<p class="muted-text" style="font-size:13px;">No users available.</p>';
    } else {
        data.all_users.forEach(u => {
            const isMember = data.members && data.members.includes(u.username);
            const isCoord  = u.username === data.coordinator;
            const dotCls   = `status-dot ${u.online ? 'online-dot' : 'offline-dot'}`;
            let label      = u.nickname;
            if (isCoord) label += ' <span class="muted-text">[COORD]</span>';

            let actionBtn = '';
            if (isMember) {
                actionBtn = u.username === currentUser
                    ? '<span class="muted-text" style="font-size:12px; font-weight:bold;">YOU</span>'
                    : `<span class="coord-btn error-text" onclick="coordActionWithConfirm('kick','${u.username}','${u.nickname}')">KICK</span>`;
            } else {
                actionBtn = `<span class="coord-btn accent-text" onclick="coordAction('add','${u.username}','${u.nickname}')">ADD</span>`;
            }

            const row = document.createElement('div');
            row.className = 'coord-row';
            row.innerHTML = `
                <div style="display:flex; align-items:center; gap:8px;">
                    <span class="${dotCls}">●</span><span>${label}</span>
                </div>
                ${actionBtn}`;
            usrDiv.appendChild(row);
        });
    }
});

function coordAction(action, username, nickname) {
    socket.emit('coord_action', { action, room_id: activeRoom, target_user: username, target_nick: nickname });
}

function coordActionWithConfirm(action, username, nickname) {
    customConfirm('KICK USER', `Remove ${nickname} from the room?`, () => coordAction(action, username, nickname));
}

function deleteRoom() {
    customConfirm('DELETE ROOM', 'Delete this room? This action cannot be undone.', () => {
        socket.emit('coord_action', { action: 'delete', room_id: activeRoom });
    });
}

socket.on('room_deleted_result', data => {
    if (data.success) {
        closeModals(); activeRoom = null; switchScreen('welcome-screen');
    } else {
        customInfo('WARNING', 'You can only delete a room when you are the last member.', 'var(--warning)');
    }
});


// ═══════════════════════════════════════════════════════════════
//  PERFIL
// ═══════════════════════════════════════════════════════════════

document.getElementById('user-panel').onclick = () => {
    document.getElementById('avatar-circle').innerText = currentNickname[0].toUpperCase();
    document.getElementById('profile-nick').innerText  = currentNickname;
    document.getElementById('profile-user').innerText  = `@${currentUser}`;
    document.getElementById('edit-nick').value         = currentNickname;
    openModal('modal-profile');
};

function updateProfile() {
    const newNick = document.getElementById('edit-nick').value.trim();
    if (!newNick) { customInfo('WARNING', 'Display name cannot be empty.', 'var(--warning)'); return; }
    socket.emit('update_profile', { nickname: newNick });
    closeModals();
}

socket.on('profile_updated', data => {
    currentNickname = data.nickname;
    document.getElementById('current-user-nick').innerText = currentNickname;
    document.getElementById('welcome-nick').innerText      = `Welcome, ${currentNickname}.`;
});


// ═══════════════════════════════════════════════════════════════
//  MODALES
// ═══════════════════════════════════════════════════════════════

function openModal(id) {
    document.getElementById('modal-bg').style.display = 'block';
    document.getElementById(id).style.display = 'block';
}

function closeModals() {
    document.getElementById('modal-bg').style.display = 'none';
    document.querySelectorAll('.modal').forEach(m => m.style.display = 'none');
}

function handleModalBgClick(e) {
    if (e.target.id === 'modal-bg') closeModals();
}


// ═══════════════════════════════════════════════════════════════
//  TOASTS
// ═══════════════════════════════════════════════════════════════

function showToast(roomId, roomName, sender, message) {
    if (activeToasts.length >= 10) return;

    const container = document.getElementById('toast-container');
    const toast     = document.createElement('div');
    toast.className = 'toast';
    const preview   = message.length > 38 ? message.substring(0, 38) + '...' : message;

    toast.innerHTML = `
        <div class="toast-header">
            <span class="toast-room"># ${roomName}</span>
            <span class="toast-close">✕</span>
        </div>
        <div class="toast-body">${sender}: ${preview}</div>`;

    toast.querySelector('.toast-close').onclick = (e) => { e.stopPropagation(); closeToast(toast); };
    toast.onclick = () => toastClick(toast, roomId);
    container.appendChild(toast);
    activeToasts.push(toast);
    toast._timer = setTimeout(() => closeToast(toast), 4000);
}

function closeToast(toast) {
    if (toast._timer) clearTimeout(toast._timer);
    activeToasts = activeToasts.filter(t => t !== toast);
    if (toast.parentElement) toast.remove();
}

function toastClick(toast, roomId) {
    closeToast(toast);
    const room = lobbyData.rooms.find(r => r.id === roomId);
    if (room && room.members && room.members.includes(currentUser)) {
        activeRoom = roomId; room.notifications = 0;
        updateChannelList();
        socket.emit('join_chat_view', { room_id: roomId });
    }
}


// ═══════════════════════════════════════════════════════════════
//  SIMULACIONES
// ═══════════════════════════════════════════════════════════════

let msgSimTimer    = null;
let leaveSimTimer  = null;
let roomSimTimer   = null;

function startSimulations() {
    if (msgSimTimer)   clearInterval(msgSimTimer);
    if (leaveSimTimer) clearInterval(leaveSimTimer);
    if (roomSimTimer)  clearInterval(roomSimTimer);

    // Mensajes entrantes cada 12 segundos
    msgSimTimer   = setInterval(simulateIncomingMessage, 12000);
    // Usuario saliendo cada 30 segundos
    leaveSimTimer = setInterval(simulateUserLeave, 30000);
    // Sala nueva creada por otro usuario cada 45 segundos
    roomSimTimer  = setInterval(simulateRoomCreation, 45000);
}

function getMyRooms() {
    return lobbyData.rooms.filter(r => r.members && r.members.includes(currentUser));
}

function getMemberSenders(room) {
    const left = simLeft[room.id] || new Set();
    return room.members
        .filter(u => u !== currentUser && !left.has(u))
        .map(u => allUsersMap[u] ? allUsersMap[u].nickname : null)
        .filter(n => n !== null);
}

function simulateIncomingMessage() {
    const myRooms = getMyRooms();
    if (myRooms.length === 0) return;

    const room    = myRooms[Math.floor(Math.random() * myRooms.length)];
    const senders = getMemberSenders(room);
    if (senders.length === 0) return;

    const sender   = senders[Math.floor(Math.random() * senders.length)];
    const messages = ["Hey, anyone there?", "Check this out.", "Meeting in 5.",
                      "Server looks good.", "Deploy done.", "Need a review."];
    const text     = messages[Math.floor(Math.random() * messages.length)];

    // Persistir en servidor
    socket.emit('sim_message', { room_id: room.id, sender, text });

    if (room.id === activeRoom) {
        appendMsg(sender, text);
    } else {
        room.notifications = (room.notifications || 0) + 1;
        updateChannelList();
        showToast(room.id, room.name, sender, text);
    }
}

function simulateUserLeave() {
    const myRooms = getMyRooms();
    if (myRooms.length === 0) return;

    const room       = myRooms[Math.floor(Math.random() * myRooms.length)];
    const left       = simLeft[room.id] || new Set();
    const candidates = room.members.filter(u => u !== currentUser && !left.has(u));
    if (candidates.length === 0) return;

    const leaverUsername = candidates[Math.floor(Math.random() * candidates.length)];
    const leaverNick     = allUsersMap[leaverUsername]
        ? allUsersMap[leaverUsername].nickname : leaverUsername;

    if (!simLeft[room.id]) simLeft[room.id] = new Set();
    simLeft[room.id].add(leaverUsername);

    const msg = `${leaverNick} has left the room.`;

    // Persistir mensaje de sistema y quitar de members en servidor
    socket.emit('sim_system', { room_id: room.id, text: msg });
    socket.emit('sim_leave',  { room_id: room.id, username: leaverUsername });

    // Actualizar members localmente para consistencia
    const idx = room.members.indexOf(leaverUsername);
    if (idx !== -1) room.members.splice(idx, 1);

    if (room.id === activeRoom) {
        appendMsg('__SYSTEM__', msg);
    } else {
        room.notifications = (room.notifications || 0) + 1;
        updateChannelList();
        showToast(room.id, room.name, '◆ System', `${leaverNick} has left.`);
    }
}

function simulateRoomCreation() {
    // Simula que otro usuario crea una sala nueva
    const existing  = lobbyData.rooms.map(r => r.name);
    const available = SIM_ROOM_NAMES.filter(n => !existing.includes(n));
    if (available.length === 0) return;

    const name       = available[Math.floor(Math.random() * available.length)];
    const others     = Object.values(allUsersMap).filter(u => u.online);
    if (others.length === 0) return;

    const creator = others[Math.floor(Math.random() * others.length)];

    // El servidor crea la sala y emite new_room_notification
    socket.emit('sim_create_room', {
        name:             name,
        creator_username: creator.username
    });
}