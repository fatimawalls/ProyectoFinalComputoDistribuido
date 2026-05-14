/*
 * server.c — ChatRoom Server
 * Arquitectura:
 *   - Padre: accept() + fork() en loop (TCP puerto 5000)
 *   - Hijo por cliente: auth + lobby (toda la vida de la conexion)
 *   - Hilo UDP (en padre): notificaciones push a clientes (UDP puerto 5001)
 *   - Memoria compartida + mutex: estado global (users, rooms, memberships)
 *
 * Compilar: cc server.c -lpthread -o server
 * Ejecutar:  ./server
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
#include <sys/mman.h>   /* mmap para shared memory entre padre e hijos */
#include <fcntl.h>

 /* ??? Constantes ??????????????????????????????????????????????????????????? */
#define TCP_PORT      5000
#define UDP_PORT      5001
#define MAX_USERS     64
#define MAX_ROOMS     32
#define MAX_MEMBERS   32
#define MAX_PENDING   16
#define BUFSIZE       1024
#define USERS_FILE    "usuarios.txt"

/* === Estructuras de estado global (van en shared memory) ================ */

typedef struct {
    int  id;
    char username[64];
    char nickname[64];
    int  active;           /* 1 = conectado */
    int  tcp_fd;           /* descriptor del socket TCP (solo valido en el hijo) */
    char udp_ip[64];       /* IP del cliente para notificaciones UDP */
    int  udp_port;         /* Puerto UDP del cliente */
} User;

typedef struct {
    int  id;
    char name[64];
    int  coordinator_id;
    int  members[MAX_MEMBERS];     /* user ids */
    int  member_count;
    int  pending[MAX_PENDING];     /* user ids esperando aceptacion */
    int  pending_count;
    int  active;
} Room;

typedef struct {
    User  users[MAX_USERS];
    Room  rooms[MAX_ROOMS];
    int   user_count;
    int   room_count;
    pthread_mutex_t lock;
} SharedState;

/* === Globales ============================================================ */
static SharedState* g_state = NULL;   /* apunta a la shared memory */
static int          g_tcp_sd = -1;    /* socket TCP principal */
static int          g_udp_sd = -1;    /* socket UDP para notificaciones */

/* ==========================================================================
   UTILIDADES DE RED
   ========================================================================== */

   /* Lee hasta '\n'. Devuelve bytes leidos, 0 o negativo en error/cierre */
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

/* Envia mensaje terminado en '\n' */
void send_line(int fd, const char* msg) {
    char buf[BUFSIZE];
    snprintf(buf, sizeof(buf), "%s\n", msg);
    send(fd, buf, strlen(buf), 0);
}

