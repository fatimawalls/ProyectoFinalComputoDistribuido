/*
 * loadBalancer.c — Load Balancer (Smart Redirect + Least Connections)
 *

gcc loadBalancer.c cJSON.c -o loadbalancer -lpthread


 * Arquitectura:
 *   Cliente ──TCP:LB_PORT──> LB ──JSON──> {"ip":"...","port":...}
 *   Cliente ──TCP──────────────────────────────────> ChatServer (directo)
 *
 *   ChatServer ──UDP:LB_UDP_PORT──> LB {"event":"connect"|"disconnect","port":XXXX}
 *
 * CONFIGURACIÓN — solo tocar la sección SERVERS y los defines de puertos
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
#include <sys/mman.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <ifaddrs.h>
#include <errno.h>

#include "cJSON.h"
#include <limits.h>

 /* ============================================================
    LOGGER
    ============================================================ */
#define LOG(fmt, ...) do { printf(fmt "\n", ##__VA_ARGS__); fflush(stdout); } while(0)

    /* ============================================================
       PUERTOS DEL LOAD BALANCER
       — LB_TCP_PORT : puerto donde escucha clientes (exterior del container)
       — LB_UDP_PORT : puerto donde escucha reportes de ChatServers
       ============================================================ */
#define LB_TCP_PORT   4000   /* ← CAMBIAR si necesitas otro puerto TCP  */
#define LB_UDP_PORT   4005   /* ← CAMBIAR si necesitas otro puerto UDP  */

       /* ============================================================
          LISTA DE CHAT SERVERS — HARDCODED
          Agrega/quita entradas según los compañeros disponibles.
          "ext_ip"  : IP pública/host de la laptop del compañero
          "ext_port": puerto exterior del container (el que expone Docker)
          "int_port": puerto interior del container (para identificar reportes UDP)
          ============================================================ */
typedef struct {
    char int_ip[64];   /* IP interna de Docker (ej: "172.18.2.2") */
    int  int_port;     /* Puerto TCP interno de Docker (ej: 5006) */
    char ext_ip[64];   /* IP externa que usará Windows (ej: "127.0.0.1") */
    int  ext_port;     /* Puerto externo expuesto en Windows (ej: 5015) */
    int  udp_port;     /* Puerto interior para reportes UDP (ej: 5001) */
    int  connections;  /* Conexiones activas (shared memory) */
    int  alive;        /* 1=alcanzable, 0=caído              */
} ServerEntry;

/* ── CONFIGURACIÓN MIXTA: CON SERVIDORES INTERNOS (DOCKER) Y EXTERNOS (LAN) ── */
static ServerEntry g_servers_template[] = {
    /* { IP_Docker, Port_Docker, IP_Windows, Port_Windows, Port_UDP, conn, alive } */

    /* 1. Tu servidor local dentro de Docker (Mapeo 5015:5006) */
    { "10.7.6.242", 5003, "10.7.6.242", 5003, 5001, 0, 1 },
    { "10.7.1.30", 5006, "10.7.1.30", 5006, 5001, 0, 1 }
};

#define SERVER_COUNT (int)(sizeof(g_servers_template) / sizeof(g_servers_template[0]))

/* ============================================================
   SHARED MEMORY — tabla de servers compartida entre procesos
   ============================================================ */
typedef struct {
    ServerEntry     servers[16];
    int             count;
    pthread_mutex_t lock;
} SharedState;

static SharedState* g_state = NULL;
static int          g_tcp_sd = -1;
static int          g_udp_sd = -1;

/* ============================================================
   LEAST CONNECTIONS — elige el server con menos conexiones activo
   ============================================================ */
static int pick_server(void)
{
    pthread_mutex_lock(&g_state->lock);

    int best_idx = -1;
    int best_conn = INT_MAX;

    LOG("[PICK] Evaluando servidores para seleccion:");
    for (int i = 0; i < g_state->count; i++) {
        ServerEntry* s = &g_state->servers[i];
        LOG("[PICK]   [%d] %s:%d alive=%d connections=%d",
            i, s->ext_ip, s->ext_port, s->alive, s->connections);
        if (!s->alive) continue;
        if (s->connections < best_conn) {
            best_conn = s->connections;
            best_idx = i;
        }
    }

    if (best_idx >= 0)
        LOG("[PICK] -> Elegido server[%d] %s:%d con %d conexiones",
            best_idx,
            g_state->servers[best_idx].ext_ip,
            g_state->servers[best_idx].ext_port,
            best_conn);
    else
        LOG("[PICK] -> Ningun server disponible");

    pthread_mutex_unlock(&g_state->lock);
    return best_idx;
}

