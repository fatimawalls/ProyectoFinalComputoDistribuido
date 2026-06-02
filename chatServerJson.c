/*
 * chatServerJson.c — Servidor de chat (proxy al database_server)


gcc chatServerJson.c database/libs/cJSON.c -Idatabase/libs -lpthread hiredis/libhiredis.a -o chatServerJson


 *
 * Arquitectura:
 * Cliente <──TCP:5006──> chatServerJson <──TCP:8080──> database_server
 *
 * CORRECCIÓN UDP:
 *   - shm_register_user() ahora acepta ip y port por separado.
 *   - En AUTH y CREATE_ACCOUNT, se leen "udpIp" y "udpPort" del JSON
 *     que el cliente Python envía, en lugar de usar la IP del socket TCP
 *     (que dentro de Docker NAT llega como 127.0.0.1).
 *   - El log de unicast ahora muestra cuántos clientes se notifican.
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
#include <errno.h>
#include "cJSON.h"
#include "hiredis/hiredis.h"

 /* ============================================================
    LOGGER
    ============================================================ */
#define LOG(fmt, ...) do { printf(fmt "\n", ##__VA_ARGS__); fflush(stdout); } while(0)

    /* ============================================================
       CONSTANTES
       ============================================================ */
#define TCP_PORT      5000
#define UDP_PORT      5001
#define DB_HOST       "172.18.2.3"
#define DB_PORT       8080
#define MAX_USERS     64
#define BUFSIZE       65536

#define redisIP       "10.7.2.119"
#define redisPORT     6379

char g_db_host[256] = DB_HOST;
int  g_db_port = DB_PORT;

/* Load Balancer reporting opcional.
   Uso:
      ./chatServerJson [db_ip] [db_port] [lb_ip] [lb_udp_port]

   Si lb_ip queda vacío, el server sigue funcionando normal y solo
   responde health checks TCP del load balancer.
*/
char g_lb_host[256] = "";
int  g_lb_udp_port = 4001;


/* ============================================================
   LOAD BALANCER — reportar connect/disconnect para least connections
   ============================================================ */
static void report_load_balancer(const char* event)
{
    if (g_lb_host[0] == '\0') {
        LOG("[LB-REPORT] SKIP — lb_host no configurado (pasa lb_ip como arg 3)");
        return;
    }

    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) {
        LOG("[LB-REPORT] ERROR — no se pudo crear socket UDP: %s", strerror(errno));
        return;
    }

    /* Bind al UDP_PORT fijo para que el LB vea src_port=5001 y pueda
       hacer coincidir el paquete con el ServerEntry correcto en su tabla */
    struct sockaddr_in local;
    memset(&local, 0, sizeof(local));
    local.sin_family = AF_INET;
    local.sin_addr.s_addr = INADDR_ANY;
    local.sin_port = htons(UDP_PORT);
    int reuse = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
    if (bind(fd, (struct sockaddr*)&local, sizeof(local)) < 0)
        LOG("[LB-REPORT] WARN — bind a UDP_PORT %d fallo (%s), usando efimero",
            UDP_PORT, strerror(errno));

    struct sockaddr_in lb;
    memset(&lb, 0, sizeof(lb));
    lb.sin_family = AF_INET;
    lb.sin_port = htons(g_lb_udp_port);
    if (inet_aton(g_lb_host, &lb.sin_addr) == 0) {
        LOG("[LB-REPORT] ERROR — IP del LB invalida: '%s'", g_lb_host);
        close(fd);
        return;
    }

    char payload[128];
    snprintf(payload, sizeof(payload),
        "{\"event\":\"%s\",\"port\":%d}", event, UDP_PORT);

    int sent = sendto(fd, payload, strlen(payload), 0,
        (struct sockaddr*)&lb, sizeof(lb));
    if (sent < 0)
        LOG("[LB-REPORT] ERROR — sendto fallo: %s", strerror(errno));
    else
        LOG("[LB-REPORT] OK — event=%s -> %s:%d payload=%s",
            event, g_lb_host, g_lb_udp_port, payload);

    close(fd);
}