/* Envia notificacion UDP a un usuario especifico */
void udp_notify(int user_id, const char* msg) {
    pthread_mutex_lock(&g_state->lock);
    User* u = NULL;
    for (int i = 0; i < MAX_USERS; i++) {
        if (g_state->users[i].active && g_state->users[i].id == user_id) {
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

/* Notifica a todos los miembros de una room */
void udp_notify_room(int room_id, const char* msg) {
    pthread_mutex_lock(&g_state->lock);
    Room* r = NULL;
    for (int i = 0; i < MAX_ROOMS; i++) {
        if (g_state->rooms[i].active && g_state->rooms[i].id == room_id) {
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

/* ==========================================================================
   AUTENTICACION
   ========================================================================== */

int buscar_usuario(const char* usuario, char* pass_out, int maxlen) {
    FILE* f = fopen(USERS_FILE, "r");
    if (!f) return 0;
    char linea[BUFSIZE];
    while (fgets(linea, sizeof(linea), f)) {
        linea[strcspn(linea, "\n")] = '\0';
        char* sep = strchr(linea, ':');
        if (!sep) continue;
        *sep = '\0';
        if (strcmp(linea, usuario) == 0) {
            strncpy(pass_out, sep + 1, maxlen - 1);
            pass_out[maxlen - 1] = '\0';
            fclose(f);
            return 1;
        }
    }
    fclose(f);
    return 0;
}

int registrar_usuario(const char* usuario, const char* pass) {
    char tmp[BUFSIZE];
    if (buscar_usuario(usuario, tmp, sizeof(tmp))) return 0;
    FILE* f = fopen(USERS_FILE, "a");
    if (!f) return 0;
    fprintf(f, "%s:%s\n", usuario, pass);
    fclose(f);
    return 1;
}

/*
 * Maneja el intercambio de auth con el cliente.
 * Devuelve user_id asignado (>0) o -1 en fallo.
 * Rellena username_out y udp_port_out.
 */
int autenticar(int sock, const char* client_ip,
    char* username_out, int* udp_port_out) {
    char buf[BUFSIZE];
    send_line(sock, "AUTH_REQUERIDA");

    while (1) {
        if (recv_line(sock, buf, sizeof(buf)) <= 0) return -1;

        /* Formato: "LOGIN:user:pass:udp_port"  o  "REGISTRO:user:pass" */
        char tipo[16], user[64], pass[64];
        int  uport = 0;

        char* p1 = strchr(buf, ':');
        if (!p1) { send_line(sock, "AUTH_FAIL:formato incorrecto"); continue; }
        *p1 = '\0';
        strncpy(tipo, buf, sizeof(tipo) - 1); tipo[sizeof(tipo) - 1] = '\0';

        char* p2 = strchr(p1 + 1, ':');
        if (!p2) { send_line(sock, "AUTH_FAIL:formato incorrecto"); continue; }
        *p2 = '\0';
        strncpy(user, p1 + 1, sizeof(user) - 1); user[sizeof(user) - 1] = '\0';

        /* Si LOGIN, puede haber un cuarto campo udp_port */
        char* p3 = strchr(p2 + 1, ':');
        if (p3) {
            *p3 = '\0';
            uport = atoi(p3 + 1);
        }
        strncpy(pass, p2 + 1, sizeof(pass) - 1); pass[sizeof(pass) - 1] = '\0';

        if (!strlen(user) || !strlen(pass)) {
            send_line(sock, "AUTH_FAIL:campos vacios"); continue;
        }

        if (strcmp(tipo, "REGISTRO") == 0) {
            if (registrar_usuario(user, pass)) {
                send_line(sock, "REGISTRO_OK");
            }
            else {
                send_line(sock, "REGISTRO_FAIL:usuario ya existe");
            }
            continue;
        }

        if (strcmp(tipo, "LOGIN") == 0) {
            char stored[64];
            if (!buscar_usuario(user, stored, sizeof(stored))) {
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
            g_state->user_count++;
            User* u = &g_state->users[slot];
            u->id = slot + 1;
            u->active = 1;
            u->tcp_fd = sock;
            u->udp_port = uport;
            strncpy(u->username, user, sizeof(u->username) - 1);
            strncpy(u->nickname, user, sizeof(u->nickname) - 1); /* nickname = username por defecto */
            strncpy(u->udp_ip, client_ip, sizeof(u->udp_ip) - 1);
            int uid = u->id;
            pthread_mutex_unlock(&g_state->lock);

            strncpy(username_out, user, 63);
            *udp_port_out = uport;

            char resp[BUFSIZE];
            snprintf(resp, sizeof(resp), "AUTH_OK:%d", uid);
            send_line(sock, resp);
            return uid;
        }

        send_line(sock, "AUTH_FAIL:tipo desconocido");
    }
}

/* ==========================================================================
   HELPERS DE LOBBY
   ========================================================================== */

int es_miembro(int user_id, int room_id) {
    Room* r = &g_state->rooms[room_id - 1];
    for (int i = 0; i < r->member_count; i++)
        if (r->members[i] == user_id) return 1;
    return 0;
}

int es_coordinador(int user_id, int room_id) {
    Room* r = &g_state->rooms[room_id - 1];
    return r->coordinator_id == user_id;
}

/* ??????????????????????????????????????????????????????????????????????????
   LOGICA DEL LOBBY (corre en el hijo)
   ?????????????????????????????????????????????????????????????????????????? */

void procesar_lobby(int sock, int user_id) {
    char buf[BUFSIZE];
    char resp[BUFSIZE];

    printf("[Hijo uid=%d] Entrando al lobby\n", user_id);
    send_line(sock, "LOBBY_OK:bienvenido al e-lobby");

    while (1) {
        int n = recv_line(sock, buf, sizeof(buf));
        if (n <= 0) {
            printf("[Hijo uid=%d] Cliente desconectado\n", user_id);
            break;
        }

        printf("[Hijo uid=%d] Recibido: %s\n", user_id, buf);

        /* ?? LOBBY_LIST_USERS ??????????????????????????????????????? */
        if (strcmp(buf, "LOBBY_LIST_USERS") == 0) {
            pthread_mutex_lock(&g_state->lock);
            strcpy(resp, "USERS_LIST:");
            int first = 1;
            for (int i = 0; i < MAX_USERS; i++) {
                if (g_state->users[i].active) {
                    if (!first) strncat(resp, ",", sizeof(resp) - strlen(resp) - 1);
                    char entry[128];
                    snprintf(entry, sizeof(entry), "%d=%s",
                        g_state->users[i].id,
                        g_state->users[i].username);
                    strncat(resp, entry, sizeof(resp) - strlen(resp) - 1);
                    first = 0;
                }
            }
            pthread_mutex_unlock(&g_state->lock);
            send_line(sock, resp);
            continue;
        }

        /* ?? LOBBY_LIST_ROOMS ??????????????????????????????????????? */
        if (strcmp(buf, "LOBBY_LIST_ROOMS") == 0) {
            pthread_mutex_lock(&g_state->lock);
            strcpy(resp, "ROOMS_LIST:");
            int first = 1;
            for (int i = 0; i < MAX_ROOMS; i++) {
                if (g_state->rooms[i].active) {
                    if (!first) strncat(resp, ",", sizeof(resp) - strlen(resp) - 1);
                    char entry[128];
                    snprintf(entry, sizeof(entry), "%d=%s(coord:%d,members:%d)",
                        g_state->rooms[i].id,
                        g_state->rooms[i].name,
                        g_state->rooms[i].coordinator_id,
                        g_state->rooms[i].member_count);
                    strncat(resp, entry, sizeof(resp) - strlen(resp) - 1);
                    first = 0;
                }
            }
            pthread_mutex_unlock(&g_state->lock);
            send_line(sock, resp);
            continue;
        }

        /* ?? LOBBY_CREATE_ROOM:nombre ??????????????????????????????? */
        if (strncmp(buf, "LOBBY_CREATE_ROOM:", 18) == 0) {
            const char* nombre = buf + 18;
            if (!strlen(nombre)) { send_line(sock, "ROOM_FAIL:nombre vacio"); continue; }

            pthread_mutex_lock(&g_state->lock);
            int slot = -1;
            for (int i = 0; i < MAX_ROOMS; i++) {
                if (!g_state->rooms[i].active) { slot = i; break; }
            }
            if (slot == -1) {
                pthread_mutex_unlock(&g_state->lock);
                send_line(sock, "ROOM_FAIL:maximo de rooms alcanzado");
                continue;
            }
            Room* r = &g_state->rooms[slot];
            memset(r, 0, sizeof(Room));
            r->id = slot + 1;
            r->active = 1;
            r->coordinator_id = user_id;
            r->members[0] = user_id;
            r->member_count = 1;
            strncpy(r->name, nombre, sizeof(r->name) - 1);
            int rid = r->id;
            g_state->room_count++;
            pthread_mutex_unlock(&g_state->lock);

            snprintf(resp, sizeof(resp), "ROOM_CREATED:%d", rid);
            send_line(sock, resp);

            /* Notificar a todos via UDP */
            char notif[BUFSIZE];
            snprintf(notif, sizeof(notif), "NOTIF_ROOM_CREATED:%d=%s", rid, nombre);
            pthread_mutex_lock(&g_state->lock);
            int uids[MAX_USERS]; int uc = 0;
            for (int i = 0; i < MAX_USERS; i++)
                if (g_state->users[i].active && g_state->users[i].id != user_id)
                    uids[uc++] = g_state->users[i].id;
            pthread_mutex_unlock(&g_state->lock);
            for (int i = 0; i < uc; i++) udp_notify(uids[i], notif);
            continue;
        }

        /* ?? LOBBY_JOIN_REQUEST:room_id ????????????????????????????? */
        if (strncmp(buf, "LOBBY_JOIN_REQUEST:", 19) == 0) {
            int rid = atoi(buf + 19);
            pthread_mutex_lock(&g_state->lock);
            Room* r = NULL;
            for (int i = 0; i < MAX_ROOMS; i++) {
                if (g_state->rooms[i].active && g_state->rooms[i].id == rid) {
                    r = &g_state->rooms[i];
                    break;
                }
            }
            if (!r) { pthread_mutex_unlock(&g_state->lock); send_line(sock, "ROOM_FAIL:room no existe"); continue; }
            if (es_miembro(user_id, rid)) { pthread_mutex_unlock(&g_state->lock); send_line(sock, "ROOM_FAIL:ya eres miembro"); continue; }
            if (r->pending_count >= MAX_PENDING) { pthread_mutex_unlock(&g_state->lock); send_line(sock, "ROOM_FAIL:cola llena"); continue; }
            r->pending[r->pending_count++] = user_id;
            int coord_id = r->coordinator_id;
            char uname[64];
            for (int i = 0; i < MAX_USERS; i++)
                if (g_state->users[i].id == user_id)
                {
                    strncpy(uname, g_state->users[i].username, sizeof(uname) - 1); break;
                }
            pthread_mutex_unlock(&g_state->lock);

            send_line(sock, "REQUEST_PENDING");

            /* Notificar al coordinador via UDP */
            char notif[BUFSIZE];
            snprintf(notif, sizeof(notif), "NOTIF_JOIN_REQUEST:%d:%d=%s", rid, user_id, uname);
            udp_notify(coord_id, notif);
            continue;
        }

        /* ?? COORD_ACCEPT:room_id:user_id ?????????????????????????? */
        if (strncmp(buf, "COORD_ACCEPT:", 13) == 0) {
            int rid, target_uid;
            if (sscanf(buf + 13, "%d:%d", &rid, &target_uid) != 2) {
                send_line(sock, "ACTION_FAIL:formato incorrecto"); continue;
            }
            pthread_mutex_lock(&g_state->lock);
            if (!es_coordinador(user_id, rid)) {
                pthread_mutex_unlock(&g_state->lock);
                send_line(sock, "ACTION_FAIL:no eres coordinador"); continue;
            }
            Room* r = &g_state->rooms[rid - 1];
            /* Quitar de pending */
            int found = 0;
            for (int i = 0; i < r->pending_count; i++) {
                if (r->pending[i] == target_uid) {
                    r->pending[i] = r->pending[--r->pending_count];
                    found = 1; break;
                }
            }
            if (!found) { pthread_mutex_unlock(&g_state->lock); send_line(sock, "ACTION_FAIL:solicitud no encontrada"); continue; }
            /* Agregar a miembros */
            r->members[r->member_count++] = target_uid;
            char uname[64] = "?";
            for (int i = 0; i < MAX_USERS; i++)
                if (g_state->users[i].id == target_uid)
                {
                    strncpy(uname, g_state->users[i].username, sizeof(uname) - 1); break;
                }
            pthread_mutex_unlock(&g_state->lock);

            send_line(sock, "ACTION_OK");

            /* Notificar al usuario aceptado */
            char notif[BUFSIZE];
            snprintf(notif, sizeof(notif), "NOTIF_ACCEPTED:%d", rid);
            udp_notify(target_uid, notif);

            /* Notificar a todos en la room */
            snprintf(notif, sizeof(notif), "NOTIF_USER_JOINED:%d:%s", rid, uname);
            udp_notify_room(rid, notif);
            continue;
        }

        /* ?? COORD_REJECT:room_id:user_id ?????????????????????????? */
        if (strncmp(buf, "COORD_REJECT:", 13) == 0) {
            int rid, target_uid;
            if (sscanf(buf + 13, "%d:%d", &rid, &target_uid) != 2) {
                send_line(sock, "ACTION_FAIL:formato incorrecto"); continue;
            }
            pthread_mutex_lock(&g_state->lock);
            if (!es_coordinador(user_id, rid)) {
                pthread_mutex_unlock(&g_state->lock);
                send_line(sock, "ACTION_FAIL:no eres coordinador"); continue;
            }
            Room* r = &g_state->rooms[rid - 1];
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

        /* ?? COORD_KICK:room_id:user_id ???????????????????????????? */
        if (strncmp(buf, "COORD_KICK:", 11) == 0) {
            int rid, target_uid;
            if (sscanf(buf + 11, "%d:%d", &rid, &target_uid) != 2) {
                send_line(sock, "ACTION_FAIL:formato incorrecto"); continue;
            }
            pthread_mutex_lock(&g_state->lock);
            if (!es_coordinador(user_id, rid)) {
                pthread_mutex_unlock(&g_state->lock);
                send_line(sock, "ACTION_FAIL:no eres coordinador"); continue;
            }
            Room* r = &g_state->rooms[rid - 1];
            int found = 0;
            for (int i = 0; i < r->member_count; i++) {
                if (r->members[i] == target_uid) {
                    r->members[i] = r->members[--r->member_count];
                    found = 1; break;
                }
            }
            char uname[64] = "?";
            for (int i = 0; i < MAX_USERS; i++)
                if (g_state->users[i].id == target_uid)
                {
                    strncpy(uname, g_state->users[i].username, sizeof(uname) - 1); break;
                }
            pthread_mutex_unlock(&g_state->lock);

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

        /* ?? COORD_INVITE:room_id:user_id ?????????????????????????? */
        if (strncmp(buf, "COORD_INVITE:", 13) == 0) {
            int rid, target_uid;
            if (sscanf(buf + 13, "%d:%d", &rid, &target_uid) != 2) {
                send_line(sock, "ACTION_FAIL:formato incorrecto"); continue;
            }
            pthread_mutex_lock(&g_state->lock);
            if (!es_coordinador(user_id, rid)) {
                pthread_mutex_unlock(&g_state->lock);
                send_line(sock, "ACTION_FAIL:no eres coordinador"); continue;
            }
            Room* r = &g_state->rooms[rid - 1];
            if (es_miembro(target_uid, rid)) {
                pthread_mutex_unlock(&g_state->lock);
                send_line(sock, "ACTION_FAIL:ya es miembro"); continue;
            }
            r->members[r->member_count++] = target_uid;
            char rname[64]; strncpy(rname, r->name, sizeof(rname) - 1);
            pthread_mutex_unlock(&g_state->lock);

            send_line(sock, "ACTION_OK");
            char notif[BUFSIZE];
            snprintf(notif, sizeof(notif), "NOTIF_INVITED:%d=%s", rid, rname);
            udp_notify(target_uid, notif);
            continue;
        }

        /* ?? COORD_DELETE_ROOM:room_id ????????????????????????????? */
        if (strncmp(buf, "COORD_DELETE_ROOM:", 18) == 0) {
            int rid = atoi(buf + 18);
            pthread_mutex_lock(&g_state->lock);
            if (!es_coordinador(user_id, rid)) {
                pthread_mutex_unlock(&g_state->lock);
                send_line(sock, "ACTION_FAIL:no eres coordinador"); continue;
            }
            Room* r = &g_state->rooms[rid - 1];
            if (r->member_count > 1) {
                pthread_mutex_unlock(&g_state->lock);
                send_line(sock, "ACTION_FAIL:la room no esta vacia");
                continue;
            }
            r->active = 0;
            pthread_mutex_unlock(&g_state->lock);

            send_line(sock, "ACTION_OK");
            char notif[BUFSIZE];
            snprintf(notif, sizeof(notif), "NOTIF_ROOM_DELETED:%d", rid);
            /* Notificar a todos */
            pthread_mutex_lock(&g_state->lock);
            int uids[MAX_USERS]; int uc = 0;
            for (int i = 0; i < MAX_USERS; i++)
                if (g_state->users[i].active)
                    uids[uc++] = g_state->users[i].id;
            pthread_mutex_unlock(&g_state->lock);
            for (int i = 0; i < uc; i++) udp_notify(uids[i], notif);
            continue;
        }

        /* ?? LOBBY_SET_NICK:nickname ???????????????????????????????? */
        if (strncmp(buf, "LOBBY_SET_NICK:", 15) == 0) {
            const char* nick = buf + 15;
            pthread_mutex_lock(&g_state->lock);
            for (int i = 0; i < MAX_USERS; i++) {
                if (g_state->users[i].id == user_id) {
                    strncpy(g_state->users[i].nickname, nick, sizeof(g_state->users[i].nickname) - 1);
                    break;
                }
            }
            pthread_mutex_unlock(&g_state->lock);
            send_line(sock, "NICK_OK");
            continue;
        }

        /* ?? Comando desconocido ???????????????????????????????????? */
        send_line(sock, "ERR_UNKNOWN_CMD");
    }
}

/* ??????????????????????????????????????????????????????????????????????????
   FUNCION DEL HIJO (corre despues del fork)
   ?????????????????????????????????????????????????????????????????????????? */

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

    /* Limpiar shared memory al salir */
    pthread_mutex_lock(&g_state->lock);
    for (int i = 0; i < MAX_USERS; i++) {
        if (g_state->users[i].id == uid) {
            g_state->users[i].active = 0;
            break;
        }
    }
    /* Quitar de todas las rooms */
    for (int i = 0; i < MAX_ROOMS; i++) {
        Room* r = &g_state->rooms[i];
        if (!r->active) continue;
        for (int j = 0; j < r->member_count; j++) {
            if (r->members[j] == uid) {
                r->members[j] = r->members[--r->member_count]; break;
            }
        }
    }
    pthread_mutex_unlock(&g_state->lock);

    /* Notificar desconexion */
    char notif[BUFSIZE];
    snprintf(notif, sizeof(notif), "NOTIF_USER_OFFLINE:%d=%s", uid, username);
    pthread_mutex_lock(&g_state->lock);
    int uids[MAX_USERS]; int uc = 0;
    for (int i = 0; i < MAX_USERS; i++)
        if (g_state->users[i].active)
            uids[uc++] = g_state->users[i].id;
    pthread_mutex_unlock(&g_state->lock);
    for (int i = 0; i < uc; i++) udp_notify(uids[i], notif);

    close(sock);
    printf("[Hijo uid=%d] Terminando\n", uid);
    exit(0);
}

/* ??????????????????????????????????????????????????????????????????????????
   HILO UDP — recoge notificaciones solicitadas por los hijos
   (En esta version simple el padre las envia directamente via udp_notify)
   El hilo UDP aqui solo sirve para recibir pings de hijos si usas un pipe.
   Por simplicidad lo dejamos como un oyente que imprime lo que llega.
   ?????????????????????????????????????????????????????????????????????????? */

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
            /* En el diseno actual los hijos llaman udp_notify() directamente
               usando el fd global g_udp_sd. Este hilo puede usarse en el futuro
               para recibir mensajes de control de hijos via UDP. */
            printf("[UDP] Recibido: %s", buf);
        }
    }
    return NULL;
}

/* ??????????????????????????????????????????????????????????????????????????
   SIGNAL HANDLERS
   ?????????????????????????????????????????????????????????????????????????? */

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

/* ??????????????????????????????????????????????????????????????????????????
   MAIN
   ?????????????????????????????????????????????????????????????????????????? */

int main(void) {
    /* ?? Shared memory ???????????????????????????????????????????????????? */
    g_state = mmap(NULL, sizeof(SharedState),
        PROT_READ | PROT_WRITE,
        MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (g_state == MAP_FAILED) { perror("mmap"); exit(1); }
    memset(g_state, 0, sizeof(SharedState));

    /* Mutex compartido entre procesos */
    pthread_mutexattr_t mattr;
    pthread_mutexattr_init(&mattr);
    pthread_mutexattr_setpshared(&mattr, PTHREAD_PROCESS_SHARED);
    pthread_mutex_init(&g_state->lock, &mattr);
    pthread_mutexattr_destroy(&mattr);

    /* ?? Socket UDP ??????????????????????????????????????????????????????? */
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

    /* ?? Hilo UDP ????????????????????????????????????????????????????????? */
    pthread_t tid;
    pthread_create(&tid, NULL, hilo_udp, NULL);
    pthread_detach(tid);

    /* ?? Socket TCP ??????????????????????????????????????????????????????? */
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

    /* ?? Signals ?????????????????????????????????????????????????????????? */
    signal(SIGCHLD, sig_chld);   /* recoger zombies automaticamente */
    signal(SIGINT, sig_int);

    printf("[Padre] Servidor listo — TCP:%d  UDP:%d\n", TCP_PORT, UDP_PORT);

    /* ?? Loop principal: accept() + fork() ???????????????????????????????? */
    while (1) {
        struct sockaddr_in client_addr;
        socklen_t clen = sizeof(client_addr);
        int client_fd = accept(g_tcp_sd, (struct sockaddr*)&client_addr, &clen);
        if (client_fd == -1) {
            perror("accept");
            continue;
        }

        char client_ip[INET_ADDRSTRLEN];
        inet_ntop(AF_INET, &client_addr.sin_addr, client_ip, sizeof(client_ip));
        printf("[Padre] Nueva conexion de %s — haciendo fork\n", client_ip);

        pid_t pid = fork();
        if (pid < 0) { perror("fork"); close(client_fd); continue; }

        if (pid == 0) {
            /* ?? HIJO ?? */
            close(g_tcp_sd);   /* hijo no necesita el socket de escucha */
            atender_cliente(client_fd, client_ip);
            /* atender_cliente llama exit(), no llega aqui */
        }

        /* ?? PADRE ?? */
        close(client_fd);   /* padre cede el socket al hijo */
    }

    return 0;
}