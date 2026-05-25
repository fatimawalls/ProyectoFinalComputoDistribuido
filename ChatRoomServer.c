/*
 * ChatRoomServer.c - ChatRoom Server con persistencia JSON
 *
 * Arquitectura:
 *   - Padre: accept() + fork() en loop (TCP puerto 5000)
 *   - Hijo por cliente: auth + lobby (toda la vida de la conexion)
 *   - Hilo UDP (en padre): notificaciones push a clientes (UDP puerto 5001)
 *   - Memoria compartida + mutex: estado global (users, rooms, memberships)
 *   - Persistencia: database_repository.c guarda todo en JSON
 *
 * Compilar:
 *   gcc ChatRoomServer.c src/database_repository.c src/json_utils.c \
 *       src/index_manager.c src/memory_utils.c libs/cJSON.c \
 *       -Iinclude -Ilibs -lpthread -o chatserver
 *
 * Ejecutar: ./chatserver
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <pthread.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <sys/mman.h>
#include <fcntl.h>

 /* Repositorio JSON */
#include "models.h"
#include "database_repository.h"
#include "memory_utils.h"

/* ============================================================
   CONSTANTES
   ============================================================ */
#define TCP_PORT    5000
#define UDP_PORT    5001
#define MAX_USERS   64
#define MAX_ROOMS   32
#define MAX_MEMBERS 32
#define MAX_PENDING 16
#define BUFSIZE     1024

   /* ============================================================
      ESTRUCTURAS DE ESTADO GLOBAL (shared memory)
      ============================================================ */

      /*
       * ShmUser: representa un usuario CONECTADO en este momento.
       * db_user_id: ID que tiene ese usuario en users.json
       */
typedef struct {
    int  id;             /* slot id (1..MAX_USERS) */
    int  db_user_id;     /* ID real en users.json  */
    char username[64];
    char nickname[64];
    int  active;         /* 1 = conectado          */
    int  tcp_fd;
    char udp_ip[64];
    int  udp_port;
} ShmUser;

/*
 * ShmRoom: representa una sala activa en memoria.
 * db_room_id: ID que tiene esa sala en chatRooms.json
 */
typedef struct {
    int  id;             /* slot id (1..MAX_ROOMS) */
    int  db_room_id;     /* ID real en chatRooms.json */
    char name[64];
    int  coordinator_id; /* db_user_id del coordinador */
    int  members[MAX_MEMBERS];   /* db_user_ids */
    int  member_count;
    int  pending[MAX_PENDING];   /* db_user_ids esperando */
    int  pending_count;
    int  active;
} ShmRoom;

typedef struct {
    ShmUser users[MAX_USERS];
    ShmRoom rooms[MAX_ROOMS];
    int     user_count;
    int     room_count;
    pthread_mutex_t lock;
} SharedState;

/* ============================================================
   GLOBALES
   ============================================================ */
static SharedState* g_state = NULL;
static int          g_tcp_sd = -1;
static int          g_udp_sd = -1;

/* ============================================================
   UTILIDADES DE RED
   ============================================================ */

   /* Lee hasta '\n'. Devuelve bytes leidos, <=0 en error/cierre */
int recv_line(int fd, char* buf, int maxlen) {
    int total = 0;
    char c;
    while (total < maxlen - 1) {
        int n = recv(fd, &c, 1, 0);
        if (n <= 0) return n;
        if (c == '\n') break;
        buf[total++] = c;
    }
    buf[total] = '\0';
    return total;
}

/* Envia string terminado en '\n' */
void send_line(int fd, const char* msg) {
    char buf[BUFSIZE];
    snprintf(buf, sizeof(buf), "%s\n", msg);
    send(fd, buf, strlen(buf), 0);
}

/* ============================================================
   NOTIFICACIONES UDP
   ============================================================ */

   /* Envia notificacion UDP a un usuario por su db_user_id */
void udp_notify(int db_user_id, const char* msg) {
    pthread_mutex_lock(&g_state->lock);
    ShmUser* u = NULL;
    for (int i = 0; i < MAX_USERS; i++) {
        if (g_state->users[i].active &&
            g_state->users[i].db_user_id == db_user_id) {
            u = &g_state->users[i];
            break;
        }
    }
    if (!u || u->udp_port == 0) {
        pthread_mutex_unlock(&g_state->lock);
        return;
    }
    struct sockaddr_in dest;
    memset(&dest, 0, sizeof(dest));
    dest.sin_family = AF_INET;
    dest.sin_port = htons(u->udp_port);
    inet_aton(u->udp_ip, &dest.sin_addr);
    pthread_mutex_unlock(&g_state->lock);

    char buf[BUFSIZE];
    snprintf(buf, sizeof(buf), "%s\n", msg);
    sendto(g_udp_sd, buf, strlen(buf), 0,
        (struct sockaddr*)&dest, sizeof(dest));
}

