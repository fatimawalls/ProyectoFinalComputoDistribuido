/*
 * client.c — ChatRoom Client (consola)
 * Arquitectura:
 *   - Hilo principal: envia comandos al servidor (TCP)
 *   - Hilo UDP: escucha notificaciones push del servidor
 *
 * Compilar: gcc client.c -lpthread -o client
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
static int  g_tcp_fd = -1;
static int  g_udp_fd = -1;
static int  g_user_id = -1;
static char g_username[64] = "";

/* ══════════════════════════════════════════════════════════════════════════
   UTILIDADES DE RED
   ══════════════════════════════════════════════════════════════════════════ */

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

void send_line(int fd, const char* msg) {
    char buf[BUFSIZE];
    snprintf(buf, sizeof(buf), "%s\n", msg);
    send(fd, buf, strlen(buf), 0);
}

/* ══════════════════════════════════════════════════════════════════════════
   HILO UDP — escucha notificaciones push del servidor
   ══════════════════════════════════════════════════════════════════════════ */

void* hilo_udp_listener(void* arg) {
    (void)arg;
    char buf[BUFSIZE];
    struct sockaddr_in src;
    socklen_t slen = sizeof(src);

    while (1) {
        int n = recvfrom(g_udp_fd, buf, sizeof(buf) - 1, 0,
            (struct sockaddr*)&src, &slen);
        if (n <= 0) break;
        buf[n] = '\0';
        buf[strcspn(buf, "\n")] = '\0';

        /* Interpretar la notificacion y mostrarla de forma legible */
        printf("\n");

        if (strncmp(buf, "NOTIF_NEW_MSG:", 14) == 0) {
            /* Formato: NOTIF_NEW_MSG:room_id:msg_id:user_id=username:texto */
            int room_id, msg_id, user_id;
            char username[64], texto[BUFSIZE];
            if (sscanf(buf + 14, "%d:%d:%d=%63[^:]:%1023[^\n]",
                &room_id, &msg_id, &user_id, username, texto) == 5) {
                printf("  ╔══ Nuevo mensaje en sala %d ══\n", room_id);
                printf("  ║  [%s]: %s\n", username, texto);
                printf("  ╚══════════════════════════════\n");
            }
            else {
                printf("  [NOTIF] %s\n", buf);
            }

        }
        else if (strncmp(buf, "NOTIF_USER_JOINED:", 18) == 0) {
            /* Formato: NOTIF_USER_JOINED:room_id:username */
            printf("  >> Usuario entro a una sala: %s\n", buf + 18);

        }
        else if (strncmp(buf, "NOTIF_USER_LEFT:", 16) == 0) {
            printf("  >> Usuario salio de una sala: %s\n", buf + 16);

        }
        else if (strncmp(buf, "NOTIF_USER_OFFLINE:", 19) == 0) {
            printf("  >> Usuario desconectado: %s\n", buf + 19);

        }
        else if (strncmp(buf, "NOTIF_ROOM_CREATED:", 19) == 0) {
            printf("  >> Nueva sala creada: %s\n", buf + 19);

        }
        else if (strncmp(buf, "NOTIF_ROOM_DELETED:", 19) == 0) {
            printf("  >> Sala eliminada: %s\n", buf + 19);

        }
        else if (strncmp(buf, "NOTIF_ACCEPTED:", 15) == 0) {
            printf("  >> Fuiste aceptado en la sala %s\n", buf + 15);

        }
        else if (strncmp(buf, "NOTIF_REJECTED:", 15) == 0) {
            printf("  >> Tu solicitud fue rechazada en sala %s\n", buf + 15);

        }
        else if (strncmp(buf, "NOTIF_KICKED:", 13) == 0) {
            printf("  >> Fuiste expulsado de la sala %s\n", buf + 13);

        }
        else if (strncmp(buf, "NOTIF_INVITED:", 14) == 0) {
            printf("  >> Fuiste invitado a la sala: %s\n", buf + 14);

        }
        else if (strncmp(buf, "NOTIF_JOIN_REQUEST:", 19) == 0) {
            /* Formato: NOTIF_JOIN_REQUEST:room_id:user_id=username */
            printf("  >> Solicitud de ingreso en sala: %s\n", buf + 19);

        }
        else {
            printf("  [NOTIF] %s\n", buf);
        }

        printf("> ");
        fflush(stdout);
    }
    return NULL;
}

