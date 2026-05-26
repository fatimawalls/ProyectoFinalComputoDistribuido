/*
 * chatServerJson.c — Servidor de chat (proxy al database_server)
 *
 * Arquitectura:
 * Cliente <──TCP:5006──> chatServerJson <──TCP:8080──> database_server
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

       /* DB host/puerto configurables por argv */
char g_db_host[256] = DB_HOST;
int  g_db_port = DB_PORT;

/* ============================================================
   BROADCAST UDP — notifica a toda la red que un usuario entró
   ============================================================ */
void broadcast_user_online(int user_id, const char* username)
{
    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) { perror("broadcast socket"); return; }

    int broadcastEnable = 1;
    setsockopt(sock, SOL_SOCKET, SO_BROADCAST, &broadcastEnable, sizeof(broadcastEnable));

    struct sockaddr_in broadcastAddr;
    memset(&broadcastAddr, 0, sizeof(broadcastAddr));
    broadcastAddr.sin_family = AF_INET;
    broadcastAddr.sin_port = htons(UDP_PORT);
    broadcastAddr.sin_addr.s_addr = inet_addr("255.255.255.255");

    char buffer[512];
    snprintf(buffer, sizeof(buffer),
        "{\"type\":\"USER_ONLINE\",\"userId\":%d,\"username\":\"%s\"}\n",
        user_id, username);

    sendto(sock, buffer, strlen(buffer), 0,
        (struct sockaddr*)&broadcastAddr, sizeof(broadcastAddr));
    LOG("[UDP BROADCAST] Notificando a la red: %s", buffer);
    close(sock);
}

/* ============================================================
   SHARED MEMORY — usuarios conectados (para UDP push)
   ============================================================ */
typedef struct {
    int  db_user_id;
    char username[64];
    int  active;
    char udp_ip[64];
    int  udp_port;
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
    int len = snprintf(buf, sizeof(buf), "%s\n", s);
    send(fd, buf, len, 0);
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
    int req_len = snprintf(req_buf, sizeof(req_buf), "%s\n", req_json);
    send(fd, req_buf, req_len, 0);

    int total = 0, lines = 0;
    char tmp[BUFSIZE];

    while (1) {
        int n = recv_line(fd, tmp, sizeof(tmp));
        if (n <= 0) {
            LOG("[DB-RESP] Fin de respuesta (EOF de DB)");
            break;
        }
        if (tmp[0] == '\0') continue;
        LOG("[DB-RESP] Línea recibida de DB: '%s'", tmp);
        int needed = strlen(tmp) + 2;
        if (total + needed >= out_size) {
            LOG("[DB-RESP] ALERTA: buffer de salida saturado");
            break;
        }
        total += snprintf(out_buf + total, out_size - total, "%s\n", tmp);
        lines++;
    }
    out_buf[total] = '\0';
    close(fd);
    LOG("[DB-RESP] Total: %d líneas del database_server", lines);
    return lines;
}

/* ============================================================
   UDP — push a usuario específico
   ============================================================ */
static void udp_notify_user(int db_user_id, const char* json_str)
{
    pthread_mutex_lock(&g_state->lock);
    for (int i = 0; i < MAX_USERS; i++) {
        ShmUser* u = &g_state->users[i];
        if (!u->active || u->db_user_id != db_user_id || u->udp_port == 0)
            continue;

        struct sockaddr_in dest;
        memset(&dest, 0, sizeof(dest));
        dest.sin_family = AF_INET;
        dest.sin_port = htons(u->udp_port);
        inet_aton(u->udp_ip, &dest.sin_addr);
        pthread_mutex_unlock(&g_state->lock);

        char buf[BUFSIZE];
        int len = snprintf(buf, sizeof(buf), "%s\n", json_str);
        sendto(g_udp_sd, buf, len, 0, (struct sockaddr*)&dest, sizeof(dest));
        LOG("[UDP] Push a uid=%d %s:%d", db_user_id, u->udp_ip, u->udp_port);
        return;
    }
    pthread_mutex_unlock(&g_state->lock);
}

