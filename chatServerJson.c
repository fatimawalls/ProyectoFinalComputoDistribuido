/*
 * chatServerJson.c — Servidor de chat (proxy al database_server)
 *
 * Arquitectura:
 * Cliente <──TCP:5006──> chatServerJson <──TCP:8080──> database_server
 *
 * CAMBIOS onDataChange:
 *   - on_data_change(): detecta el tipo de respuesta y hace broadcast UDP
 *     a TODOS los clientes conectados (no solo al solicitante).
 *   - Los tipos cubiertos:
 *       NEW_MESSAGE_RESPONSE, NEW_CHATROOM_RESPONSE,
 *       ADD_USER_RESPONSE, REMOVE_USER_RESPONSE,
 *       DELETE_MESSAGE_RESPONSE, DELETE_CHATROOM_RESPONSE,
 *       CREATE_ACCOUNT_RESPONSE, JOIN_REQUEST_RESPONSE
 *   - USER_ONLINE sigue usando su propio broadcast independiente.
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
#include <ifaddrs.h>
#include <errno.h>   // para MSG_DONTWAIT

#include "cJSON.h"

 /* ============================================================
    LOGGER
    ============================================================ */
#define LOG(fmt, ...)                    \
    do {                                 \
        printf(fmt "\n", ##__VA_ARGS__); \
        fflush(stdout);                  \
    } while (0)

    /* ============================================================
       CONSTANTES
       ============================================================ */
#define TCP_PORT      5006
#define UDP_PORT      5001
#define DB_HOST       "172.18.2.3"
#define DB_PORT       8080
#define MAX_USERS     64
#define BUFSIZE       65536

char g_db_host[256] = DB_HOST;
int  g_db_port = DB_PORT;

/* ============================================================
   SHARED MEMORY — usuarios conectados
   ============================================================ */
typedef struct {
    int  db_user_id;
    char username[64];
    int  active;
    char udp_ip[64];
    int  udp_port;   /* 0 = desconocido, se llena desde la IP del TCP */
} ShmUser;

typedef struct {
    ShmUser         users[MAX_USERS];
    int             user_count;
    pthread_mutex_t lock;
} SharedState;

static SharedState* g_state = NULL;
static int          g_tcp_sd = -1;
static int          g_udp_sd = -1;

/* ============================================================
   RED — leer/enviar línea terminada en '\n'
   ============================================================ */
static int recv_line(int fd, char* buf, int maxlen)
{
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

static void send_line(int fd, const char* s)
{
    char buf[BUFSIZE];
    int  len = snprintf(buf, sizeof(buf), "%s\n", s);
    send(fd, buf, len, 0);
}

/* ============================================================
   UDP — enviar datagrama a una dirección específica
   ============================================================ */
static void udp_send_to(const char* ip, int port, const char* json_str)
{
    struct sockaddr_in dest;
    memset(&dest, 0, sizeof(dest));
    dest.sin_family = AF_INET;
    dest.sin_port = htons(port);
    inet_aton(ip, &dest.sin_addr);

    char buf[BUFSIZE];
    int  len = snprintf(buf, sizeof(buf), "%s\n", json_str);
    sendto(g_udp_sd, buf, len, 0,
        (struct sockaddr*)&dest, sizeof(dest));
}

/* ============================================================
   UDP BROADCAST — notifica a TODOS los clientes activos
   (copia la lista bajo mutex y envía sin retenerlo, con MSG_DONTWAIT)
   ============================================================ */
static void udp_broadcast_all(const char* json_str, int skip_uid)
{
    // 1. Copiar usuarios activos bajo protección
    pthread_mutex_lock(&g_state->lock);
    ShmUser active[MAX_USERS];
    int count = 0;
    for (int i = 0; i < MAX_USERS; i++) {
        ShmUser* u = &g_state->users[i];
        if (u->active && u->db_user_id != skip_uid &&
            u->udp_ip[0] != '\0' && u->udp_port > 0)
        {
            active[count++] = *u;
        }
    }
    pthread_mutex_unlock(&g_state->lock);

    // 2. Enviar sin retener el mutex
    for (int i = 0; i < count; i++) {
        struct sockaddr_in dest;
        memset(&dest, 0, sizeof(dest));
        dest.sin_family = AF_INET;
        dest.sin_port = htons(active[i].udp_port);
        inet_aton(active[i].udp_ip, &dest.sin_addr);

        char buf[BUFSIZE];
        int  len = snprintf(buf, sizeof(buf), "%s\n", json_str);
        sendto(g_udp_sd, buf, len, MSG_DONTWAIT,
            (struct sockaddr*)&dest, sizeof(dest));

        LOG("[UDP-BROADCAST] → uid=%d %s:%d  %s",
            active[i].db_user_id, active[i].udp_ip, active[i].udp_port, json_str);
    }
}

/* ============================================================
   UDP — push a usuario específico por db_user_id
   ============================================================ */
static void udp_notify_user(int db_user_id, const char* json_str)
{
    pthread_mutex_lock(&g_state->lock);
    for (int i = 0; i < MAX_USERS; i++) {
        ShmUser* u = &g_state->users[i];
        if (!u->active || u->db_user_id != db_user_id || u->udp_ip[0] == '\0')
            continue;

        int port = (u->udp_port > 0) ? u->udp_port : UDP_PORT;
        pthread_mutex_unlock(&g_state->lock);
        udp_send_to(u->udp_ip, port, json_str);
        LOG("[UDP-USER] uid=%d %s:%d", db_user_id, u->udp_ip, port);
        return;
    }
    pthread_mutex_unlock(&g_state->lock);
}

/* ============================================================
   on_data_change()

   Se llama después de que el database_server responde a cualquier
   comando mutante. Detecta el tipo de respuesta y hace broadcast
   UDP a todos los clientes afectados para que actualicen su
   local_DB.

   Parámetro:
     resp_json : línea JSON ya procesada (una sola línea)
     sender_uid: uid del cliente que hizo la petición original
                 (lo excluye del broadcast si él ya recibió la
                  respuesta por TCP directo)
   ============================================================ */
static void on_data_change(const char* resp_json, int sender_uid)
{
    cJSON* obj = cJSON_Parse(resp_json);
    if (!obj) return;

    cJSON* jtype = cJSON_GetObjectItem(obj, "type");
    cJSON* jsuccess = cJSON_GetObjectItem(obj, "success");

    if (!cJSON_IsString(jtype)) { cJSON_Delete(obj); return; }

    const char* type = jtype->valuestring;
    int         success = cJSON_IsNumber(jsuccess) ? jsuccess->valueint : 0;

    LOG("[ON_DATA_CHANGE] tipo=%s success=%d", type, success);

    /* Solo propagamos respuestas exitosas de operaciones que
       modifican estado.  La AUTH_RESPONSE y CREATE_ACCOUNT_RESPONSE
       se manejan por separado (USER_ONLINE broadcast). */

    if (!success) { cJSON_Delete(obj); return; }

    /* ---- Tipos que deben sincronizarse en todos los clientes ---- */

    int broadcast = 0;

    if (strcmp(type, "NEW_MESSAGE_RESPONSE") == 0)    broadcast = 1;
    if (strcmp(type, "NEW_CHATROOM_RESPONSE") == 0)   broadcast = 1;
    if (strcmp(type, "ADD_USER_RESPONSE") == 0)        broadcast = 1;
    if (strcmp(type, "REMOVE_USER_RESPONSE") == 0)     broadcast = 1;
    if (strcmp(type, "DELETE_MESSAGE_RESPONSE") == 0)  broadcast = 1;
    if (strcmp(type, "DELETE_CHATROOM_RESPONSE") == 0) broadcast = 1;
    if (strcmp(type, "JOIN_REQUEST_RESPONSE") == 0)    broadcast = 1;
    if (strcmp(type, "REQUEST_RESPONSE") == 0)         broadcast = 1;  // ← add
    if (strcmp(type, "DELETE_REQUEST_RESPONSE") == 0)  broadcast = 1;  // ← add

    if (broadcast) {
        /* Extraemos la lista de notifyUsers si viene en el JSON.
           Si viene, solo notificamos a esos usuarios.
           Si no viene, hacemos broadcast a todos. */

        cJSON* notify_arr = cJSON_GetObjectItem(obj, "notifyUsers");

        if (cJSON_IsArray(notify_arr) && cJSON_GetArraySize(notify_arr) > 0) {
            cJSON* item = NULL;
            cJSON_ArrayForEach(item, notify_arr) {
                int uid = item->valueint;
                if (uid == sender_uid) continue; /* ya recibió por TCP */
                udp_notify_user(uid, resp_json);
            }
        }
        else {
            /* Sin lista explícita → todos los conectados */
            udp_broadcast_all(resp_json, sender_uid);
        }
    }

    cJSON_Delete(obj);
}

/* ============================================================
   broadcast_user_online — igual que antes, para USER_ONLINE
   ============================================================ */
static void broadcast_user_online(int user_id, const char* username)
{
    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) { perror("broadcast socket"); return; }

    int on = 1;
    setsockopt(sock, SOL_SOCKET, SO_BROADCAST, &on, sizeof(on));

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(UDP_PORT);
    addr.sin_addr.s_addr = inet_addr("255.255.255.255");

    char buf[512];
    snprintf(buf, sizeof(buf),
        "{\"type\":\"USER_ONLINE\",\"userId\":%d,\"username\":\"%s\"}\n",
        user_id, username);
    sendto(sock, buf, strlen(buf), 0,
        (struct sockaddr*)&addr, sizeof(addr));
    LOG("[UDP BROADCAST USER_ONLINE] uid=%d username=%s", user_id, username);
    close(sock);
}

/* ============================================================
   DATABASE SERVER — conexión de un solo request
   ============================================================ */
static int db_request(const char* req_json, char* out_buf, int out_size)
{
    LOG("[DB-REQ] Conectando a database_server en %s:%d...", g_db_host, g_db_port);
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) { perror("db socket"); return -1; }

    struct sockaddr_in db_addr;
    memset(&db_addr, 0, sizeof(db_addr));
    db_addr.sin_family = AF_INET;
    db_addr.sin_port = htons(g_db_port);
    inet_pton(AF_INET, g_db_host, &db_addr.sin_addr);

    if (connect(fd, (struct sockaddr*)&db_addr, sizeof(db_addr)) < 0) {
        perror("db connect");
        close(fd);
        return -1;
    }

    LOG("[DB-REQ] Enviando a DB: '%s'", req_json);
    char req_buf[BUFSIZE];
    int  req_len = snprintf(req_buf, sizeof(req_buf), "%s\n", req_json);
    send(fd, req_buf, req_len, 0);

    int   total = 0, lines = 0;
    char  tmp[BUFSIZE];
    while (1) {
        int n = recv_line(fd, tmp, sizeof(tmp));
        if (n <= 0) break;
        if (tmp[0] == '\0') continue;
        LOG("[DB-RESP] Línea recibida de DB: '%s'", tmp);
        int needed = strlen(tmp) + 2;
        if (total + needed >= out_size) { LOG("[DB-RESP] buffer saturado"); break; }
        total += snprintf(out_buf + total, out_size - total, "%s\n", tmp);
        lines++;
    }
    out_buf[total] = '\0';
    close(fd);
    LOG("[DB-RESP] Total: %d líneas del database_server", lines);
    return lines;
}