/* Notifica a todos los miembros de una sala por db_room_id */
void udp_notify_room(int db_room_id, const char* msg) {
    pthread_mutex_lock(&g_state->lock);
    ShmRoom* r = NULL;
    for (int i = 0; i < MAX_ROOMS; i++) {
        if (g_state->rooms[i].active &&
            g_state->rooms[i].db_room_id == db_room_id) {
            r = &g_state->rooms[i];
            break;
        }
    }
    if (!r) { pthread_mutex_unlock(&g_state->lock); return; }
    int members[MAX_MEMBERS];
    int mc = r->member_count;
    memcpy(members, r->members, mc * sizeof(int));
    pthread_mutex_unlock(&g_state->lock);

    for (int i = 0; i < mc; i++) udp_notify(members[i], msg);
}

/* ============================================================
   AUTENTICACION  (usa users.json via database_repository)
   ============================================================ */

   /*
    * Busca usuario en users.json por nombre.
    * Devuelve 1 si existe, llena pass_out y db_id_out.
    */
static int buscar_usuario_json(const char* username,
    char* pass_out, int pass_maxlen,
    int* db_id_out)
{
    int count = 0;
    User* users = getAllUsers(&count);
    if (!users) return 0;

    int found = 0;
    for (int i = 0; i < count; i++) {
        if (strcmp(users[i].name, username) == 0) {
            strncpy(pass_out, users[i].password, pass_maxlen - 1);
            pass_out[pass_maxlen - 1] = '\0';
            *db_id_out = users[i].id;
            found = 1;
            break;
        }
    }
    freeUsers(users, count);
    return found;
}

/*
 * Registra un usuario nuevo en users.json.
 * Devuelve el db_id asignado, o -1 si ya existia.
 */
static int registrar_usuario_json(const char* username, const char* pass) {
    char tmp[64]; int tmp_id = 0;
    if (buscar_usuario_json(username, tmp, sizeof(tmp), &tmp_id)) return -1;

    User u = createUser(username, pass);
    saveUser(&u);
    int new_id = u.id;
    freeUser(&u);
    return new_id;
}

/*
 * Maneja el handshake de autenticacion con el cliente.
 * Devuelve db_user_id (>0) o -1 en fallo.
 */
int autenticar(int sock, const char* client_ip,
    char* username_out, int* udp_port_out)
{
    char buf[BUFSIZE];
    send_line(sock, "AUTH_REQUERIDA");

    while (1) {
        if (recv_line(sock, buf, sizeof(buf)) <= 0) return -1;

        /* Formato esperado:
         *   REGISTRO:user:pass
         *   LOGIN:user:pass:udp_port
         */
        char tipo[16], user[64], pass[64];
        int  uport = 0;

        char* p1 = strchr(buf, ':');
        if (!p1) { send_line(sock, "AUTH_FAIL:formato incorrecto"); continue; }
        *p1 = '\0';
        strncpy(tipo, buf, sizeof(tipo) - 1);

        char* p2 = strchr(p1 + 1, ':');
        if (!p2) { send_line(sock, "AUTH_FAIL:formato incorrecto"); continue; }
        *p2 = '\0';
        strncpy(user, p1 + 1, sizeof(user) - 1);

        char* p3 = strchr(p2 + 1, ':');
        if (p3) { *p3 = '\0'; uport = atoi(p3 + 1); }
        strncpy(pass, p2 + 1, sizeof(pass) - 1);

        if (!strlen(user) || !strlen(pass)) {
            send_line(sock, "AUTH_FAIL:campos vacios"); continue;
        }

        /* --- REGISTRO --- */
        if (strcmp(tipo, "REGISTRO") == 0) {
            int new_id = registrar_usuario_json(user, pass);
            if (new_id > 0)
                send_line(sock, "REGISTRO_OK");
            else
                send_line(sock, "REGISTRO_FAIL:usuario ya existe");
            continue;
        }

        /* --- LOGIN --- */
        if (strcmp(tipo, "LOGIN") == 0) {
            char stored[64]; int db_id = 0;
            if (!buscar_usuario_json(user, stored, sizeof(stored), &db_id)) {
                send_line(sock, "AUTH_FAIL:usuario no existe"); continue;
            }
            if (strcmp(stored, pass) != 0) {
                send_line(sock, "AUTH_FAIL:contrasena incorrecta"); continue;
            }

            /* Registrar en shared memory */
            pthread_mutex_lock(&g_state->lock);
            int slot = -1;
            for (int i = 0; i < MAX_USERS; i++) {
                if (!g_state->users[i].active) { slot = i; break; }
            }
            if (slot == -1) {
                pthread_mutex_unlock(&g_state->lock);
                send_line(sock, "AUTH_FAIL:servidor lleno");
                return -1;
            }
            ShmUser* u = &g_state->users[slot];
            u->id = slot + 1;
            u->db_user_id = db_id;
            u->active = 1;
            u->tcp_fd = sock;
            u->udp_port = uport;
            strncpy(u->username, user, sizeof(u->username) - 1);
            strncpy(u->nickname, user, sizeof(u->nickname) - 1);
            strncpy(u->udp_ip, client_ip, sizeof(u->udp_ip) - 1);
            g_state->user_count++;
            pthread_mutex_unlock(&g_state->lock);

            strncpy(username_out, user, 63);
            *udp_port_out = uport;

            char resp[BUFSIZE];
            snprintf(resp, sizeof(resp), "AUTH_OK:%d", db_id);
            send_line(sock, resp);
            return db_id;
        }

        send_line(sock, "AUTH_FAIL:tipo desconocido");
    }
}

