/*
 * client.c — ChatRoom Client (consola)
 * Arquitectura:
 *   - Hilo principal: envia comandos al servidor (TCP)
 *   - Hilo UDP: escucha notificaciones push del servidor
 *
 * Compilar: cc client.c -lpthread -o client
 * Ejecutar:  ./client <host>
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <pthread.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <netdb.h>

/* ─── Constantes ─────────────────────────────────────────────────────────── */
#define TCP_PORT   5000
#define UDP_PORT   5001      /* puerto donde el SERVIDOR envia notificaciones */
#define UDP_LOCAL  5100      /* puerto LOCAL donde este cliente escucha UDP   */
#define BUFSIZE    1024

/* ─── Estado del cliente ─────────────────────────────────────────────────── */
static int  g_tcp_fd  = -1;
static int  g_udp_fd  = -1;
static int  g_user_id = -1;
static char g_username[64] = "";

/* ══════════════════════════════════════════════════════════════════════════
   UTILIDADES DE RED
   ══════════════════════════════════════════════════════════════════════════ */

int recv_line(int fd, char *buf, int maxlen) {
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

void send_line(int fd, const char *msg) {
    char buf[BUFSIZE];
    snprintf(buf, sizeof(buf), "%s\n", msg);
    send(fd, buf, strlen(buf), 0);
}

/* ══════════════════════════════════════════════════════════════════════════
   HILO UDP — escucha notificaciones push del servidor
   ══════════════════════════════════════════════════════════════════════════ */

void *hilo_udp_listener(void *arg) {
    (void)arg;
    char buf[BUFSIZE];
    struct sockaddr_in src;
    socklen_t slen = sizeof(src);

    while (1) {
        int n = recvfrom(g_udp_fd, buf, sizeof(buf)-1, 0,
                         (struct sockaddr *)&src, &slen);
        if (n <= 0) break;
        buf[n] = '\0';
        /* Quitar el \n si lo hay */
        buf[strcspn(buf, "\n")] = '\0';

        /* Mostrar la notificacion de forma clara en consola */
        printf("\n  [NOTIF] %s\n> ", buf);
        fflush(stdout);
    }
    return NULL;
}

/* ══════════════════════════════════════════════════════════════════════════
   AUTENTICACION
   ══════════════════════════════════════════════════════════════════════════ */

/*
 * Protocolo:
 *   Server -> "AUTH_REQUERIDA"
 *   Client -> "LOGIN:user:pass:udp_port"  o  "REGISTRO:user:pass"
 *   Server -> "AUTH_OK:uid"  /  "AUTH_FAIL:razon"  /  "REGISTRO_OK"
 */
int hacer_auth(void) {
    char buf[BUFSIZE];

    /* Esperar AUTH_REQUERIDA */
    if (recv_line(g_tcp_fd, buf, sizeof(buf)) <= 0) {
        printf("Error: servidor cerro la conexion\n"); return 0;
    }
    if (strcmp(buf, "AUTH_REQUERIDA") != 0) {
        printf("Protocolo inesperado: %s\n", buf); return 0;
    }

    while (1) {
        printf("\n=== CHATROOM — Acceso al sistema ===\n");
        printf("  1) Iniciar sesion\n");
        printf("  2) Registrarse\n");
        printf("  0) Salir\n");
        printf("Opcion: ");

        char opcion[8];
        if (!fgets(opcion, sizeof(opcion), stdin)) return 0;
        opcion[strcspn(opcion, "\n")] = '\0';

        if (strcmp(opcion, "0") == 0) return 0;

        char user[64], pass[64];
        printf("Usuario: ");
        if (!fgets(user, sizeof(user), stdin)) return 0;
        user[strcspn(user, "\n")] = '\0';

        printf("Contrasena: ");
        if (!fgets(pass, sizeof(pass), stdin)) return 0;
        pass[strcspn(pass, "\n")] = '\0';

        if (!strlen(user) || !strlen(pass)) {
            printf("Error: campos vacios\n"); continue;
        }

        char msg[BUFSIZE];
        if (strcmp(opcion, "1") == 0) {
            snprintf(msg, sizeof(msg), "LOGIN:%s:%s:%d", user, pass, UDP_LOCAL);
        } else if (strcmp(opcion, "2") == 0) {
            snprintf(msg, sizeof(msg), "REGISTRO:%s:%s", user, pass);
        } else {
            printf("Opcion invalida\n"); continue;
        }

        send_line(g_tcp_fd, msg);

        if (recv_line(g_tcp_fd, buf, sizeof(buf)) <= 0) {
            printf("Servidor cerro la conexion\n"); return 0;
        }

        if (strcmp(buf, "REGISTRO_OK") == 0) {
            printf("  Registro exitoso. Ahora inicia sesion.\n");
            continue;
        }
        if (strncmp(buf, "REGISTRO_FAIL:", 14) == 0) {
            printf("  Registro fallido: %s\n", buf + 14);
            continue;
        }
        if (strncmp(buf, "AUTH_OK:", 8) == 0) {
            g_user_id = atoi(buf + 8);
            strncpy(g_username, user, sizeof(g_username) - 1);
            printf("\n  Bienvenido, %s (ID: %d)\n", g_username, g_user_id);
            return 1;
        }
        if (strncmp(buf, "AUTH_FAIL:", 10) == 0) {
            printf("  Acceso denegado: %s\n", buf + 10);
            continue;
        }
        printf("  Respuesta inesperada: %s\n", buf);
    }
}

/* ══════════════════════════════════════════════════════════════════════════
   MENU DE LOBBY
   ══════════════════════════════════════════════════════════════════════════ */

void imprimir_menu_lobby(void) {
    printf("\n╔══════════════════════════════╗\n");
    printf("║         E-LOBBY              ║\n");
    printf("╠══════════════════════════════╣\n");
    printf("║  1) Ver usuarios activos     ║\n");
    printf("║  2) Ver chatrooms            ║\n");
    printf("║  3) Crear chatroom           ║\n");
    printf("║  4) Solicitar unirme a room  ║\n");
    printf("║  5) [COORD] Aceptar usuario  ║\n");
    printf("║  6) [COORD] Rechazar usuario ║\n");
    printf("║  7) [COORD] Expulsar usuario ║\n");
    printf("║  8) [COORD] Invitar usuario  ║\n");
    printf("║  9) [COORD] Borrar room      ║\n");
    printf("║  n) Cambiar nickname         ║\n");
    printf("║  0) Salir                    ║\n");
    printf("╚══════════════════════════════╝\n");
    printf("> ");
    fflush(stdout);
}

void recibir_y_mostrar(void) {
    char resp[BUFSIZE];
    if (recv_line(g_tcp_fd, resp, sizeof(resp)) > 0)
        printf("  Servidor: %s\n", resp);
}

void lobby_loop(void) {
    char buf[BUFSIZE];
    char cmd[BUFSIZE];
    char input[128];

    /* Esperar LOBBY_OK */
    if (recv_line(g_tcp_fd, buf, sizeof(buf)) > 0)
        printf("\n  %s\n", buf);

    while (1) {
        imprimir_menu_lobby();

        if (!fgets(input, sizeof(input), stdin)) break;
        input[strcspn(input, "\n")] = '\0';

        /* ── Ver usuarios ──────────────────────────────────────────── */
        if (strcmp(input, "1") == 0) {
            send_line(g_tcp_fd, "LOBBY_LIST_USERS");
            recibir_y_mostrar();
            continue;
        }

        /* ── Ver rooms ─────────────────────────────────────────────── */
        if (strcmp(input, "2") == 0) {
            send_line(g_tcp_fd, "LOBBY_LIST_ROOMS");
            recibir_y_mostrar();
            continue;
        }

        /* ── Crear room ────────────────────────────────────────────── */
        if (strcmp(input, "3") == 0) {
            printf("Nombre de la room: ");
            if (!fgets(input, sizeof(input), stdin)) continue;
            input[strcspn(input, "\n")] = '\0';
            snprintf(cmd, sizeof(cmd), "LOBBY_CREATE_ROOM:%s", input);
            send_line(g_tcp_fd, cmd);
            recibir_y_mostrar();
            continue;
        }

        /* ── Solicitar unirme ──────────────────────────────────────── */
        if (strcmp(input, "4") == 0) {
            printf("ID de la room: ");
            if (!fgets(input, sizeof(input), stdin)) continue;
            input[strcspn(input, "\n")] = '\0';
            snprintf(cmd, sizeof(cmd), "LOBBY_JOIN_REQUEST:%s", input);
            send_line(g_tcp_fd, cmd);
            recibir_y_mostrar();
            continue;
        }

        /* ── Aceptar usuario (coord) ───────────────────────────────── */
        if (strcmp(input, "5") == 0) {
            printf("ID de la room: ");
            char rid[16];
            if (!fgets(rid, sizeof(rid), stdin)) continue;
            rid[strcspn(rid, "\n")] = '\0';
            printf("ID del usuario a aceptar: ");
            char uid[16];
            if (!fgets(uid, sizeof(uid), stdin)) continue;
            uid[strcspn(uid, "\n")] = '\0';
            snprintf(cmd, sizeof(cmd), "COORD_ACCEPT:%s:%s", rid, uid);
            send_line(g_tcp_fd, cmd);
            recibir_y_mostrar();
            continue;
        }

        /* ── Rechazar usuario (coord) ──────────────────────────────── */
        if (strcmp(input, "6") == 0) {
            printf("ID de la room: ");
            char rid[16];
            if (!fgets(rid, sizeof(rid), stdin)) continue;
            rid[strcspn(rid, "\n")] = '\0';
            printf("ID del usuario a rechazar: ");
            char uid[16];
            if (!fgets(uid, sizeof(uid), stdin)) continue;
            uid[strcspn(uid, "\n")] = '\0';
            snprintf(cmd, sizeof(cmd), "COORD_REJECT:%s:%s", rid, uid);
            send_line(g_tcp_fd, cmd);
            recibir_y_mostrar();
            continue;
        }

        /* ── Expulsar usuario (coord) ──────────────────────────────── */
        if (strcmp(input, "7") == 0) {
            printf("ID de la room: ");
            char rid[16];
            if (!fgets(rid, sizeof(rid), stdin)) continue;
            rid[strcspn(rid, "\n")] = '\0';
            printf("ID del usuario a expulsar: ");
            char uid[16];
            if (!fgets(uid, sizeof(uid), stdin)) continue;
            uid[strcspn(uid, "\n")] = '\0';
            snprintf(cmd, sizeof(cmd), "COORD_KICK:%s:%s", rid, uid);
            send_line(g_tcp_fd, cmd);
            recibir_y_mostrar();
            continue;
        }

        /* ── Invitar usuario (coord) ───────────────────────────────── */
        if (strcmp(input, "8") == 0) {
            printf("ID de la room: ");
            char rid[16];
            if (!fgets(rid, sizeof(rid), stdin)) continue;
            rid[strcspn(rid, "\n")] = '\0';
            printf("ID del usuario a invitar: ");
            char uid[16];
            if (!fgets(uid, sizeof(uid), stdin)) continue;
            uid[strcspn(uid, "\n")] = '\0';
            snprintf(cmd, sizeof(cmd), "COORD_INVITE:%s:%s", rid, uid);
            send_line(g_tcp_fd, cmd);
            recibir_y_mostrar();
            continue;
        }

        /* ── Borrar room (coord) ───────────────────────────────────── */
        if (strcmp(input, "9") == 0) {
            printf("ID de la room a borrar: ");
            if (!fgets(input, sizeof(input), stdin)) continue;
            input[strcspn(input, "\n")] = '\0';
            snprintf(cmd, sizeof(cmd), "COORD_DELETE_ROOM:%s", input);
            send_line(g_tcp_fd, cmd);
            recibir_y_mostrar();
            continue;
        }

        /* ── Cambiar nickname ──────────────────────────────────────── */
        if (strcmp(input, "n") == 0) {
            printf("Nuevo nickname: ");
            if (!fgets(input, sizeof(input), stdin)) continue;
            input[strcspn(input, "\n")] = '\0';
            snprintf(cmd, sizeof(cmd), "LOBBY_SET_NICK:%s", input);
            send_line(g_tcp_fd, cmd);
            recibir_y_mostrar();
            continue;
        }

        /* ── Salir ─────────────────────────────────────────────────── */
        if (strcmp(input, "0") == 0) {
            printf("  Cerrando sesion...\n");
            break;
        }

        printf("  Opcion invalida\n");
    }
}

/* ══════════════════════════════════════════════════════════════════════════
   MAIN
   ══════════════════════════════════════════════════════════════════════════ */

int main(int argc, char *argv[]) {
    if (argc != 2) {
        fprintf(stderr, "Uso: %s <host>\n", argv[0]);
        exit(1);
    }
    const char *host = argv[1];

    /* ── Socket UDP local (escucha notificaciones) ───────────────────────── */
    g_udp_fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (g_udp_fd == -1) { perror("udp socket"); exit(1); }
    struct sockaddr_in udp_local;
    memset(&udp_local, 0, sizeof(udp_local));
    udp_local.sin_family      = AF_INET;
    udp_local.sin_addr.s_addr = INADDR_ANY;
    udp_local.sin_port        = htons(UDP_LOCAL);
    if (bind(g_udp_fd, (struct sockaddr *)&udp_local, sizeof(udp_local)) == -1) {
        perror("udp bind");
        fprintf(stderr, "Nota: cambia UDP_LOCAL si el puerto %d esta en uso\n", UDP_LOCAL);
        exit(1);
    }

    /* ── Hilo UDP ────────────────────────────────────────────────────────── */
    pthread_t tid;
    pthread_create(&tid, NULL, hilo_udp_listener, NULL);
    pthread_detach(tid);

    /* ── Conexion TCP ────────────────────────────────────────────────────── */
    struct hostent *he = gethostbyname(host);
    if (!he) { fprintf(stderr, "Host no encontrado: %s\n", host); exit(1); }

    g_tcp_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (g_tcp_fd == -1) { perror("tcp socket"); exit(1); }

    struct sockaddr_in srv;
    memset(&srv, 0, sizeof(srv));
    srv.sin_family = AF_INET;
    srv.sin_port   = htons(TCP_PORT);
    memcpy(&srv.sin_addr, he->h_addr, he->h_length);

    if (connect(g_tcp_fd, (struct sockaddr *)&srv, sizeof(srv)) == -1) {
        perror("connect"); exit(1);
    }
    printf("Conectado a %s:%d\n", host, TCP_PORT);
    printf("Notificaciones UDP en puerto local %d\n", UDP_LOCAL);

    /* ── Auth ────────────────────────────────────────────────────────────── */
    if (!hacer_auth()) {
        printf("Saliendo.\n");
        close(g_tcp_fd);
        close(g_udp_fd);
        return 0;
    }

    /* ── Lobby ───────────────────────────────────────────────────────────── */
    lobby_loop();

    close(g_tcp_fd);
    close(g_udp_fd);
    printf("Adios.\n");
    return 0;
}