/* ============================================================
   SHARED MEMORY — registrar / eliminar usuario
   ============================================================ */
static void shm_register_user(int uid, const char* uname, const char* ip)
{
    pthread_mutex_lock(&g_state->lock);
    /* Si el usuario ya existe (reconexión) */
    for (int i = 0; i < MAX_USERS; i++) {
        if (g_state->users[i].active && g_state->users[i].db_user_id == uid) {
            strncpy(g_state->users[i].udp_ip, ip, sizeof(g_state->users[i].udp_ip) - 1);
            g_state->users[i].udp_port = UDP_PORT;   // ← CAMBIO 1: actualizar puerto en reconexión
            pthread_mutex_unlock(&g_state->lock);
            return;
        }
    }
    /* Slot nuevo */
    for (int i = 0; i < MAX_USERS; i++) {
        if (!g_state->users[i].active) {
            ShmUser* su = &g_state->users[i];
            memset(su, 0, sizeof(ShmUser));
            su->db_user_id = uid;
            su->active = 1;
            su->udp_port = UDP_PORT;               // ← CAMBIO 1: antes era 0
            strncpy(su->username, uname, sizeof(su->username) - 1);
            strncpy(su->udp_ip, ip, sizeof(su->udp_ip) - 1);
            g_state->user_count++;
            LOG("[SHM] Registrado uid=%d username=%s ip=%s slot=%d", uid, uname, ip, i);
            break;
        }
    }
    pthread_mutex_unlock(&g_state->lock);
}