/* ============================================================
   HELPERS DEL LOBBY
   ============================================================ */

   /* Busca ShmRoom por db_room_id. DEBE llamarse con lock tomado. */
static ShmRoom* find_room(int db_room_id) {
    for (int i = 0; i < MAX_ROOMS; i++) {
        if (g_state->rooms[i].active &&
            g_state->rooms[i].db_room_id == db_room_id)
            return &g_state->rooms[i];
    }
    return NULL;
}

static int es_miembro(int db_user_id, int db_room_id) {
    ShmRoom* r = find_room(db_room_id);
    if (!r) return 0;
    for (int i = 0; i < r->member_count; i++)
        if (r->members[i] == db_user_id) return 1;
    return 0;
}

static int es_coordinador(int db_user_id, int db_room_id) {
    ShmRoom* r = find_room(db_room_id);
    if (!r) return 0;
    return r->coordinator_id == db_user_id;
}

/* ============================================================
   LOGICA DEL LOBBY (corre en el proceso hijo)
   ============================================================ */

void procesar_lobby(int sock, int db_user_id) {
    char buf[BUFSIZE];
    char resp[BUFSIZE];

    printf("[Hijo uid=%d] Entrando al lobby\n", db_user_id);
    send_line(sock, "LOBBY_OK:bienvenido al e-lobby");

    while (1) {
        int n = recv_line(sock, buf, sizeof(buf));
        if (n <= 0) {
            printf("[Hijo uid=%d] Cliente desconectado\n", db_user_id);
            break;
        }
        printf("[Hijo uid=%d] Recibido: %s\n", db_user_id, buf);

        /* ── LOBBY_LIST_USERS ─────────────────────────────────── */
        if (strcmp(buf, "LOBBY_LIST_USERS") == 0) {
            pthread_mutex_lock(&g_state->lock);
            strcpy(resp, "USERS_LIST:");
            int first = 1;
            for (int i = 0; i < MAX_USERS; i++) {
                if (!g_state->users[i].active) continue;
                if (!first) strncat(resp, ",", sizeof(resp) - strlen(resp) - 1);
                char entry[128];
                snprintf(entry, sizeof(entry), "%d=%s",
                    g_state->users[i].db_user_id,
                    g_state->users[i].username);
                strncat(resp, entry, sizeof(resp) - strlen(resp) - 1);
                first = 0;
            }
            pthread_mutex_unlock(&g_state->lock);
            send_line(sock, resp);
            continue;
        }

        /* ── LOBBY_LIST_ROOMS ─────────────────────────────────── */
        if (strcmp(buf, "LOBBY_LIST_ROOMS") == 0) {
            pthread_mutex_lock(&g_state->lock);
            strcpy(resp, "ROOMS_LIST:");
            int first = 1;
            for (int i = 0; i < MAX_ROOMS; i++) {
                if (!g_state->rooms[i].active) continue;
                if (!first) strncat(resp, ",", sizeof(resp) - strlen(resp) - 1);
                char entry[192];
                snprintf(entry, sizeof(entry), "%d=%s(coord:%d,members:%d)",
                    g_state->rooms[i].db_room_id,
                    g_state->rooms[i].name,
                    g_state->rooms[i].coordinator_id,
                    g_state->rooms[i].member_count);
                strncat(resp, entry, sizeof(resp) - strlen(resp) - 1);
                first = 0;
            }
            pthread_mutex_unlock(&g_state->lock);
            send_line(sock, resp);
            continue;
        }

        /* ── LOBBY_CREATE_ROOM:nombre ─────────────────────────── */
        if (strncmp(buf, "LOBBY_CREATE_ROOM:", 18) == 0) {
            const char* nombre = buf + 18;
            if (!strlen(nombre)) { send_line(sock, "ROOM_FAIL:nombre vacio"); continue; }

            /* 1. Guardar en JSON */
            ChatRoom cr = createChatRoom(nombre, db_user_id);
            saveChatRoom(&cr);
            int db_rid = cr.id;
            freeChatRoom(&cr);

            /* 2. Registrar en shared memory */
            pthread_mutex_lock(&g_state->lock);
            int slot = -1;
            for (int i = 0; i < MAX_ROOMS; i++)
                if (!g_state->rooms[i].active) { slot = i; break; }

            if (slot == -1) {
                pthread_mutex_unlock(&g_state->lock);
                send_line(sock, "ROOM_FAIL:maximo de rooms alcanzado");
                continue;
            }
            ShmRoom* r = &g_state->rooms[slot];
            memset(r, 0, sizeof(ShmRoom));
            r->id = slot + 1;
            r->db_room_id = db_rid;
            r->active = 1;
            r->coordinator_id = db_user_id;
            r->members[0] = db_user_id;
            r->member_count = 1;
            strncpy(r->name, nombre, sizeof(r->name) - 1);
            g_state->room_count++;

            /* Recoger usuarios activos para notificar */
            int uids[MAX_USERS]; int uc = 0;
            for (int i = 0; i < MAX_USERS; i++)
                if (g_state->users[i].active &&
                    g_state->users[i].db_user_id != db_user_id)
                    uids[uc++] = g_state->users[i].db_user_id;
            pthread_mutex_unlock(&g_state->lock);

            snprintf(resp, sizeof(resp), "ROOM_CREATED:%d", db_rid);
            send_line(sock, resp);

            char notif[BUFSIZE];
            snprintf(notif, sizeof(notif), "NOTIF_ROOM_CREATED:%d=%s", db_rid, nombre);
            for (int i = 0; i < uc; i++) udp_notify(uids[i], notif);
            continue;
        }

        /* ── ROOM_MSG:room_id:texto  (NUEVO) ──────────────────── */
        if (strncmp(buf, "ROOM_MSG:", 9) == 0) {
            /* Parsear room_id y texto */
            char* colon = strchr(buf + 9, ':');
            if (!colon) { send_line(sock, "MSG_FAIL:formato incorrecto"); continue; }
            *colon = '\0';
            int   rid = atoi(buf + 9);
            const char* texto = colon + 1;

            if (!strlen(texto)) { send_line(sock, "MSG_FAIL:mensaje vacio"); continue; }

            /* Verificar membresia */
            pthread_mutex_lock(&g_state->lock);
            int miembro = es_miembro(db_user_id, rid);
            pthread_mutex_unlock(&g_state->lock);

            if (!miembro) { send_line(sock, "MSG_FAIL:no eres miembro de esa sala"); continue; }

            /* 1. Guardar mensaje en JSON */
            Message msg = createMessage(texto, db_user_id, rid);
            saveMessage(&msg);
            int msg_id = msg.id;
            freeMessage(&msg);

            printf("[Hijo uid=%d] Mensaje guardado id=%d en sala %d\n",
                db_user_id, msg_id, rid);

            /* 2. Obtener username del remitente para la notificacion */
            char sender_name[64] = "?";
            pthread_mutex_lock(&g_state->lock);
            for (int i = 0; i < MAX_USERS; i++) {
                if (g_state->users[i].active &&
                    g_state->users[i].db_user_id == db_user_id) {
                    strncpy(sender_name, g_state->users[i].username,
                        sizeof(sender_name) - 1);
                    break;
                }
            }
            pthread_mutex_unlock(&g_state->lock);

            /* 3. Confirmar al remitente */
            snprintf(resp, sizeof(resp), "MSG_OK:%d", msg_id);
            send_line(sock, resp);

            /* 4. Notificar a todos los miembros de la sala via UDP
             *    Formato: NOTIF_NEW_MSG:room_id:msg_id:user_id=username:texto
             */
            char notif[BUFSIZE];
            snprintf(notif, sizeof(notif),
                "NOTIF_NEW_MSG:%d:%d:%d=%s:%s",
                rid, msg_id, db_user_id, sender_name, texto);
            udp_notify_room(rid, notif);
            continue;
        }

        /* ── LOBBY_GET_MESSAGES:room_id  (historial) ─────────── */
        if (strncmp(buf, "LOBBY_GET_MESSAGES:", 19) == 0) {
            int rid = atoi(buf + 19);

            /* Verificar membresia */
            pthread_mutex_lock(&g_state->lock);
            int miembro = es_miembro(db_user_id, rid);
            pthread_mutex_unlock(&g_state->lock);

            if (!miembro) { send_line(sock, "MSG_FAIL:no eres miembro de esa sala"); continue; }

            /* Leer mensajes del JSON */
            int count = 0;
            Message* msgs = getMessagesFromChatRoom(rid, &count);

            if (!msgs || count == 0) {
                send_line(sock, "MESSAGES_LIST:");
                if (msgs) freeMessages(msgs, count);
                continue;
            }

            /* Construir respuesta:
             * MESSAGES_LIST:msg_id:user_id:texto|msg_id:user_id:texto|...
             */
            strcpy(resp, "MESSAGES_LIST:");
            for (int i = 0; i < count; i++) {
                char entry[BUFSIZE];
                snprintf(entry, sizeof(entry), "%d:%d:%s",
                    msgs[i].id, msgs[i].userId, msgs[i].text);
                strncat(resp, entry, sizeof(resp) - strlen(resp) - 1);
                if (i < count - 1)
                    strncat(resp, "|", sizeof(resp) - strlen(resp) - 1);
            }
            freeMessages(msgs, count);
            send_line(sock, resp);
            continue;
        }

        /* ── LOBBY_JOIN_REQUEST:room_id ───────────────────────── */
        if (strncmp(buf, "LOBBY_JOIN_REQUEST:", 19) == 0) {
            int rid = atoi(buf + 19);
            pthread_mutex_lock(&g_state->lock);
            ShmRoom* r = find_room(rid);
            if (!r) {
                pthread_mutex_unlock(&g_state->lock);
                send_line(sock, "ROOM_FAIL:room no existe"); continue;
            }
            if (es_miembro(db_user_id, rid)) {
                pthread_mutex_unlock(&g_state->lock);
                send_line(sock, "ROOM_FAIL:ya eres miembro"); continue;
            }
            if (r->pending_count >= MAX_PENDING) {
                pthread_mutex_unlock(&g_state->lock);
                send_line(sock, "ROOM_FAIL:cola llena"); continue;
            }
            r->pending[r->pending_count++] = db_user_id;
            int coord_id = r->coordinator_id;

            char uname[64] = "?";
            for (int i = 0; i < MAX_USERS; i++)
                if (g_state->users[i].db_user_id == db_user_id) {
                    strncpy(uname, g_state->users[i].username, sizeof(uname) - 1);
                    break;
                }
            pthread_mutex_unlock(&g_state->lock);

            send_line(sock, "REQUEST_PENDING");

            char notif[BUFSIZE];
            snprintf(notif, sizeof(notif), "NOTIF_JOIN_REQUEST:%d:%d=%s",
                rid, db_user_id, uname);
            udp_notify(coord_id, notif);
            continue;
        }

        /* ── COORD_ACCEPT:room_id:user_id ─────────────────────── */
        if (strncmp(buf, "COORD_ACCEPT:", 13) == 0) {
            int rid, target_uid;
            if (sscanf(buf + 13, "%d:%d", &rid, &target_uid) != 2) {
                send_line(sock, "ACTION_FAIL:formato incorrecto"); continue;
            }
            pthread_mutex_lock(&g_state->lock);
            if (!es_coordinador(db_user_id, rid)) {
                pthread_mutex_unlock(&g_state->lock);
                send_line(sock, "ACTION_FAIL:no eres coordinador"); continue;
            }
            ShmRoom* r = find_room(rid);
            int found = 0;
            for (int i = 0; i < r->pending_count; i++) {
                if (r->pending[i] == target_uid) {
                    r->pending[i] = r->pending[--r->pending_count];
                    found = 1; break;
                }
            }
            if (!found) {
                pthread_mutex_unlock(&g_state->lock);
                send_line(sock, "ACTION_FAIL:solicitud no encontrada"); continue;
            }
            r->members[r->member_count++] = target_uid;

            char uname[64] = "?";
            for (int i = 0; i < MAX_USERS; i++)
                if (g_state->users[i].db_user_id == target_uid) {
                    strncpy(uname, g_state->users[i].username, sizeof(uname) - 1);
                    break;
                }
            pthread_mutex_unlock(&g_state->lock);

            /* Persistir relacion en JSON */
            addUserToChatRoom(target_uid, rid);

            send_line(sock, "ACTION_OK");

            char notif[BUFSIZE];
            snprintf(notif, sizeof(notif), "NOTIF_ACCEPTED:%d", rid);
            udp_notify(target_uid, notif);

            snprintf(notif, sizeof(notif), "NOTIF_USER_JOINED:%d:%s", rid, uname);
            udp_notify_room(rid, notif);
            continue;
        }

        /* ── COORD_REJECT:room_id:user_id ─────────────────────── */
        if (strncmp(buf, "COORD_REJECT:", 13) == 0) {
            int rid, target_uid;
            if (sscanf(buf + 13, "%d:%d", &rid, &target_uid) != 2) {
                send_line(sock, "ACTION_FAIL:formato incorrecto"); continue;
            }
            pthread_mutex_lock(&g_state->lock);
            if (!es_coordinador(db_user_id, rid)) {
                pthread_mutex_unlock(&g_state->lock);
                send_line(sock, "ACTION_FAIL:no eres coordinador"); continue;
            }
            ShmRoom* r = find_room(rid);
            int found = 0;
            for (int i = 0; i < r->pending_count; i++) {
                if (r->pending[i] == target_uid) {
                    r->pending[i] = r->pending[--r->pending_count];
                    found = 1; break;
                }
            }
            pthread_mutex_unlock(&g_state->lock);

            send_line(sock, found ? "ACTION_OK" : "ACTION_FAIL:solicitud no encontrada");
            if (found) {
                char notif[BUFSIZE];
                snprintf(notif, sizeof(notif), "NOTIF_REJECTED:%d", rid);
                udp_notify(target_uid, notif);
            }
            continue;
        }

        /* ── COORD_KICK:room_id:user_id ───────────────────────── */
        if (strncmp(buf, "COORD_KICK:", 11) == 0) {
            int rid, target_uid;
            if (sscanf(buf + 11, "%d:%d", &rid, &target_uid) != 2) {
                send_line(sock, "ACTION_FAIL:formato incorrecto"); continue;
            }
            pthread_mutex_lock(&g_state->lock);
            if (!es_coordinador(db_user_id, rid)) {
                pthread_mutex_unlock(&g_state->lock);
                send_line(sock, "ACTION_FAIL:no eres coordinador"); continue;
            }
            ShmRoom* r = find_room(rid);
            int found = 0;
            for (int i = 0; i < r->member_count; i++) {
                if (r->members[i] == target_uid) {
                    r->members[i] = r->members[--r->member_count];
                    found = 1; break;
                }
            }
            char uname[64] = "?";
            for (int i = 0; i < MAX_USERS; i++)
                if (g_state->users[i].db_user_id == target_uid) {
                    strncpy(uname, g_state->users[i].username, sizeof(uname) - 1);
                    break;
                }
            pthread_mutex_unlock(&g_state->lock);

            /* No hay removeUserFromChatRoom en el repo, pero podemos
             * simplemente no persistir el kick por ahora, o se puede
             * implementar llamando a updateChatRoom directamente.      */

            send_line(sock, found ? "ACTION_OK" : "ACTION_FAIL:usuario no en la room");
            if (found) {
                char notif[BUFSIZE];
                snprintf(notif, sizeof(notif), "NOTIF_KICKED:%d", rid);
                udp_notify(target_uid, notif);
                snprintf(notif, sizeof(notif), "NOTIF_USER_LEFT:%d:%s", rid, uname);
                udp_notify_room(rid, notif);
            }
            continue;
        }

        /* ── COORD_INVITE:room_id:user_id ─────────────────────── */
        if (strncmp(buf, "COORD_INVITE:", 13) == 0) {
            int rid, target_uid;
            if (sscanf(buf + 13, "%d:%d", &rid, &target_uid) != 2) {
                send_line(sock, "ACTION_FAIL:formato incorrecto"); continue;
            }
            pthread_mutex_lock(&g_state->lock);
            if (!es_coordinador(db_user_id, rid)) {
                pthread_mutex_unlock(&g_state->lock);
                send_line(sock, "ACTION_FAIL:no eres coordinador"); continue;
            }
            if (es_miembro(target_uid, rid)) {
                pthread_mutex_unlock(&g_state->lock);
                send_line(sock, "ACTION_FAIL:ya es miembro"); continue;
            }
            ShmRoom* r = find_room(rid);
            r->members[r->member_count++] = target_uid;
            char rname[64];
            strncpy(rname, r->name, sizeof(rname) - 1);
            pthread_mutex_unlock(&g_state->lock);

            /* Persistir en JSON */
            addUserToChatRoom(target_uid, rid);

            send_line(sock, "ACTION_OK");
            char notif[BUFSIZE];
            snprintf(notif, sizeof(notif), "NOTIF_INVITED:%d=%s", rid, rname);
            udp_notify(target_uid, notif);
            continue;
        }

        /* ── COORD_DELETE_ROOM:room_id ────────────────────────── */
        if (strncmp(buf, "COORD_DELETE_ROOM:", 18) == 0) {
            int rid = atoi(buf + 18);
            pthread_mutex_lock(&g_state->lock);
            if (!es_coordinador(db_user_id, rid)) {
                pthread_mutex_unlock(&g_state->lock);
                send_line(sock, "ACTION_FAIL:no eres coordinador"); continue;
            }
            ShmRoom* r = find_room(rid);
            if (!r) {
                pthread_mutex_unlock(&g_state->lock);
                send_line(sock, "ACTION_FAIL:sala no existe"); continue;
            }
            if (r->member_count > 1) {
                pthread_mutex_unlock(&g_state->lock);
                send_line(sock, "ACTION_FAIL:la room no esta vacia"); continue;
            }
            r->active = 0;

            int uids[MAX_USERS]; int uc = 0;
            for (int i = 0; i < MAX_USERS; i++)
                if (g_state->users[i].active)
                    uids[uc++] = g_state->users[i].db_user_id;
            pthread_mutex_unlock(&g_state->lock);

            send_line(sock, "ACTION_OK");
            char notif[BUFSIZE];
            snprintf(notif, sizeof(notif), "NOTIF_ROOM_DELETED:%d", rid);
            for (int i = 0; i < uc; i++) udp_notify(uids[i], notif);
            continue;
        }

        /* ── LOBBY_SET_NICK:nickname ──────────────────────────── */
        if (strncmp(buf, "LOBBY_SET_NICK:", 15) == 0) {
            const char* nick = buf + 15;
            pthread_mutex_lock(&g_state->lock);
            for (int i = 0; i < MAX_USERS; i++) {
                if (g_state->users[i].db_user_id == db_user_id) {
                    strncpy(g_state->users[i].nickname, nick,
                        sizeof(g_state->users[i].nickname) - 1);
                    break;
                }
            }
            pthread_mutex_unlock(&g_state->lock);
            send_line(sock, "NICK_OK");
            continue;
        }

        /* ── Comando desconocido ──────────────────────────────── */
        send_line(sock, "ERR_UNKNOWN_CMD");
    }
}

