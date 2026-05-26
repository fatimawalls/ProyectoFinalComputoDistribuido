/*
 * chatServerJson.c — Servidor de chat (proxy al database_server)
 *
 * Arquitectura:
 * Cliente <──TCP:5000──> chatServerJson <──TCP:8080──> database_server
 *
 * Versión con LOGS extendidos para depuración de respuestas JSON.
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
#define BUFSIZE       65536   /* grande: el sync puede ser largo */

       /* ============================================================
          SHARED MEMORY — usuarios conectados (para UDP push)
          ============================================================ */
typedef struct {
    int  db_user_id;
    char username[64];
    int  active;
    char udp_ip[64];
    int  udp_port;        /* 0 = sin UDP registrado aún */
} ShmUser;

typedef struct {
    ShmUser     users[MAX_USERS];
    int         user_count;
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
    LOG("[DB-REQ] Conectando a database_server en %s:%d...", DB_HOST, DB_PORT);
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) { perror("db socket"); return -1; }

    struct sockaddr_in db_addr;
    memset(&db_addr, 0, sizeof(db_addr));
    db_addr.sin_family = AF_INET;
    db_addr.sin_port = htons(DB_PORT);
    inet_pton(AF_INET, DB_HOST, &db_addr.sin_addr);

    if (connect(fd, (struct sockaddr*)&db_addr, sizeof(db_addr)) < 0) {
        perror("db connect");
        close(fd);
        return -1;
    }

    LOG("[DB-REQ] Enviando a DB: '%s'", req_json);
    char req_buf[BUFSIZE];
    int req_len = snprintf(req_buf, sizeof(req_buf), "%s\n", req_json);
    send(fd, req_buf, req_len, 0);

    int total = 0;
    int lines = 0;
    char tmp[BUFSIZE];

    while (1) {
        int n = recv_line(fd, tmp, sizeof(tmp));
        if (n <= 0) {
            LOG("[DB-RESP] Fin de respuesta (Socket cerrado por DB u orden EOF)");
            break;
        }
        if (tmp[0] == '\0') continue;

        LOG("[DB-RESP] Línea cruda recibida de DB: '%s'", tmp);

        /* Agregar al buffer de salida */
        int needed = strlen(tmp) + 2;
        if (total + needed >= out_size) {
            LOG("[DB-RESP] ¡ALERTA! Buffer de salida saturado");
            break;
        }
        total += snprintf(out_buf + total, out_size - total, "%s\n", tmp);
        lines++;
    }
    out_buf[total] = '\0';
    close(fd);

    LOG("[DB-RESP] Total: %d líneas consolidadas del database_server", lines);
    return lines;
}

/* ============================================================
   UDP — notificar a usuarios conectados
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
        LOG("[UDP-ERR] No se pudo parsear JSON para notificación UDP: '%s'", resp_json);
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
   REGISTRAR / LIMPIAR USUARIO EN SHARED MEMORY
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
            LOG("[HIJO-AUTH] Cliente desconectado abruptamente en fase Auth");
            close(sock); exit(0);
        }
        LOG("[HIJO-AUTH] Recibido del Cliente: '%s'", req_buf);

        /* Validar estructura JSON */
        cJSON* req = cJSON_Parse(req_buf);
        if (!req) {
            LOG("[HIJO-AUTH-ERR] El cliente envió algo que NO es JSON válido: '%s'", req_buf);
            continue;
        }
        cJSON* jtype = cJSON_GetObjectItem(req, "type");
        if (!cJSON_IsString(jtype)) {
            LOG("[HIJO-AUTH-ERR] JSON del cliente no contiene campo 'type' string");
            cJSON_Delete(req); continue;
        }
        const char* type = jtype->valuestring;
        LOG("[HIJO-AUTH] Request tipo: %s", type);

        /* Petición al Database Server */
        int lines = db_request(req_buf, resp_buf, sizeof(resp_buf));
        if (lines < 0) {
            LOG("[HIJO-AUTH-ERR] Fallo crítico al comunicarse con el database_server");
            cJSON_Delete(req);
            close(sock); exit(1);
        }

        if (strcmp(type, "CREATE_ACCOUNT") == 0) {
            char* line = strtok(resp_buf, "\n");
            while (line) {
                LOG("[HIJO-AUTH] Reenviando a cliente (CREATE_ACCOUNT_RESP): '%s'", line);
                send_line(sock, line);
                line = strtok(NULL, "\n");
            }
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
                    LOG("[HIJO-AUTH] Enviando línea de respuesta al cliente: '%s'", line);
                    send_line(sock, line);

                    /* Validar si la línea que le mandamos es JSON */
                    cJSON* j = cJSON_Parse(line);
                    if (!j) {
                        LOG("[HIJO-AUTH-ALERTA] ¡CUIDADO! La línea enviada NO es un JSON parseable. Contenido: '%s'", line);
                    }
                    else {
                        cJSON* jt = cJSON_GetObjectItem(j, "type");
                        cJSON* js = cJSON_GetObjectItem(j, "success");
                        if (cJSON_IsString(jt) && strcmp(jt->valuestring, "AUTH_RESPONSE") == 0) {
                            LOG("[HIJO-AUTH] Detectado AUTH_RESPONSE. success=%d", cJSON_IsNumber(js) ? js->valueint : -1);
                            if (cJSON_IsNumber(js) && js->valueint) {
                                auth_ok = 1;
                                cJSON* ju = cJSON_GetObjectItem(j, "userId");
                                cJSON* jn = cJSON_GetObjectItem(j, "username");
                                uid = ju ? ju->valueint : -1;
                                strncpy(username, jn ? jn->valuestring : "", sizeof(username) - 1);
                            }
                        }
                        cJSON_Delete(j);
                    }
                }
                line = strtok(NULL, "\n");
            }

            if (auth_ok && uid > 0) {
                shm_register_user(uid, username, client_ip);
                LOG("[HIJO-AUTH-OK] Autenticación Exitosa. uid=%d, usuario=%s", uid, username);
            }
            else {
                LOG("[HIJO-AUTH-FAIL] Autenticación rechazada o incompleta. uid obtenido=%d", uid);
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
                    if (cJSON_IsArray(arr)) {
                        udp_push_notify_users(line, uid);
                    }
                    cJSON_Delete(j);
                }
                else {
                    LOG("[HIJO-SESION-ALERTA] Línea de sesión enviada no es JSON: '%s'", line);
                }
            }
            line = strtok(NULL, "\n");
        }
    }

    shm_unregister_user(uid);
    close(sock);
    LOG("[HIJO-CLIENTE] Finalizado por completo. uid=%d", uid);
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
    LOG("[UDP-HILO] Escuchando activamente en puerto %d", UDP_PORT);
    while (1) {
        int n = recvfrom(g_udp_sd, buf, sizeof(buf) - 1, 0,
            (struct sockaddr*)&src, &slen);
        if (n > 0) { buf[n] = '\0'; LOG("[UDP-HILO] Mensaje entrante: %s", buf); }
    }
    return NULL;
}