static void* heartbeat_thread(void* arg)
{
    (void)arg;
    while (1) {
        sleep(5);
        if (g_lb_host[0] == '\0') continue;

        pthread_mutex_lock(&g_state->lock);
        int count = 0;
        for (int i = 0; i < MAX_USERS; i++)
            if (g_state->users[i].active) count++;
        pthread_mutex_unlock(&g_state->lock);

        int fd = socket(AF_INET, SOCK_DGRAM, 0);
        if (fd < 0) continue;
        int reuse = 1;
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
        struct sockaddr_in local;
        memset(&local, 0, sizeof(local));
        local.sin_family = AF_INET;
        local.sin_addr.s_addr = INADDR_ANY;
        local.sin_port = htons(UDP_PORT);
        bind(fd, (struct sockaddr*)&local, sizeof(local));

        struct sockaddr_in lb;
        memset(&lb, 0, sizeof(lb));
        lb.sin_family = AF_INET;
        lb.sin_port = htons(g_lb_udp_port);
        inet_aton(g_lb_host, &lb.sin_addr);

        char payload[128];
        snprintf(payload, sizeof(payload),
            "{\"event\":\"heartbeat\",\"port\":%d,\"connections\":%d}", UDP_PORT, count);
        sendto(fd, payload, strlen(payload), 0, (struct sockaddr*)&lb, sizeof(lb));
        close(fd);
        LOG("[HEARTBEAT] connections=%d -> %s:%d", count, g_lb_host, g_lb_udp_port);
    }
    return NULL;
}

/* ============================================================
   SHARED MEMORY — usuarios conectados
   ============================================================ */
typedef struct {
    int  db_user_id;
    char username[64];
    char nickname[64];
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
        if (n <= 0) return -1;   // -1 = EOF real o error (distinto de línea vacía)
        if (c == '\n') break;
        buf[total++] = c;
    }
    buf[total] = '\0';
    return total;              // 0 = línea vacía válida, >0 = mensaje normal
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
   ============================================================ */