/* ══════════════════════════════════════════════════════════════════════════
   AUTENTICACION
   ══════════════════════════════════════════════════════════════════════════ */

int hacer_auth(void) {
    char buf[BUFSIZE];

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
        }
        else if (strcmp(opcion, "2") == 0) {
            snprintf(msg, sizeof(msg), "REGISTRO:%s:%s", user, pass);
        }
        else {
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
    printf("\n╔══════════════════════════════════╗\n");
    printf("║           E-LOBBY                ║\n");
    printf("╠══════════════════════════════════╣\n");
    printf("║  1) Ver usuarios activos         ║\n");
    printf("║  2) Ver chatrooms                ║\n");
    printf("║  3) Crear chatroom               ║\n");
    printf("║  4) Solicitar unirme a room      ║\n");
    printf("║  m) Mandar mensaje a room        ║\n");  /* NUEVO */
    printf("║  h) Ver historial de room        ║\n");  /* NUEVO */
    printf("║  5) [COORD] Aceptar usuario      ║\n");
    printf("║  6) [COORD] Rechazar usuario     ║\n");
    printf("║  7) [COORD] Expulsar usuario     ║\n");
    printf("║  8) [COORD] Invitar usuario      ║\n");
    printf("║  9) [COORD] Borrar room          ║\n");
    printf("║  n) Cambiar nickname             ║\n");
    printf("║  0) Salir                        ║\n");
    printf("╚══════════════════════════════════╝\n");
    printf("> ");
    fflush(stdout);
}

void recibir_y_mostrar(void) {
    char resp[BUFSIZE];
    if (recv_line(g_tcp_fd, resp, sizeof(resp)) > 0)
        printf("  Servidor: %s\n", resp);
}

/* ══════════════════════════════════════════════════════════════════════════
   MANDAR MENSAJE A UNA ROOM
   ══════════════════════════════════════════════════════════════════════════ */

void mandar_mensaje(void) {
    char input[128];
    char cmd[BUFSIZE];
    char resp[BUFSIZE];

    printf("ID de la sala: ");
    if (!fgets(input, sizeof(input), stdin)) return;
    input[strcspn(input, "\n")] = '\0';
    char room_id[16];
    strncpy(room_id, input, sizeof(room_id) - 1);

    printf("Mensaje: ");
    if (!fgets(input, sizeof(input), stdin)) return;
    input[strcspn(input, "\n")] = '\0';

    if (!strlen(input)) {
        printf("  Mensaje vacio, cancelado.\n");
        return;
    }

    /* Formato: ROOM_MSG:room_id:texto */
    snprintf(cmd, sizeof(cmd), "ROOM_MSG:%s:%s", room_id, input);
    send_line(g_tcp_fd, cmd);

    if (recv_line(g_tcp_fd, resp, sizeof(resp)) > 0) {
        if (strncmp(resp, "MSG_OK:", 7) == 0) {
            printf("  Mensaje enviado (ID: %s)\n", resp + 7);
        }
        else {
            printf("  Error: %s\n", resp);
        }
    }
}

/* ══════════════════════════════════════════════════════════════════════════
   VER HISTORIAL DE UNA ROOM
   ══════════════════════════════════════════════════════════════════════════ */