static void udp_push_notify_users(const char* resp_json, int skip_id)
{
    cJSON* resp = cJSON_Parse(resp_json);
    if (!resp) {
        LOG("[UDP-ERR] No se pudo parsear JSON para notificación: '%s'", resp_json);
        return;
    }
    cJSON* arr = cJSON_GetObjectItem(resp, "notifyUsers");
    if (cJSON_IsArray(arr)) {
        cJSON* item = NULL;
        cJSON_ArrayForEach(item, arr) {
            int uid = item->valueint;
            if (uid != skip_id)
                udp_notify_user(uid, resp_json);
        }
    }
    cJSON_Delete(resp);
}

/* ============================================================
   SHARED MEMORY — registrar / eliminar usuario
   ============================================================ */
static void shm_register_user(int uid, const char* uname, const char* ip)
{
    pthread_mutex_lock(&g_state->lock);
    for (int i = 0; i < MAX_USERS; i++) {
        if (g_state->users[i].active && g_state->users[i].db_user_id == uid) {
            strncpy(g_state->users[i].udp_ip, ip, sizeof(g_state->users[i].udp_ip) - 1);
            pthread_mutex_unlock(&g_state->lock);
            return;
        }
    }
    for (int i = 0; i < MAX_USERS; i++) {
        if (!g_state->users[i].active) {
            ShmUser* su = &g_state->users[i];
            memset(su, 0, sizeof(ShmUser));
            su->db_user_id = uid;
            su->active = 1;
            su->udp_port = 0;
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
        if (n <= 0) {
            LOG("[HIJO-AUTH] Cliente desconectado en fase Auth");
            close(sock); exit(0);
        }
        LOG("[HIJO-AUTH] Recibido del Cliente: '%s'", req_buf);

        cJSON* req = cJSON_Parse(req_buf);
        if (!req) {
            LOG("[HIJO-AUTH-ERR] JSON inválido del cliente: '%s'", req_buf);
            continue;
        }
        cJSON* jtype = cJSON_GetObjectItem(req, "type");
        if (!cJSON_IsString(jtype)) {
            LOG("[HIJO-AUTH-ERR] JSON sin campo 'type'");
            cJSON_Delete(req); continue;
        }
        const char* type = jtype->valuestring;
        LOG("[HIJO-AUTH] Request tipo: %s", type);

        int lines = db_request(req_buf, resp_buf, sizeof(resp_buf));
        if (lines < 0) {
            LOG("[HIJO-AUTH-ERR] Fallo crítico con database_server");
            cJSON_Delete(req);
            close(sock); exit(1);
        }

        if (strcmp(type, "CREATE_ACCOUNT") == 0) {
            int create_ok = 0;
            char resp_copy[BUFSIZE];
            strncpy(resp_copy, resp_buf, sizeof(resp_copy) - 1);
            resp_copy[sizeof(resp_copy) - 1] = '\0';

            char* line = strtok(resp_copy, "\n");
            while (line) {
                if (line[0] != '\0') {
                    LOG("[HIJO-AUTH] Reenviando a cliente (CREATE_ACCOUNT_RESP): '%s'", line);
                    send_line(sock, line);

                    cJSON* j = cJSON_Parse(line);
                    if (j) {
                        cJSON* jsuccess = cJSON_GetObjectItem(j, "success");
                        if (cJSON_IsNumber(jsuccess) && jsuccess->valueint == 1) {
                            create_ok = 1;
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

            if (create_ok && uid > 0) {
                shm_register_user(uid, username, client_ip);
                LOG("[HIJO-CREATE-OK] Registro exitoso. uid=%d, usuario=%s", uid, username);
                broadcast_user_online(uid, username);
                /* Salir del bucle de auth para entrar a sesión */
                cJSON_Delete(req);
                break;
            }
            /* Si create_ok==0, uid sigue en -1 y el bucle continúa */
            uid = -1;
            cJSON_Delete(req);
            continue;
        }

        if (strcmp(type, "AUTH") == 0) {
            int auth_ok = 0;
            char resp_copy[BUFSIZE];
            strncpy(resp_copy, resp_buf, sizeof(resp_copy) - 1);
            resp_copy[sizeof(resp_copy) - 1] = '\0';

            char* line = strtok(resp_copy, "\n");
            while (line) {
                if (line[0] != '\0') {
                    LOG("[HIJO-AUTH] Enviando línea al cliente: '%s'", line);
                    send_line(sock, line);

                    cJSON* j = cJSON_Parse(line);
                    if (!j) {
                        LOG("[HIJO-AUTH-ALERTA] Línea enviada no es JSON: '%s'", line);
                    }
                    else {
                        cJSON* jt = cJSON_GetObjectItem(j, "type");
                        cJSON* js = cJSON_GetObjectItem(j, "success");
                        if (cJSON_IsString(jt) &&
                            strcmp(jt->valuestring, "AUTH_RESPONSE") == 0) {
                            LOG("[HIJO-AUTH] AUTH_RESPONSE detectado. success=%d",
                                cJSON_IsNumber(js) ? js->valueint : -1);
                            if (cJSON_IsNumber(js) && js->valueint) {
                                auth_ok = 1;
                                cJSON* ju = cJSON_GetObjectItem(j, "userId");
                                cJSON* jn = cJSON_GetObjectItem(j, "username");
                                uid = ju ? ju->valueint : -1;
                                strncpy(username, jn ? jn->valuestring : "",
                                    sizeof(username) - 1);
                            }
                        }
                        cJSON_Delete(j);
                    }
                }
                line = strtok(NULL, "\n");
            }

            if (auth_ok && uid > 0) {
                shm_register_user(uid, username, client_ip);
                LOG("[HIJO-AUTH-OK] Autenticación exitosa. uid=%d, usuario=%s", uid, username);
                broadcast_user_online(uid, username);
            }
            else {
                LOG("[HIJO-AUTH-FAIL] Autenticación rechazada. uid=%d", uid);
                uid = -1;
            }
            cJSON_Delete(req);
            continue;
        }

        LOG("[HIJO-AUTH] Tipo desconocido ignorado: %s", type);
        cJSON_Delete(req);
    }

    /* ── Fase 2: Sesión ──────────────────────────────────────── */
    LOG("[HIJO-SESION] Loop de comandos activo para uid=%d (%s)", uid, username);

    while (1) {
        int n = recv_line(sock, req_buf, sizeof(req_buf));
        if (n <= 0) {
            LOG("[HIJO-SESION] Cliente desconectado (uid=%d)", uid);
            break;
        }
        LOG("[HIJO-SESION] Request de uid=%d: '%s'", uid, req_buf);

        int lines = db_request(req_buf, resp_buf, sizeof(resp_buf));
        if (lines < 0) {
            LOG("[HIJO-SESION-ERR] Error de comunicación DB para uid=%d", uid);
            break;
        }

        char resp_copy[BUFSIZE];
        strncpy(resp_copy, resp_buf, sizeof(resp_copy) - 1);
        resp_copy[sizeof(resp_copy) - 1] = '\0';

        char* line = strtok(resp_copy, "\n");
        while (line) {
            if (line[0] != '\0') {
                LOG("[HIJO-SESION] Reenviando a cliente: '%s'", line);
                send_line(sock, line);

                cJSON* j = cJSON_Parse(line);
                if (j) {
                    cJSON* arr = cJSON_GetObjectItem(j, "notifyUsers");
                    if (cJSON_IsArray(arr))
                        udp_push_notify_users(line, uid);
                    cJSON_Delete(j);
                }
                else {
                    LOG("[HIJO-SESION-ALERTA] Línea no es JSON: '%s'", line);
                }
            }
            line = strtok(NULL, "\n");
        }
    }

    shm_unregister_user(uid);
    close(sock);
    LOG("[HIJO-CLIENTE] Finalizado. uid=%d", uid);
    exit(0);
}

/* ============================================================
   HILO UDP — escucha notificaciones entrantes
   ============================================================ */
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
        if (n > 0) { buf[n] = '\0'; LOG("[UDP-HILO] Mensaje entrante: %s", buf); }
    }
    return NULL;
}

/* ============================================================
   DB PING — verifica conectividad al arrancar
   ============================================================ */
static int db_ping(void)
{
    LOG("[DB-PING] Probando conexión a %s:%d ...", g_db_host, g_db_port);
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) { LOG("[DB-PING] ERROR: no se pudo crear socket"); return 0; }

    struct timeval tv = { .tv_sec = 3, .tv_usec = 0 };
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

    struct sockaddr_in db_addr;
    memset(&db_addr, 0, sizeof(db_addr));
    db_addr.sin_family = AF_INET;
    db_addr.sin_port = htons(g_db_port);
    inet_pton(AF_INET, g_db_host, &db_addr.sin_addr);

    if (connect(fd, (struct sockaddr*)&db_addr, sizeof(db_addr)) < 0) {
        perror("[DB-PING] connect");
        LOG("[DB-PING] FALLO — database_server NO alcanzable en %s:%d", g_db_host, g_db_port);
        close(fd);
        return 0;
    }

    close(fd);
    LOG("[DB-PING] OK — database_server alcanzable en %s:%d", g_db_host, g_db_port);
    return 1;
}

/* ============================================================
   SEÑALES
   ============================================================ */
static void sig_chld(int s) { (void)s; while (waitpid(-1, NULL, WNOHANG) > 0); }
static void sig_int(int s) {
    (void)s;
    LOG("[SIGNAL] Cierre controlado por SIGINT");
    if (g_tcp_sd != -1) close(g_tcp_sd);
    if (g_udp_sd != -1) close(g_udp_sd);
    exit(0);
}

/* ============================================================
   MAIN
   ============================================================ */
int main(int argc, char* argv[])
{
    /* Aceptar IP y puerto de la DB por argumento: ./chatServer [db_ip] [db_port] */
    if (argc > 1) strncpy(g_db_host, argv[1], sizeof(g_db_host) - 1);
    if (argc > 2) g_db_port = atoi(argv[2]);

    LOG("[PADRE] Configuración DB → %s:%d", g_db_host, g_db_port);

    g_state = mmap(NULL, sizeof(SharedState),
        PROT_READ | PROT_WRITE, MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (g_state == MAP_FAILED) { perror("mmap"); exit(1); }
    memset(g_state, 0, sizeof(SharedState));

    pthread_mutexattr_t mattr;
    pthread_mutexattr_init(&mattr);
    pthread_mutexattr_setpshared(&mattr, PTHREAD_PROCESS_SHARED);
    pthread_mutex_init(&g_state->lock, &mattr);
    pthread_mutexattr_destroy(&mattr);
    LOG("[PADRE] Memoria compartida inicializada");

    /* Socket UDP */
    g_udp_sd = socket(AF_INET, SOCK_DGRAM, 0);
    if (g_udp_sd < 0) { perror("udp socket"); exit(1); }
    struct sockaddr_in ua;
    memset(&ua, 0, sizeof(ua));
    ua.sin_family = AF_INET;
    ua.sin_addr.s_addr = INADDR_ANY;
    ua.sin_port = htons(UDP_PORT);
    if (bind(g_udp_sd, (struct sockaddr*)&ua, sizeof(ua)) < 0) {
        perror("udp bind"); exit(1);
    }
    pthread_t tid;
    pthread_create(&tid, NULL, hilo_udp, NULL);
    pthread_detach(tid);

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

    if (!db_ping()) {
        LOG("[PADRE] ADVERTENCIA: DB no alcanzable. El servidor esperará.");
    }

    /* Auto-detectar IP real del servidor */
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
    LOG(" Puerto UDP       : %d", UDP_PORT);
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
        if (pid == 0) {
            close(g_tcp_sd);
            atender_cliente(cfd, ip);
        }
        close(cfd);
    }
    return 0;
}