static void udp_broadcast_all(const char* json_str, int skip_uid)
{
    char buf[BUFSIZE];
    int  len = snprintf(buf, sizeof(buf), "%s\n", json_str);

    /* Broadcast a 255.255.255.255 — fallback para redes sin NAT */
    {
        struct sockaddr_in bcast;
        memset(&bcast, 0, sizeof(bcast));
        bcast.sin_family = AF_INET;
        bcast.sin_port = htons(UDP_PORT);
        bcast.sin_addr.s_addr = inet_addr("255.255.255.255");
        sendto(g_udp_sd, buf, len, MSG_DONTWAIT,
            (struct sockaddr*)&bcast, sizeof(bcast));
        LOG("[UDP-BROADCAST] ✅ %d bytes → 255.255.255.255:%d  tipo=%s",
            len, UDP_PORT, json_str);
    }

    /* Unicast a cada cliente registrado con su IP y puerto real */
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

    LOG("[UDP] %d cliente(s) para notificar por unicast (skip uid=%d)", count, skip_uid);

    for (int i = 0; i < count; i++) {
        struct sockaddr_in dest;
        memset(&dest, 0, sizeof(dest));
        dest.sin_family = AF_INET;
        dest.sin_port = htons(active[i].udp_port);
        inet_aton(active[i].udp_ip, &dest.sin_addr);
        int r = sendto(g_udp_sd, buf, len, MSG_DONTWAIT,
            (struct sockaddr*)&dest, sizeof(dest));
        LOG("[UDP-UNICAST] ✅ %d bytes → uid=%d %s:%d",
            r, active[i].db_user_id, active[i].udp_ip, active[i].udp_port);
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


/* forward declaration — definida después del subscriber thread */
static int redis_is_user_online(int uid);

/* ============================================================
   FORWARD CHAT_USER — reenvía una línea al cliente inyectando
   el campo "online" si es un mensaje CHAT_USER.
   Para cualquier otro tipo lo reenvía sin modificar.
   ============================================================ */
static void forward_db_line(int sock, const char* line)
{
    cJSON* j = cJSON_Parse(line);
    if (!j) { send_line(sock, line); return; }

    cJSON* jtype = cJSON_GetObjectItem(j, "type");
    if (cJSON_IsString(jtype) && strcmp(jtype->valuestring, "CHAT_USER") == 0) {
        cJSON* jid = cJSON_GetObjectItem(j, "id");
        int is_online = 0;
        if (cJSON_IsNumber(jid)) {
            int uid = jid->valueint;
            /* Primero SHM local (rápido), luego Redis para usuarios en otros servers */
            pthread_mutex_lock(&g_state->lock);
            for (int i = 0; i < MAX_USERS; i++) {
                if (g_state->users[i].active && g_state->users[i].db_user_id == uid) {
                    is_online = 1;
                    break;
                }
            }
            pthread_mutex_unlock(&g_state->lock);
            if (!is_online)
                is_online = redis_is_user_online(uid);
        }
        cJSON_AddBoolToObject(j, "online", is_online);
        char* out = cJSON_PrintUnformatted(j);
        if (out) { send_line(sock, out); free(out); }
        else       send_line(sock, line);
        cJSON_Delete(j);
        return;
    }

    cJSON_Delete(j);
    send_line(sock, line);
}

/* ============================================================
   REDIS — gestión de usuarios online (cross-server)
   ============================================================ */
static void redis_user_online(int uid, const char* username, const char* nickname)
{
    redisContext* r = redisConnect(redisIP, redisPORT);
    if (!r || r->err) {
        LOG("[REDIS] Error marcando online uid=%d: %s", uid, r ? r->errstr : "OOM");
        if (r) redisFree(r);
        return;
    }
    redisReply* rep;
    rep = redisCommand(r, "SADD online_user_ids %d", uid);
    if (rep) freeReplyObject(rep);
    rep = redisCommand(r, "HSET online_users:%d username %s nickname %s",
                       uid, username, nickname[0] ? nickname : username);
    if (rep) freeReplyObject(rep);
    redisFree(r);
    LOG("[REDIS] uid=%d (%s) online en Redis", uid, username);
}

static void redis_user_offline(int uid)
{
    redisContext* r = redisConnect(redisIP, redisPORT);
    if (!r || r->err) {
        LOG("[REDIS] Error marcando offline uid=%d: %s", uid, r ? r->errstr : "OOM");
        if (r) redisFree(r);
        return;
    }
    redisReply* rep;
    rep = redisCommand(r, "SREM online_user_ids %d", uid);
    if (rep) freeReplyObject(rep);
    rep = redisCommand(r, "DEL online_users:%d", uid);
    if (rep) freeReplyObject(rep);
    redisFree(r);
    LOG("[REDIS] uid=%d offline en Redis", uid);
}

static int redis_is_user_online(int uid)
{
    redisContext* r = redisConnect(redisIP, redisPORT);
    if (!r || r->err) { if (r) redisFree(r); return 0; }
    redisReply* rep = redisCommand(r, "SISMEMBER online_user_ids %d", uid);
    int online = (rep && rep->type == REDIS_REPLY_INTEGER && rep->integer == 1);
    if (rep) freeReplyObject(rep);
    redisFree(r);
    return online;
}

/* ============================================================
   REDIS SUBSCRIBER — Escucha actualizaciones de otros servidores
   ============================================================ */
static void* redis_subscriber_thread(void* arg) {
    // Conectar al Redis central (cambia la IP si Redis está en otro contenedor/máquina)
    redisContext* sub = redisConnect(redisIP, redisPORT);
    if (!sub || sub->err) {
        LOG("[REDIS] Error al conectar el suscriptor: %s", sub ? sub->errstr : "OOM");
        return NULL;
    }

    LOG("[REDIS] Suscriptor conectado exitosamente. Escuchando 'chat_updates'...");
    redisCommand(sub, "SUBSCRIBE chat_updates");

    redisReply* reply;
    while (redisGetReply(sub, (void**)&reply) == REDIS_OK) {
        // hiredis devuelve arrays para los mensajes de Pub/Sub
        // reply->element[0] = "message"
        // reply->element[1] = nombre del canal ("chat_updates")
        // reply->element[2] = el contenido del mensaje (el JSON)
        if (reply->type == REDIS_REPLY_ARRAY && reply->elements == 3) {
            if (reply->element[2]->str) {
                LOG("[REDIS] Mensaje recibido de otro server. Repartiendo localmente...");
                // Usamos skip_uid = -1 para que le llegue a TODOS los locales
                udp_broadcast_all(reply->element[2]->str, -1);
            }
        }
        freeReplyObject(reply);
    }

    redisFree(sub);
    return NULL;
}

/* ============================================================
   on_data_change()
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

    if (!success) { cJSON_Delete(obj); return; }

    int broadcast = 0;

    if (strcmp(type, "NEW_MESSAGE_RESPONSE") == 0)    broadcast = 1;
    if (strcmp(type, "NEW_CHATROOM_RESPONSE") == 0)   broadcast = 1;
    if (strcmp(type, "ADD_USER_RESPONSE") == 0)        broadcast = 1;
    if (strcmp(type, "REMOVE_USER_RESPONSE") == 0)     broadcast = 1;
    if (strcmp(type, "DELETE_MESSAGE_RESPONSE") == 0)  broadcast = 1;
    if (strcmp(type, "DELETE_CHATROOM_RESPONSE") == 0) broadcast = 1;
    if (strcmp(type, "JOIN_REQUEST_RESPONSE") == 0)    broadcast = 1;
    if (strcmp(type, "REQUEST_RESPONSE") == 0)         broadcast = 1;
    if (strcmp(type, "DELETE_REQUEST_RESPONSE") == 0)  broadcast = 1;

    if (broadcast) {
        // 1. Notifica a los clientes locales de este servidor
        udp_broadcast_all(resp_json, sender_uid);

        // 2. NUEVO: Publica a todo el ecosistema vía Redis

        // 👇 AQUÍ ESTÁ LA CORRECCIÓN: Agregar "redisContext *pub = " 👇
        redisContext* pub = redisConnect(redisIP, redisPORT);

        if (pub && !pub->err) {
            redisReply* reply = redisCommand(pub, "PUBLISH chat_updates %s", resp_json);
            if (reply) freeReplyObject(reply);
            redisFree(pub);
        }
        else {
            LOG("[REDIS] Fallo al publicar el evento en Redis");
            if (pub) redisFree(pub);
        }
    }

    cJSON_Delete(obj);
}

/* ============================================================
   broadcast_user_online
   ============================================================ */
static void broadcast_user_online(int user_id, const char* username, const char* nickname)
{
    char buf[512];
    snprintf(buf, sizeof(buf),
        "{\"type\":\"USER_ONLINE\",\"userId\":%d,\"username\":\"%s\",\"nickname\":\"%s\"}",
        user_id, username, nickname[0] ? nickname : username);

    /* Registrar en Redis para que otros servidores lo vean */
    redis_user_online(user_id, username, nickname);

    /* Unicast a cada cliente registrado + broadcast fallback */
    udp_broadcast_all(buf, user_id);

    /* Publicar a Redis para que otros servidores notifiquen a sus clientes */
    redisContext* pub = redisConnect(redisIP, redisPORT);
    if (pub && !pub->err) {
        redisReply* reply = redisCommand(pub, "PUBLISH chat_updates %s", buf);
        if (reply) freeReplyObject(reply);
        redisFree(pub);
    } else {
        LOG("[REDIS] Fallo al publicar USER_ONLINE");
        if (pub) redisFree(pub);
    }

    LOG("[UDP BROADCAST USER_ONLINE] uid=%d username=%s", user_id, username);
}

/* ============================================================
   broadcast_user_offline
   ============================================================ */
static void broadcast_user_offline(int user_id, const char* username, const char* nickname)
{
    char buf[512];
    snprintf(buf, sizeof(buf),
        "{\"type\":\"USER_OFFLINE\",\"userId\":%d,\"username\":\"%s\",\"nickname\":\"%s\"}",
        user_id, username, nickname[0] ? nickname : username);

    /* Limpiar de Redis antes de notificar para que otros servers ya lo vean offline */
    redis_user_offline(user_id);

    udp_broadcast_all(buf, user_id);

    redisContext* pub = redisConnect(redisIP, redisPORT);
    if (pub && !pub->err) {
        redisReply* reply = redisCommand(pub, "PUBLISH chat_updates %s", buf);
        if (reply) freeReplyObject(reply);
        redisFree(pub);
    } else {
        LOG("[REDIS] Fallo al publicar USER_OFFLINE");
        if (pub) redisFree(pub);
    }

    LOG("[UDP BROADCAST USER_OFFLINE] uid=%d username=%s", user_id, username);
}

/* Envía USER_ONLINE por TCP al cliente recién conectado, uno por cada usuario activo
   en TODOS los servidores (consultando Redis). */
static void notify_existing_online_users(int sock, int skip_uid)
{
    redisContext* r = redisConnect(redisIP, redisPORT);
    if (!r || r->err) {
        LOG("[REDIS] No se pudo obtener usuarios online globales: %s", r ? r->errstr : "OOM");
        if (r) redisFree(r);
        return;
    }

    redisReply* members = redisCommand(r, "SMEMBERS online_user_ids");
    if (!members) { redisFree(r); return; }

    for (size_t i = 0; i < members->elements; i++) {
        int uid = atoi(members->element[i]->str);
        if (uid == skip_uid) continue;

        redisReply* info = redisCommand(r, "HGETALL online_users:%d", uid);
        if (!info) continue;

        char uname[64] = "";
        char nick[64]  = "";
        for (size_t j = 0; j + 1 < info->elements; j += 2) {
            if (strcmp(info->element[j]->str, "username") == 0)
                strncpy(uname, info->element[j+1]->str, sizeof(uname)-1);
            else if (strcmp(info->element[j]->str, "nickname") == 0)
                strncpy(nick,  info->element[j+1]->str, sizeof(nick)-1);
        }
        freeReplyObject(info);

        if (!uname[0]) continue;
        const char* display = nick[0] ? nick : uname;
        char buf[512];
        snprintf(buf, sizeof(buf),
            "{\"type\":\"USER_ONLINE\",\"userId\":%d,\"username\":\"%s\",\"nickname\":\"%s\"}",
            uid, uname, display);
        send_line(sock, buf);
        LOG("[TCP-NOTIFY-EXISTING] uid=%d %s (%s) -> sock=%d [Redis]",
            uid, uname, display, sock);
    }

    freeReplyObject(members);
    redisFree(r);
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
        if (n < 0) break;
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
   CORRECCIÓN: ahora recibe ip y port explícitamente en lugar
   de asumir siempre UDP_PORT. Esto permite usar el puerto
   efímero que el cliente Python reporta en el JSON de AUTH.
   ============================================================ */
static void shm_register_user(int uid, const char* uname, const char* nick,
                              const char* ip, int port)
{
    pthread_mutex_lock(&g_state->lock);
    /* Reconexión — actualizar nickname, IP y puerto */
    for (int i = 0; i < MAX_USERS; i++) {
        if (g_state->users[i].active && g_state->users[i].db_user_id == uid) {
            strncpy(g_state->users[i].udp_ip,  ip,   sizeof(g_state->users[i].udp_ip)  - 1);
            strncpy(g_state->users[i].nickname, nick, sizeof(g_state->users[i].nickname) - 1);
            g_state->users[i].udp_port = port;
            LOG("[SHM] Reconexión uid=%d ip=%s port=%d nick=%s", uid, ip, port, nick);
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
            su->active     = 1;
            su->udp_port   = port;
            strncpy(su->username, uname, sizeof(su->username) - 1);
            strncpy(su->nickname, nick,  sizeof(su->nickname) - 1);
            strncpy(su->udp_ip,   ip,    sizeof(su->udp_ip)   - 1);
            g_state->user_count++;
            LOG("[SHM] Registrado uid=%d username=%s nick=%s ip=%s port=%d slot=%d",
                uid, uname, nick, ip, port, i);
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
   HELPER — extraer udpIp y udpPort del JSON de AUTH/CREATE_ACCOUNT
   Devuelve la IP y puerto UDP que el cliente reportó.
   Si no vienen en el JSON, usa client_ip y UDP_PORT como fallback.
   ============================================================ */
static void extract_udp_info(cJSON* req, const char* client_ip,
    char* out_ip, int ip_size, int* out_port)
{
    cJSON* judp_ip = cJSON_GetObjectItem(req, "udpIp");
    cJSON* judp_port = cJSON_GetObjectItem(req, "udpPort");

    /* IP: usar la que el cliente reportó si viene y no es vacía */
    if (judp_ip && cJSON_IsString(judp_ip) && strlen(judp_ip->valuestring) > 3)
        strncpy(out_ip, judp_ip->valuestring, ip_size - 1);
    else
        strncpy(out_ip, client_ip, ip_size - 1);

    out_ip[ip_size - 1] = '\0';

    /* Puerto: usar el que el cliente reportó si viene y es válido */
    if (judp_port && cJSON_IsNumber(judp_port) && judp_port->valueint > 0)
        *out_port = judp_port->valueint;
    else
        *out_port = UDP_PORT;

    LOG("[UDP-INFO] Cliente reportó udpIp=%s udpPort=%d", out_ip, *out_port);
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
    char nickname[64] = "";

    LOG("[HIJO] Atendiendo cliente desde IP: %s", client_ip);

    /* ── Fase 1: Autenticación ───────────────────────────────── */
    while (uid < 0) {
        int n = recv_line(sock, req_buf, sizeof(req_buf));
        if (n < 0) { LOG("[HIJO-AUTH] Cliente desconectado"); close(sock); exit(0); }
        if (n == 0) continue; // línea vacía, ignorar
        LOG("[HIJO-AUTH] Recibido: '%s'", req_buf);

        cJSON* req = cJSON_Parse(req_buf);
        if (!req) continue;

        cJSON* jtype = cJSON_GetObjectItem(req, "type");
        if (!cJSON_IsString(jtype)) { cJSON_Delete(req); continue; }
        const char* type = jtype->valuestring;

        int lines = db_request(req_buf, resp_buf, sizeof(resp_buf));
        if (lines < 0) { cJSON_Delete(req); close(sock); exit(1); }

        /* ── CREATE_ACCOUNT ── */
        if (strcmp(type, "CREATE_ACCOUNT") == 0) {
            int ok = 0;
            char copy[BUFSIZE];
            strncpy(copy, resp_buf, sizeof(copy) - 1);
            char* line = strtok(copy, "\n");
            while (line) {
                if (line[0]) {
                    forward_db_line(sock, line);
                    cJSON* j = cJSON_Parse(line);
                    if (j) {
                        cJSON* js = cJSON_GetObjectItem(j, "success");
                        if (cJSON_IsNumber(js) && js->valueint) {
                            ok = 1;
                            cJSON* ju  = cJSON_GetObjectItem(j, "userId");
                            cJSON* jn  = cJSON_GetObjectItem(j, "username");
                            cJSON* jnk = cJSON_GetObjectItem(j, "nickname");
                            if (ju) uid = ju->valueint;
                            if (jn  && jn->valuestring)
                                strncpy(username, jn->valuestring,  sizeof(username) - 1);
                            if (jnk && jnk->valuestring)
                                strncpy(nickname, jnk->valuestring, sizeof(nickname) - 1);
                        }
                        cJSON_Delete(j);
                    }
                }
                line = strtok(NULL, "\n");
            }
            if (ok && uid > 0) {
                if (!nickname[0]) strncpy(nickname, username, sizeof(nickname) - 1);
                char reg_ip[64] = "";
                int  reg_port = UDP_PORT;
                extract_udp_info(req, client_ip, reg_ip, sizeof(reg_ip), &reg_port);
                shm_register_user(uid, username, nickname, reg_ip, reg_port);
                report_load_balancer("connect");
                LOG("[HIJO-CREATE-OK] uid=%d user=%s nick=%s udp=%s:%d",
                    uid, username, nickname, reg_ip, reg_port);
                broadcast_user_online(uid, username, nickname);
                notify_existing_online_users(sock, uid);
                cJSON_Delete(req);
                break;
            }
            uid = -1;
            cJSON_Delete(req);
            continue;
        }

        /* ── AUTH ── */
        if (strcmp(type, "AUTH") == 0) {
            int ok = 0;
            char copy[BUFSIZE];
            strncpy(copy, resp_buf, sizeof(copy) - 1);
            char* line = strtok(copy, "\n");
            while (line) {
                if (line[0]) {
                    forward_db_line(sock, line);
                    cJSON* j = cJSON_Parse(line);
                    if (j) {
                        cJSON* jt  = cJSON_GetObjectItem(j, "type");
                        cJSON* js  = cJSON_GetObjectItem(j, "success");
                        if (cJSON_IsString(jt) &&
                            strcmp(jt->valuestring, "AUTH_RESPONSE") == 0 &&
                            cJSON_IsNumber(js) && js->valueint) {
                            ok = 1;
                            cJSON* ju  = cJSON_GetObjectItem(j, "userId");
                            cJSON* jn  = cJSON_GetObjectItem(j, "username");
                            cJSON* jnk = cJSON_GetObjectItem(j, "nickname");
                            uid = ju ? ju->valueint : -1;
                            strncpy(username, jn  ? jn->valuestring  : "", sizeof(username) - 1);
                            if (jnk && jnk->valuestring)
                                strncpy(nickname, jnk->valuestring, sizeof(nickname) - 1);
                        }
                        cJSON_Delete(j);
                    }
                }
                line = strtok(NULL, "\n");
            }
            if (ok && uid > 0) {
                if (!nickname[0]) strncpy(nickname, username, sizeof(nickname) - 1);
                char reg_ip[64] = "";
                int  reg_port = UDP_PORT;
                extract_udp_info(req, client_ip, reg_ip, sizeof(reg_ip), &reg_port);
                shm_register_user(uid, username, nickname, reg_ip, reg_port);
                report_load_balancer("connect");
                LOG("[HIJO-AUTH-OK] uid=%d user=%s nick=%s udp=%s:%d",
                    uid, username, nickname, reg_ip, reg_port);
                broadcast_user_online(uid, username, nickname);
                notify_existing_online_users(sock, uid);
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
        if (n < 0) { LOG("[HIJO-SESION] Desconectado uid=%d", uid); break; }
        if (n == 0) continue; // línea vacía, ignorar
        LOG("[HIJO-SESION] uid=%d req: '%s'", uid, req_buf);

        int lines = db_request(req_buf, resp_buf, sizeof(resp_buf));
        if (lines < 0) { LOG("[HIJO-SESION-ERR] DB error uid=%d", uid); break; }

        char copy[BUFSIZE];
        strncpy(copy, resp_buf, sizeof(copy) - 1);
        copy[sizeof(copy) - 1] = '\0';

        char* line = strtok(copy, "\n");
        while (line) {
            if (line[0]) {
                LOG("[HIJO-SESION] → cliente uid=%d: '%s'", uid, line);
                send_line(sock, line);
                on_data_change(line, uid);
            }
            line = strtok(NULL, "\n");
        }
    }

    if (uid > 0) {
        broadcast_user_offline(uid, username, nickname);
        report_load_balancer("disconnect");
    }

    shm_unregister_user(uid);
    close(sock);
    LOG("[HIJO-CLIENTE] Finalizado uid=%d", uid);
    exit(0);
}

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
    if (argc > 3) strncpy(g_lb_host, argv[3], sizeof(g_lb_host) - 1);
    if (argc > 4) g_lb_udp_port = atoi(argv[4]);

    LOG("[PADRE] DB → %s:%d", g_db_host, g_db_port);
    if (g_lb_host[0] != '\0')
        LOG("[PADRE] Load Balancer reports → %s:%d", g_lb_host, g_lb_udp_port);
    else
        LOG("[PADRE] Load Balancer reports deshabilitados");

    g_state = mmap(NULL, sizeof(SharedState),
        PROT_READ | PROT_WRITE, MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (g_state == MAP_FAILED) { perror("mmap"); exit(1); }
    memset(g_state, 0, sizeof(SharedState));

    pthread_mutexattr_t mattr;
    pthread_mutexattr_init(&mattr);
    pthread_mutexattr_setpshared(&mattr, PTHREAD_PROCESS_SHARED);
    pthread_mutex_init(&g_state->lock, &mattr);
    pthread_mutexattr_destroy(&mattr);

    /* Socket UDP — envío de notificaciones a clientes */
    g_udp_sd = socket(AF_INET, SOCK_DGRAM, 0);
    if (g_udp_sd < 0) { perror("udp socket"); exit(1); }

    int bcast = 1;
    setsockopt(g_udp_sd, SOL_SOCKET, SO_BROADCAST, &bcast, sizeof(bcast));

    struct sockaddr_in ua;
    memset(&ua, 0, sizeof(ua));
    ua.sin_family = AF_INET;
    ua.sin_addr.s_addr = INADDR_ANY;
    ua.sin_port = 0;  /* puerto efímero */
    if (bind(g_udp_sd, (struct sockaddr*)&ua, sizeof(ua)) < 0) {
        perror("udp bind"); exit(1);
    }

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
    LOG(" LB reporting     : %s", g_lb_host[0] ? "ON" : "OFF");
    if (g_lb_host[0] != '\0')
        LOG(" LB destino       : %s:%d", g_lb_host, g_lb_udp_port);
    LOG("--------------------------------------------------");
    LOG(" CONFIGURA en loadBalancer.c g_servers_template:");
    LOG("   int_ip  = \"%s\"", realIP);
    LOG("   int_port= %d  (TCP)", TCP_PORT);
    LOG("   udp_port= %d  (debe coincidir con UDP_PORT)", UDP_PORT);
    LOG("==================================================");

    /* ============================================================
    LOOP PRINCIPAL DE CONEXIONES (en el main de chatServerJson.c
    ============================================================ */

    // Iniciar el hilo de Redis en segundo plano
    pthread_t t_redis;
    pthread_create(&t_redis, NULL, redis_subscriber_thread, NULL);
    pthread_detach(t_redis);

    pthread_t t_heartbeat;
    pthread_create(&t_heartbeat, NULL, heartbeat_thread, NULL);
    pthread_detach(t_heartbeat);

    while (1) {
        struct sockaddr_in ca;
        socklen_t clen = sizeof(ca);
        int cfd = accept(g_tcp_sd, (struct sockaddr*)&ca, &clen);
        if (cfd < 0) {
            if (errno == EINTR) continue;
            perror("accept");
            continue;
        }

        char client_ip[64] = "";
        strncpy(client_ip, inet_ntoa(ca.sin_addr), sizeof(client_ip) - 1);

        // Hacemos el fork de inmediato para no bloquear la atención de otros sockets
        pid_t pid = fork();
        if (pid == 0) {
            // ─────────────────────────────────────────────────────────────────
            // ─── DENTRO DEL PROCESO HIJO ─────────────────────────────────────
            // ─────────────────────────────────────────────────────────────────
            close(g_tcp_sd); // El hijo no necesita el socket de escucha general

            char peek_buf[16];
            memset(peek_buf, 0, sizeof(peek_buf));

            // "Espiamos" los primeros 12 bytes del socket sin consumirlos de la cola
            int pbytes = recv(cfd, peek_buf, 12, MSG_PEEK);
            if (pbytes > 0 && strncmp(peek_buf, "HEALTH_CHECK", 12) == 0) {
                // ¡Confirmado! Es el Load Balancer.
                char discard[32];
                printf("[HEALTHCHECK] -> Estado OK (Verificado por LB)\n"); fflush(stdout);
                recv(cfd, discard, sizeof(discard), 0); // Vaciamos el socket
                close(cfd);
                exit(0); // El hijo muere en SILENCIO ABSOLUTO (sin logs)
            }

            // ─────────────────────────────────────────────────────────────────
            // ─── SI NO ES UN HEALTH CHECK (ES UN CLIENTE REAL DE PYTHON) ─────
            // ─────────────────────────────────────────────────────────────────
            // Imprimimos el log del Padre (simulado desde el hijo) y procedemos
            printf("[PADRE] Nueva conexión TCP desde %s\n", client_ip);
            fflush(stdout);

            // Llamamos a la función normal para procesar el login/sesión
            atender_cliente(cfd, client_ip);
            exit(0);
        }

        // ─────────────────────────────────────────────────────────────────
        // ─── DENTRO DEL PROCESO PADRE GENERAL ────────────────────────────
        // ─────────────────────────────────────────────────────────────────
        close(cfd); // El padre cierra su copia del socket cliente y sigue escuchando
    }
}