static void shm_unregister_user(int uid)
{
    pthread_mutex_lock(&g_state->lock);
    for (int i = 0; i < MAX_USERS; i++) {
        if (g_state->users[i].active && g_state->users[i].db_user_id == uid) {
            memset(&g_state->users[i], 0, sizeof(ShmUser));
            g_state->user_count--;
            LOG("[SHM] Eliminado uid=%d", uid);
            break;
        }
    }
    pthread_mutex_unlock(&g_state->lock);
}

/* ============================================================
   LÓGICA DEL CLIENTE — proceso hijo
   ============================================================ */
static void atender_cliente(int sock, const char* client_ip)
{
    char req_buf[BUFSIZE];
    char resp_buf[BUFSIZE];
    int  uid = -1;
    char username[64] = "";

    LOG("[HIJO] Atendiendo cliente desde IP: %s", client_ip);

    /* ── Fase 1: Autenticación ───────────────────────────────── */
    while (uid < 0) {
        int n = recv_line(sock, req_buf, sizeof(req_buf));
        if (n <= 0) { LOG("[HIJO-AUTH] Cliente desconectado"); close(sock); exit(0); }
        LOG("[HIJO-AUTH] Recibido: '%s'", req_buf);

        cJSON* req = cJSON_Parse(req_buf);
        if (!req) continue;

        cJSON* jtype = cJSON_GetObjectItem(req, "type");
        if (!cJSON_IsString(jtype)) { cJSON_Delete(req); continue; }
        const char* type = jtype->valuestring;

        int lines = db_request(req_buf, resp_buf, sizeof(resp_buf));
        if (lines < 0) { cJSON_Delete(req); close(sock); exit(1); }

        if (strcmp(type, "CREATE_ACCOUNT") == 0) {
            int ok = 0;
            char copy[BUFSIZE];
            strncpy(copy, resp_buf, sizeof(copy) - 1);
            char* line = strtok(copy, "\n");
            while (line) {
                if (line[0]) {
                    send_line(sock, line);
                    cJSON* j = cJSON_Parse(line);
                    if (j) {
                        cJSON* js = cJSON_GetObjectItem(j, "success");
                        if (cJSON_IsNumber(js) && js->valueint) {
                            ok = 1;
                            cJSON* ju = cJSON_GetObjectItem(j, "userId");
                            cJSON* jn = cJSON_GetObjectItem(j, "username");
                            if (ju) uid = ju->valueint;
                            if (jn && jn->valuestring)
                                strncpy(username, jn->valuestring, sizeof(username) - 1);
                        }
                        cJSON_Delete(j);
                    }
                }
                line = strtok(NULL, "\n");
            }
            if (ok && uid > 0) {
                shm_register_user(uid, username, client_ip);
                LOG("[HIJO-CREATE-OK] uid=%d user=%s", uid, username);
                broadcast_user_online(uid, username);
                cJSON_Delete(req);
                break;
            }
            uid = -1;
            cJSON_Delete(req);
            continue;
        }

        if (strcmp(type, "AUTH") == 0) {
            int ok = 0;
            char copy[BUFSIZE];
            strncpy(copy, resp_buf, sizeof(copy) - 1);
            char* line = strtok(copy, "\n");
            while (line) {
                if (line[0]) {
                    send_line(sock, line);
                    cJSON* j = cJSON_Parse(line);
                    if (j) {
                        cJSON* jt = cJSON_GetObjectItem(j, "type");
                        cJSON* js = cJSON_GetObjectItem(j, "success");
                        if (cJSON_IsString(jt) &&
                            strcmp(jt->valuestring, "AUTH_RESPONSE") == 0 &&
                            cJSON_IsNumber(js) && js->valueint) {
                            ok = 1;
                            cJSON* ju = cJSON_GetObjectItem(j, "userId");
                            cJSON* jn = cJSON_GetObjectItem(j, "username");
                            uid = ju ? ju->valueint : -1;
                            strncpy(username, jn ? jn->valuestring : "",
                                sizeof(username) - 1);
                        }
                        cJSON_Delete(j);
                    }
                }
                line = strtok(NULL, "\n");
            }
            if (ok && uid > 0) {
                shm_register_user(uid, username, client_ip);
                LOG("[HIJO-AUTH-OK] uid=%d user=%s", uid, username);
                broadcast_user_online(uid, username);
            }
            else {
                uid = -1;
            }
            cJSON_Delete(req);
            continue;
        }

        LOG("[HIJO-AUTH] Tipo desconocido ignorado: %s", type);
        cJSON_Delete(req);
    }

    /* ── Fase 2: Sesión ──────────────────────────────────────── */
    LOG("[HIJO-SESION] Loop activo uid=%d (%s)", uid, username);

    while (1) {
        int n = recv_line(sock, req_buf, sizeof(req_buf));
        if (n <= 0) { LOG("[HIJO-SESION] Desconectado uid=%d", uid); break; }
        LOG("[HIJO-SESION] uid=%d req: '%s'", uid, req_buf);

        int lines = db_request(req_buf, resp_buf, sizeof(resp_buf));
        if (lines < 0) { LOG("[HIJO-SESION-ERR] DB error uid=%d", uid); break; }

        char copy[BUFSIZE];
        strncpy(copy, resp_buf, sizeof(copy) - 1);
        copy[sizeof(copy) - 1] = '\0';

        char* line = strtok(copy, "\n");
        while (line) {
            if (line[0]) {
                /* 1. Reenviar al cliente que hizo la petición */
                LOG("[HIJO-SESION] → cliente uid=%d: '%s'", uid, line);
                send_line(sock, line);

                /* 2. on_data_change: notificar a los demás vía UDP */
                on_data_change(line, uid);
            }
            line = strtok(NULL, "\n");
        }
    }

    shm_unregister_user(uid);
    close(sock);
    LOG("[HIJO-CLIENTE] Finalizado uid=%d", uid);
    exit(0);
}