/* ============================================================
   HEALTH CHECK — prueba TCP a un server (timeout 2s)
   ============================================================ */
static int is_reachable(const char* ip, int port)
{
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return 0;

    struct timeval tv = { .tv_sec = 2, .tv_usec = 0 };
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    inet_pton(AF_INET, ip, &addr.sin_addr);

    int ok = (connect(fd, (struct sockaddr*)&addr, sizeof(addr)) == 0);

    // ── NUEVA LÍNEA: Si la conexión fue exitosa, enviamos el identificador ──
    if (ok) {
        send(fd, "HEALTH_CHECK\n", 13, 0);
    }

    close(fd);
    return ok;
}

/* ============================================================
   HILO HEALTH CHECK — corre cada 10s, marca alive/dead
   ============================================================ */
static void* health_thread(void* arg)
{
    (void)arg;
    while (1) {
        sleep(10);
        pthread_mutex_lock(&g_state->lock);

        LOG("[HEALTH] === Estado actual de servidores ===");
        for (int i = 0; i < g_state->count; i++) {
            ServerEntry* s = &g_state->servers[i];
            int prev = s->alive;

            s->alive = is_reachable(s->int_ip, s->int_port);

            if (prev != s->alive) {
                LOG("[HEALTH] %s:%d -> %s", s->int_ip, s->int_port, s->alive ? "UP" : "DOWN");

                if (!s->alive) {
                    s->connections = 0;
                    LOG("[HEALTH] Servidor caido. Reseteando conexiones a 0 para %s:%d", s->int_ip, s->int_port);
                }
            }
            LOG("[HEALTH]   [%d] %s:%d alive=%d connections=%d",
                i, s->int_ip, s->int_port, s->alive, s->connections);
        }
        LOG("[HEALTH] =====================================");
        pthread_mutex_unlock(&g_state->lock);
    }
    return NULL;
}

/* ============================================================
   HILO UDP — recibe reportes connect/disconnect de ChatServers
   {"event":"connect"|"disconnect","port":<int_port>}
   ============================================================ */
