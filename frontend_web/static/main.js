const socket = io();
let currentUser = "", currentNickname = "", activeRoom = null;

// --- NAVEGACIÓN ---
function switchView(viewId) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.getElementById(viewId).classList.add('active');
}
function switchScreen(screenId) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById(screenId).classList.add('active');
}

// --- AUTH ---
document.getElementById('btn-login').onclick = () => {
    const u = document.getElementById('log-user').value.trim();
    if (!u) return document.getElementById('log-error').innerText = "◆ Username cannot be empty.";
    socket.emit('login', { username: u });
};
socket.on('login_success', data => {
    currentUser = data.username;
    currentNickname = data.nickname;
    document.getElementById('current-user-nick').innerText = currentNickname;
    switchView('app-view');
});

document.getElementById('btn-register').onclick = () => {
    const u = document.getElementById('reg-user').value.trim(), n = document.getElementById('reg-nick').value.trim(), p = document.getElementById('reg-pass').value;
    if (!u || !n || !p) return document.getElementById('reg-error').innerText = "◆ All fields are required.";
    socket.emit('register', { username: u, nickname: n, password: p });
};
socket.on('register_success', data => { alert("Account created: " + data.nickname); switchView('login-view'); });

// --- LOBBY DATA ---
socket.on('lobby_update', data => {
    const cl = document.getElementById('channel-list'); cl.innerHTML = '';
    data.rooms.forEach(r => {
        let li = document.createElement('li');
        li.innerText = `# ${r.name} ` + (r.notifications > 0 ? `[${r.notifications}]` : "");
        li.onclick = () => selectRoom(r);
        cl.appendChild(li);
    });
    const ol = document.getElementById('online-list'); ol.innerHTML = '';
    data.users.forEach(u => {
        let li = document.createElement('li');
        li.innerHTML = `<span class="status-dot">●</span> ${u.nickname}`;
        ol.appendChild(li);
    });
});

function selectRoom(r) {
    activeRoom = r.id;
    if (r.members.includes(currentUser)) {
        socket.emit('join_chat_view', {room_id: r.id});
    } else {
        document.getElementById('private-title').innerText = `# ${r.name}`;
        switchScreen('private-room-screen');
    }
}

// --- CHAT ---
socket.on('chat_view_data', data => {
    document.getElementById('chat-title').innerText = `# ${data.name}`;
    document.getElementById('btn-manage').style.display = data.is_coord ? 'inline-block' : 'none';
    document.getElementById('btn-leave').style.display = data.is_coord ? 'none' : 'inline-block';

    const hist = document.getElementById('chat-history');
    hist.innerHTML = '<div class="sys-msg">◆ Connected to node.</div>';
    data.history.forEach(m => appendMsg(m[0], m[1]));
    switchScreen('chat-screen');
});

document.getElementById('btn-send').onclick = () => {
    const inp = document.getElementById('chat-input');
    if (inp.value.trim() && activeRoom) {
        socket.emit('send_message', {room_id: activeRoom, text: inp.value.trim()});
        inp.value = '';
    }
};
document.getElementById('chat-input').onkeypress = (e) => { if(e.key === 'Enter') document.getElementById('btn-send').click(); };

socket.on('new_message', data => {
    if (data.room_id === activeRoom) appendMsg(data.sender, data.text);
    else showToast(data.room_id, data.sender, data.text);
});

function appendMsg(sender, text) {
    const hist = document.getElementById('chat-history');
    if (sender === "__SYSTEM__") hist.innerHTML += `<div class="sys-msg">◆ ${text}</div>`;
    else hist.innerHTML += `<div class="msg"><span class="msg-sender">[${sender}]</span> <span class="msg-text">${text}</span></div>`;
    hist.scrollTop = hist.scrollHeight;
}

// --- ROOM ACTIONS ---
function createRoom() { socket.emit('create_room', {name: document.getElementById('new-room-name').value}); closeModals(); }
function requestJoinRoom() { socket.emit('request_join', {room_id: activeRoom}); alert("Request sent!"); }
function leaveRoom() { if(confirm("Are you sure you want to leave?")) { socket.emit('leave_room', {room_id: activeRoom}); switchScreen('welcome-screen'); } }

// --- MODALES ---
function openModal(id) { document.getElementById('modal-bg').style.display = 'block'; document.getElementById(id).style.display = 'block'; }
function closeModals() { document.getElementById('modal-bg').style.display = 'none'; document.querySelectorAll('.modal').forEach(m => m.style.display = 'none'); }

// Profile
document.querySelector('.user-panel').onclick = () => {
    document.getElementById('avatar-initial').innerText = currentNickname[0].toUpperCase();
    document.getElementById('edit-nick').value = currentNickname;
    openModal('modal-profile');
};
function updateProfile() { socket.emit('update_profile', {nickname: document.getElementById('edit-nick').value}); closeModals(); }
socket.on('profile_updated', data => { currentNickname = data.nickname; document.getElementById('current-user-nick').innerText = currentNickname; });

// Coordinator
function openCoordPanel() { socket.emit('get_coord_data', {room_id: activeRoom}); openModal('modal-coord'); }
socket.on('coord_data', data => {
    document.getElementById('coord-title').innerText = "MANAGE";
    const reqDiv = document.getElementById('coord-requests'); reqDiv.innerHTML = '';
    data.requests.forEach(r => {
        reqDiv.innerHTML += `<div class="coord-row"><span>${r.nickname}</span><div><span style="color:var(--success);cursor:pointer;margin-right:10px;" onclick="coordAct('accept','${r.username}')">✓</span><span style="color:var(--error);cursor:pointer;" onclick="coordAct('reject','${r.username}')">✕</span></div></div>`;
    });
    const usrDiv = document.getElementById('coord-users'); usrDiv.innerHTML = '';
    data.all_users.forEach(u => {
        let btn = data.members.includes(u.username) ? `<span style="color:var(--error);cursor:pointer;" onclick="coordAct('kick','${u.username}')">KICK</span>` : `<span style="color:var(--accent);cursor:pointer;" onclick="coordAct('accept','${u.username}')">ADD</span>`;
        usrDiv.innerHTML += `<div class="coord-row"><span>${u.nickname}</span>${btn}</div>`;
    });
});
function coordAct(action, user) { socket.emit('coord_action', {room_id: activeRoom, action: action, target_user: user}); }
function deleteRoom() { if(confirm("Delete this room permanently?")) socket.emit('coord_action', {room_id: activeRoom, action: 'delete'}); }
socket.on('room_deleted_result', data => { if(data.success) { closeModals(); switchScreen('welcome-screen'); } else alert("You can only delete a room when you are the last member."); });

// --- TOASTS ---
function showToast(room, sender, text) {
    const cont = document.getElementById('toast-container');
    const t = document.createElement('div'); t.className = 'toast';
    t.innerHTML = `<div style="font-weight:bold; color:var(--accent); margin-bottom:5px;"># Mensaje Nuevo</div><div>${sender}: ${text.substring(0,30)}...</div>`;
    cont.appendChild(t);
    setTimeout(() => t.remove(), 4000);
}