/* ============================================================
   HILO UDP — (opcional, ahora comentado en main)
   ============================================================ */
   /*
   static void* hilo_udp(void* arg)
   {
       (void)arg;
       char buf[BUFSIZE];
       struct sockaddr_in src;
       socklen_t slen = sizeof(src);
       LOG("[UDP-HILO] Escuchando en puerto %d", UDP_PORT);
       while (1) {
           int n = recvfrom(g_udp_sd, buf, sizeof(buf) - 1, 0,
               (struct sockaddr*)&src, &slen);
           if (n > 0) { buf[n] = '\0'; LOG("[UDP-HILO] Entrante: %s", buf); }
       }
       return NULL;
   }
   */

   /* ============================================================
      DB PING
      ============================================================ */
static int db_ping(void)
{
    LOG("[DB-PING] Probando %s:%d ...", g_db_host, g_db_port);
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return 0;
    struct timeval tv = { .tv_sec = 3, .tv_usec = 0 };
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
    struct sockaddr_in a;
    memset(&a, 0, sizeof(a));
    a.sin_family = AF_INET;
    a.sin_port = htons(g_db_port);
    inet_pton(AF_INET, g_db_host, &a.sin_addr);
    if (connect(fd, (struct sockaddr*)&a, sizeof(a)) < 0) {
        perror("[DB-PING] connect");
        close(fd); return 0;
    }
    close(fd);
    LOG("[DB-PING] OK");
    return 1;
}