static void* udp_thread(void* arg)
{
    (void)arg;
    char buf[1024];
    struct sockaddr_in src;
    socklen_t slen = sizeof(src);

    LOG("[UDP] Escuchando reportes en puerto %d", LB_UDP_PORT);

    while (1) {
        int n = recvfrom(g_udp_sd, buf, sizeof(buf) - 1, 0,
            (struct sockaddr*)&src, &slen);
        if (n <= 0) continue;
        buf[n] = '\0';

        cJSON* obj = cJSON_Parse(buf);
        if (!obj) continue;

        cJSON* jevent = cJSON_GetObjectItem(obj, "event");
        cJSON* jport = cJSON_GetObjectItem(obj, "port");

        if (!cJSON_IsString(jevent) || !cJSON_IsNumber(jport)) {
            cJSON_Delete(obj);
            continue;
        }

        const char* event = jevent->valuestring;
        int         int_port = jport->valueint;
        char        src_ip[64];
        inet_ntop(AF_INET, &src.sin_addr, src_ip, sizeof(src_ip));

        LOG("[UDP-RAW] Paquete recibido de IP=%s payload='%s'", src_ip, buf);
        LOG("[UDP-RAW] event='%s' port=%d", event, int_port);

        pthread_mutex_lock(&g_state->lock);

        /* Debug: mostrar tabla de servers conocidos */
        LOG("[UDP-MATCH] Buscando server... (total=%d)", g_state->count);
        for (int i = 0; i < g_state->count; i++) {
            ServerEntry* s = &g_state->servers[i];
            LOG("[UDP-MATCH]   [%d] int_ip=%s udp_port=%d alive=%d conn=%d",
                i, s->int_ip, s->udp_port, s->alive, s->connections);
        }

        int matched = 0;
        for (int i = 0; i < g_state->count; i++) {
            ServerEntry* s = &g_state->servers[i];

            /* Intento 1: coincidencia exacta IP + puerto */
            int ip_match = (strcmp(s->int_ip, src_ip) == 0);
            int port_match = (s->udp_port == int_port);

            LOG("[UDP-MATCH]   [%d] ip_match=%d port_match=%d (src=%s:%d vs reg=%s:%d)",
                i, ip_match, port_match, src_ip, int_port, s->int_ip, s->udp_port);

            /* Intento 2: si la IP no coincide, acepta sólo por puerto
               (útil cuando Docker NAT cambia la IP origen) */
            if (!ip_match && port_match) {
                LOG("[UDP-FALLBACK] IP no coincide (%s vs %s) pero puerto sí (%d). Aceptando por puerto.",
                    src_ip, s->int_ip, int_port);
            }

            if (!port_match)
                continue;   /* puerto distinto → definitivamente no es éste */

            if (!ip_match)
                LOG("[UDP-WARN] Usando fallback por puerto — verifica int_ip del server [%d]", i);

            matched = 1;
            if (strcmp(event, "connect") == 0) {
                s->connections++;
                LOG("[UDP] connect  %s:%d → server[%d] conexiones=%d",
                    src_ip, int_port, i, s->connections);
            }
            else if (strcmp(event, "disconnect") == 0) {
                if (s->connections > 0) s->connections--;
                LOG("[UDP] disconnect %s:%d → server[%d] conexiones=%d",
                    src_ip, int_port, i, s->connections);
            }
            break;
        }

        if (!matched)
            LOG("[UDP-WARN] Paquete de %s:%d NO coincide con ningún server registrado — revisa int_ip/udp_port",
                src_ip, int_port);

        pthread_mutex_unlock(&g_state->lock);
        cJSON_Delete(obj);
    }
    return NULL;
}

/* ============================================================
   PROCESO HIJO — atiende un cliente, responde JSON y cierra
   ============================================================ */
static void atender_cliente(int sock)
{
    int idx = pick_server();
    if (idx < 0) {
        const char* err = "{\"success\":0,\"error\":\"No hay servidores disponibles\"}\n";
        send(sock, err, strlen(err), 0);
        close(sock);
        exit(0);
    }

    pthread_mutex_lock(&g_state->lock);
    ServerEntry s = g_state->servers[idx];
    pthread_mutex_unlock(&g_state->lock);

    /* Envia al cliente de Python la IP externa y el puerto mapeado en el Host (5015) */
    char resp[256];
    snprintf(resp, sizeof(resp),
        "{\"success\":1,\"ip\":\"%s\",\"port\":%d}\n",
        s.ext_ip, s.ext_port);

    send(sock, resp, strlen(resp), 0);
    close(sock);

    LOG("[HIJO] Cliente redirigido → %s:%d (conexiones=%d)",
        s.ext_ip, s.ext_port, s.connections);
    exit(0);
}

/* ============================================================
   SEÑALES
   ============================================================ */
static void sig_chld(int s) { (void)s; while (waitpid(-1, NULL, WNOHANG) > 0); }
static void sig_int(int s) {
    (void)s;
    LOG("[LB] Cerrando...");
    if (g_tcp_sd >= 0) close(g_tcp_sd);
    if (g_udp_sd >= 0) close(g_udp_sd);
    exit(0);
}

/* ============================================================
   MAIN
   ============================================================ */