/* ============================================================
   DB PING — verifica conectividad con database_server al arrancar
   ============================================================ */
static int db_ping(void)
{
    LOG("[DB-PING] Probando conexión a %s:%d ...", DB_HOST, DB_PORT);
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        LOG("[DB-PING] ERROR: no se pudo crear socket de prueba");
        return 0;
    }

    /* Timeout de 3 segundos para el intento de conexión */
    struct timeval tv = { .tv_sec = 3, .tv_usec = 0 };
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

    struct sockaddr_in db_addr;
    memset(&db_addr, 0, sizeof(db_addr));
    db_addr.sin_family = AF_INET;
    db_addr.sin_port = htons(DB_PORT);
    inet_pton(AF_INET, DB_HOST, &db_addr.sin_addr);

    if (connect(fd, (struct sockaddr*)&db_addr, sizeof(db_addr)) < 0) {
        perror("[DB-PING] connect");
        LOG("[DB-PING] ✗ FALLO — database_server NO alcanzable en %s:%d", DB_HOST, DB_PORT);
        close(fd);
        return 0;
    }

    close(fd);
    LOG("[DB-PING] ✓ OK — database_server alcanzable en %s:%d", DB_HOST, DB_PORT);
    return 1;
}

/* ============================================================
   SEÑALES
   ============================================================ */
static void sig_chld(int s) { (void)s; while (waitpid(-1, NULL, WNOHANG) > 0); }
static void sig_int(int s) {
    (void)s;
    LOG("[SIGNAL] Cierre por SIGINT controlado");
    if (g_tcp_sd != -1) close(g_tcp_sd);
    if (g_udp_sd != -1) close(g_udp_sd);
    exit(0);
}

/* ============================================================
   MAIN
   ============================================================ */
int main(void)
{
    LOG("[PADRE] Iniciando Proxy ChatServer. Apuntando a DB en %s:%d", DB_HOST, DB_PORT);

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

    /* Verificar conectividad con la DB antes de aceptar clientes */
    if (!db_ping()) {
        LOG("[PADRE] ADVERTENCIA: no se pudo conectar a la DB en este momento.");
        LOG("[PADRE] El servidor seguirá corriendo pero los clientes fallarán hasta que la DB esté disponible.");
    }

    LOG("[PADRE] Servidor escuchando en TCP:%d y listo para enviar UDP:%d", TCP_PORT, UDP_PORT);

    while (1) {
        struct sockaddr_in ca;
        socklen_t clen = sizeof(ca);
        int cfd = accept(g_tcp_sd, (struct sockaddr*)&ca, &clen);
        if (cfd < 0) { perror("accept"); continue; }

        char ip[INET_ADDRSTRLEN];
        inet_ntop(AF_INET, &ca.sin_addr, ip, sizeof(ip));
        LOG("[PADRE] Nueva conexión entrante desde TCP %s", ip);

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