/* ============================================================
   SEÑALES
   ============================================================ */
static void sig_chld(int s) { (void)s; while (waitpid(-1, NULL, WNOHANG) > 0); }
static void sig_int(int s) {
    (void)s;
    LOG("[SIGNAL] Cierre controlado");
    if (g_tcp_sd != -1) close(g_tcp_sd);
    if (g_udp_sd != -1) close(g_udp_sd);
    exit(0);
}

/* ============================================================
   MAIN
   ============================================================ */
int main(int argc, char* argv[])
{
    if (argc > 1) strncpy(g_db_host, argv[1], sizeof(g_db_host) - 1);
    if (argc > 2) g_db_port = atoi(argv[2]);
    LOG("[PADRE] DB → %s:%d", g_db_host, g_db_port);

    g_state = mmap(NULL, sizeof(SharedState),
        PROT_READ | PROT_WRITE, MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (g_state == MAP_FAILED) { perror("mmap"); exit(1); }
    memset(g_state, 0, sizeof(SharedState));

    pthread_mutexattr_t mattr;
    pthread_mutexattr_init(&mattr);
    pthread_mutexattr_setpshared(&mattr, PTHREAD_PROCESS_SHARED);
    pthread_mutex_init(&g_state->lock, &mattr);
    pthread_mutexattr_destroy(&mattr);

    /* Socket UDP — solo para envío, no necesita puerto fijo */
    g_udp_sd = socket(AF_INET, SOCK_DGRAM, 0);
    if (g_udp_sd < 0) { perror("udp socket"); exit(1); }

    /* Bind a puerto 0 → el SO asigna uno efímero, sin conflictos */
    struct sockaddr_in ua;
    memset(&ua, 0, sizeof(ua));
    ua.sin_family = AF_INET;
    ua.sin_addr.s_addr = INADDR_ANY;
    ua.sin_port = 0;   // ← CAMBIO 2: antes era htons(UDP_PORT)
    if (bind(g_udp_sd, (struct sockaddr*)&ua, sizeof(ua)) < 0) {
        perror("udp bind"); exit(1);
    }

    /* El hilo de escucha UDP ya no es necesario (solo imprimía logs).
       Lo comentamos para liberar el puerto 5001 y evitar conflictos. */
       // pthread_t tid;
       // pthread_create(&tid, NULL, hilo_udp, NULL);
       // pthread_detach(tid);

       /* Socket TCP */
    g_tcp_sd = socket(AF_INET, SOCK_STREAM, 0);
    if (g_tcp_sd < 0) { perror("tcp socket"); exit(1); }
    int opt = 1;
    setsockopt(g_tcp_sd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
    struct sockaddr_in ta;
    memset(&ta, 0, sizeof(ta));
    ta.sin_family = AF_INET;
    ta.sin_addr.s_addr = INADDR_ANY;
    ta.sin_port = htons(TCP_PORT);
    if (bind(g_tcp_sd, (struct sockaddr*)&ta, sizeof(ta)) < 0) {
        perror("tcp bind"); exit(1);
    }
    if (listen(g_tcp_sd, 10) < 0) { perror("listen"); exit(1); }

    signal(SIGCHLD, sig_chld);
    signal(SIGINT, sig_int);

    if (!db_ping())
        LOG("[PADRE] ADVERTENCIA: DB no alcanzable");

    /* Auto-detectar IP real */
    char realIP[64] = "0.0.0.0";
    struct ifaddrs* interfaces = NULL;
    if (getifaddrs(&interfaces) == 0) {
        for (struct ifaddrs* ifa = interfaces; ifa; ifa = ifa->ifa_next) {
            if (ifa->ifa_addr && ifa->ifa_addr->sa_family == AF_INET) {
                char* ip = inet_ntoa(((struct sockaddr_in*)ifa->ifa_addr)->sin_addr);
                if (strcmp(ip, "127.0.0.1") != 0) { strncpy(realIP, ip, 63); break; }
            }
        }
        freeifaddrs(interfaces);
    }

    LOG("==================================================");
    LOG(" CHAT SERVER INICIADO");
    LOG(" IP del servidor  : %s", realIP);
    LOG(" Puerto TCP       : %d", TCP_PORT);
    LOG(" Puerto UDP       : %d  (onDataChange broadcast)", UDP_PORT);
    LOG(" Database         : %s:%d", g_db_host, g_db_port);
    LOG("==================================================");

    while (1) {
        struct sockaddr_in ca;
        socklen_t clen = sizeof(ca);
        int cfd = accept(g_tcp_sd, (struct sockaddr*)&ca, &clen);
        if (cfd < 0) { perror("accept"); continue; }

        char ip[INET_ADDRSTRLEN];
        inet_ntop(AF_INET, &ca.sin_addr, ip, sizeof(ip));
        LOG("[PADRE] Nueva conexión TCP desde %s", ip);

        pid_t pid = fork();
        if (pid < 0) { perror("fork"); close(cfd); continue; }
        if (pid == 0) { close(g_tcp_sd); atender_cliente(cfd, ip); }
        close(cfd);
    }
    return 0;
}