int main(void)
{
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

    /* Copiar lista hardcoded a shared memory */
    g_state->count = SERVER_COUNT;
    for (int i = 0; i < SERVER_COUNT; i++)
        g_state->servers[i] = g_servers_template[i];

    /* Socket UDP — escucha reportes de ChatServers */
    g_udp_sd = socket(AF_INET, SOCK_DGRAM, 0);
    if (g_udp_sd < 0) { perror("udp socket"); exit(1); }
    int reuse = 1;
    setsockopt(g_udp_sd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
    struct sockaddr_in ua;
    memset(&ua, 0, sizeof(ua));
    ua.sin_family = AF_INET;
    ua.sin_addr.s_addr = INADDR_ANY;
    ua.sin_port = htons(LB_UDP_PORT);
    if (bind(g_udp_sd, (struct sockaddr*)&ua, sizeof(ua)) < 0) {
        perror("udp bind"); exit(1);
    }

    /* Socket TCP — escucha clientes */
    g_tcp_sd = socket(AF_INET, SOCK_STREAM, 0);
    if (g_tcp_sd < 0) { perror("tcp socket"); exit(1); }
    int opt = 1;
    setsockopt(g_tcp_sd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
    struct sockaddr_in ta;
    memset(&ta, 0, sizeof(ta));
    ta.sin_family = AF_INET;
    ta.sin_addr.s_addr = INADDR_ANY;
    ta.sin_port = htons(LB_TCP_PORT);
    if (bind(g_tcp_sd, (struct sockaddr*)&ta, sizeof(ta)) < 0) {
        perror("tcp bind"); exit(1);
    }
    if (listen(g_tcp_sd, 20) < 0) { perror("listen"); exit(1); }

    /* Hilos */
    pthread_t t_udp, t_health;
    pthread_create(&t_udp, NULL, udp_thread, NULL);
    pthread_create(&t_health, NULL, health_thread, NULL);
    pthread_detach(t_udp);
    pthread_detach(t_health);

    signal(SIGCHLD, sig_chld);
    signal(SIGINT, sig_int);

    /* Health check inicial */
    LOG("[LB] Verificando servers al inicio...");
    pthread_mutex_lock(&g_state->lock);
    for (int i = 0; i < g_state->count; i++) {
        ServerEntry* s = &g_state->servers[i];

        // CAMBIO: Probar vida internamente
        s->alive = is_reachable(s->int_ip, s->int_port);

        LOG("  [%d] Interno: %s:%d | Cliente usará: %s:%d → %s",
            i, s->int_ip, s->int_port, s->ext_ip, s->ext_port, s->alive ? "UP" : "DOWN");
    }
    pthread_mutex_unlock(&g_state->lock);

    /* ------------------------------------------------------------
       OBTENER IP REAL DEL LOAD BALANCER
       ------------------------------------------------------------ */
    char realIP[64] = "0.0.0.0";
    struct ifaddrs* interfaces = NULL;
    if (getifaddrs(&interfaces) == 0) {
        for (struct ifaddrs* ifa = interfaces; ifa; ifa = ifa->ifa_next) {
            if (ifa->ifa_addr && ifa->ifa_addr->sa_family == AF_INET) {
                char* ip = inet_ntoa(((struct sockaddr_in*)ifa->ifa_addr)->sin_addr);
                // Ignoramos localhost para obtener la IP de la red Docker/Local
                if (strcmp(ip, "127.0.0.1") != 0) {
                    strncpy(realIP, ip, 63);
                    break;
                }
            }
        }
        freeifaddrs(interfaces);
    }

    /* ------------------------------------------------------------
       HEADER / ENCABEZADO EN CONSOLA
       ------------------------------------------------------------ */
    LOG("==================================================");
    LOG(" LOAD BALANCER INICIADO");
    LOG(" IP del Balanceador    : %s", realIP);
    LOG(" Puerto TCP (clientes) : %d", LB_TCP_PORT);
    LOG(" Puerto UDP (servers)  : %d", LB_UDP_PORT);
    LOG(" Servers registrados   : %d", SERVER_COUNT);
    LOG(" Estrategia            : Least Connections");
    LOG("==================================================");

    /* Loop principal */
    while (1) {
        struct sockaddr_in ca;
        socklen_t clen = sizeof(ca);
        int cfd = accept(g_tcp_sd, (struct sockaddr*)&ca, &clen);
        if (cfd < 0) { perror("accept"); continue; }

        char ip[INET_ADDRSTRLEN];
        inet_ntop(AF_INET, &ca.sin_addr, ip, sizeof(ip));
        LOG("[LB] Cliente desde %s", ip);

        pid_t pid = fork();
        if (pid < 0) { perror("fork"); close(cfd); continue; }
        if (pid == 0) { close(g_tcp_sd); atender_cliente(cfd); }
        close(cfd);
    }
    return 0;
}