void ver_historial(void) {
    char input[128];
    char cmd[BUFSIZE];
    char resp[BUFSIZE];

    printf("ID de la sala: ");
    if (!fgets(input, sizeof(input), stdin)) return;
    input[strcspn(input, "\n")] = '\0';

    /* Formato: LOBBY_GET_MESSAGES:room_id */
    snprintf(cmd, sizeof(cmd), "LOBBY_GET_MESSAGES:%s", input);
    send_line(g_tcp_fd, cmd);

    if (recv_line(g_tcp_fd, resp, sizeof(resp)) <= 0) return;

    if (strncmp(resp, "MSG_FAIL:", 9) == 0) {
        printf("  Error: %s\n", resp + 9);
        return;
    }

    if (strcmp(resp, "MESSAGES_LIST:") == 0) {
        printf("  No hay mensajes en esta sala.\n");
        return;
    }

    /* Formato recibido: MESSAGES_LIST:msg_id:user_id:texto|msg_id:user_id:texto|... */
    printf("\n  ╔══════════ Historial ══════════╗\n");

    char* lista = resp + 14; /* saltar "MESSAGES_LIST:" */
    char* token = strtok(lista, "|");
    int count = 1;

    while (token != NULL) {
        int msg_id, user_id;
        char texto[BUFSIZE];

        /* Parsear msg_id:user_id:texto */
        if (sscanf(token, "%d:%d:%1023[^\n]", &msg_id, &user_id, texto) == 3) {
            printf("  ║  #%-3d [user:%d]: %s\n", count, user_id, texto);
        }
        else {
            printf("  ║  %s\n", token);
        }
        count++;
        token = strtok(NULL, "|");
    }

    printf("  ╚══════════════════════════════╝\n");
}

/* ══════════════════════════════════════════════════════════════════════════
   LOOP PRINCIPAL DEL LOBBY
   ══════════════════════════════════════════════════════════════════════════ */

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

        /* ── Mandar mensaje (NUEVO) ────────────────────────────────── */
        if (strcmp(input, "m") == 0) {
            mandar_mensaje();
            continue;
        }

        /* ── Ver historial (NUEVO) ─────────────────────────────────── */
        if (strcmp(input, "h") == 0) {
            ver_historial();
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

int main(int argc, char* argv[]) {
    if (argc != 2) {
        fprintf(stderr, "Uso: %s <host>\n", argv[0]);
        exit(1);
    }
    const char* host = argv[1];

    /* Socket UDP local (escucha notificaciones) */
    g_udp_fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (g_udp_fd == -1) { perror("udp socket"); exit(1); }
    struct sockaddr_in udp_local;
    memset(&udp_local, 0, sizeof(udp_local));
    udp_local.sin_family = AF_INET;
    udp_local.sin_addr.s_addr = INADDR_ANY;
    udp_local.sin_port = htons(UDP_LOCAL);
    if (bind(g_udp_fd, (struct sockaddr*)&udp_local, sizeof(udp_local)) == -1) {
        perror("udp bind");
        fprintf(stderr, "Cambia UDP_LOCAL si el puerto %d esta en uso\n", UDP_LOCAL);
        exit(1);
    }

    /* Hilo UDP */
    pthread_t tid;
    pthread_create(&tid, NULL, hilo_udp_listener, NULL);
    pthread_detach(tid);

    /* Conexion TCP */
    struct hostent* he = gethostbyname(host);
    if (!he) { fprintf(stderr, "Host no encontrado: %s\n", host); exit(1); }

    g_tcp_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (g_tcp_fd == -1) { perror("tcp socket"); exit(1); }

    struct sockaddr_in srv;
    memset(&srv, 0, sizeof(srv));
    srv.sin_family = AF_INET;
    srv.sin_port = htons(TCP_PORT);
    memcpy(&srv.sin_addr, he->h_addr, he->h_length);

    if (connect(g_tcp_fd, (struct sockaddr*)&srv, sizeof(srv)) == -1) {
        perror("connect"); exit(1);
    }
    printf("Conectado a %s:%d\n", host, TCP_PORT);
    printf("Notificaciones UDP en puerto local %d\n", UDP_LOCAL);

    /* Auth */
    if (!hacer_auth()) {
        printf("Saliendo.\n");
        close(g_tcp_fd);
        close(g_udp_fd);
        return 0;
    }

    /* Lobby */
    lobby_loop();

    close(g_tcp_fd);
    close(g_udp_fd);
    printf("Adios.\n");
    return 0;
}