/* ============================================================
   FUNCION DEL HIJO
   ============================================================ */

void atender_cliente(int sock, const char* client_ip) {
    char username[64] = "";
    int  udp_port = 0;

    int uid = autenticar(sock, client_ip, username, &udp_port);
    if (uid < 0) {
        printf("[Hijo] Auth fallida para %s\n", client_ip);
        close(sock);
        exit(0);
    }
    printf("[Hijo uid=%d] Autenticado: %s\n", uid, username);

    procesar_lobby(sock, uid);

    /* Limpiar shared memory */
    pthread_mutex_lock(&g_state->lock);
    for (int i = 0; i < MAX_USERS; i++) {
        if (g_state->users[i].db_user_id == uid) {
            g_state->users[i].active = 0;
            break;
        }
    }
    for (int i = 0; i < MAX_ROOMS; i++) {
        ShmRoom* r = &g_state->rooms[i];
        if (!r->active) continue;
        for (int j = 0; j < r->member_count; j++) {
            if (r->members[j] == uid) {
                r->members[j] = r->members[--r->member_count]; break;
            }
        }
    }

    int uids[MAX_USERS]; int uc = 0;
    for (int i = 0; i < MAX_USERS; i++)
        if (g_state->users[i].active)
            uids[uc++] = g_state->users[i].db_user_id;
    pthread_mutex_unlock(&g_state->lock);

    char notif[BUFSIZE];
    snprintf(notif, sizeof(notif), "NOTIF_USER_OFFLINE:%d=%s", uid, username);
    for (int i = 0; i < uc; i++) udp_notify(uids[i], notif);

    close(sock);
    printf("[Hijo uid=%d] Terminando\n", uid);
    exit(0);
}

/* ============================================================
   HILO UDP
   ============================================================ */

void* hilo_udp(void* arg) {
    (void)arg;
    char buf[BUFSIZE];
    struct sockaddr_in src;
    socklen_t slen = sizeof(src);
    printf("[UDP] Hilo de notificaciones activo en puerto %d\n", UDP_PORT);
    while (1) {
        int n = recvfrom(g_udp_sd, buf, sizeof(buf) - 1, 0,
            (struct sockaddr*)&src, &slen);
        if (n > 0) {
            buf[n] = '\0';
            printf("[UDP] Recibido: %s", buf);
        }
    }
    return NULL;
}

/* ============================================================
   SIGNAL HANDLERS
   ============================================================ */

void sig_chld(int sig) {
    (void)sig;
    while (waitpid(-1, NULL, WNOHANG) > 0);
}

void sig_int(int sig) {
    (void)sig;
    printf("\n[Padre] Cerrando servidor...\n");
    if (g_tcp_sd != -1) close(g_tcp_sd);
    if (g_udp_sd != -1) close(g_udp_sd);
    exit(0);
}

/* ============================================================
   MAIN
   ============================================================ */

int main(void) {
    /* Shared memory */
    g_state = mmap(NULL, sizeof(SharedState),
        PROT_READ | PROT_WRITE,
        MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (g_state == MAP_FAILED) { perror("mmap"); exit(1); }
    memset(g_state, 0, sizeof(SharedState));

    pthread_mutexattr_t mattr;
    pthread_mutexattr_init(&mattr);
    pthread_mutexattr_setpshared(&mattr, PTHREAD_PROCESS_SHARED);
    pthread_mutex_init(&g_state->lock, &mattr);
    pthread_mutexattr_destroy(&mattr);

    /* Socket UDP */
    g_udp_sd = socket(AF_INET, SOCK_DGRAM, 0);
    if (g_udp_sd == -1) { perror("udp socket"); exit(1); }
    struct sockaddr_in udp_addr;
    memset(&udp_addr, 0, sizeof(udp_addr));
    udp_addr.sin_family = AF_INET;
    udp_addr.sin_addr.s_addr = INADDR_ANY;
    udp_addr.sin_port = htons(UDP_PORT);
    if (bind(g_udp_sd, (struct sockaddr*)&udp_addr, sizeof(udp_addr)) == -1) {
        perror("udp bind"); exit(1);
    }

    pthread_t tid;
    pthread_create(&tid, NULL, hilo_udp, NULL);
    pthread_detach(tid);

    /* Socket TCP */
    g_tcp_sd = socket(AF_INET, SOCK_STREAM, 0);
    if (g_tcp_sd == -1) { perror("tcp socket"); exit(1); }
    int opt = 1;
    setsockopt(g_tcp_sd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    struct sockaddr_in tcp_addr;
    memset(&tcp_addr, 0, sizeof(tcp_addr));
    tcp_addr.sin_family = AF_INET;
    tcp_addr.sin_addr.s_addr = INADDR_ANY;
    tcp_addr.sin_port = htons(TCP_PORT);
    if (bind(g_tcp_sd, (struct sockaddr*)&tcp_addr, sizeof(tcp_addr)) == -1) {
        perror("tcp bind"); exit(1);
    }
    if (listen(g_tcp_sd, 10) == -1) { perror("listen"); exit(1); }

    signal(SIGCHLD, sig_chld);
    signal(SIGINT, sig_int);

    printf("[Padre] Servidor listo - TCP:%d  UDP:%d\n", TCP_PORT, UDP_PORT);

    /* Loop principal */
    while (1) {
        struct sockaddr_in client_addr;
        socklen_t clen = sizeof(client_addr);
        int client_fd = accept(g_tcp_sd, (struct sockaddr*)&client_addr, &clen);
        if (client_fd == -1) { perror("accept"); continue; }

        char client_ip[INET_ADDRSTRLEN];
        inet_ntop(AF_INET, &client_addr.sin_addr, client_ip, sizeof(client_ip));
        printf("[Padre] Nueva conexion de %s\n", client_ip);

        pid_t pid = fork();
        if (pid < 0) { perror("fork"); close(client_fd); continue; }

        if (pid == 0) {
            close(g_tcp_sd);
            atender_cliente(client_fd, client_ip);
        }

        close(client_fd);
    }

    return 0;
}