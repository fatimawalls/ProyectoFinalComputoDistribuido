/*
 * clienteJSON.c — Cliente ChatRoom con protocolo JSON
 *
 * Compatible con chatServerJson.c / handbookRequestDB.txt
 *
 * Compilar:
 *   gcc clienteJSON.c database/libs/cJSON.c -Idatabase/libs -lpthread -o clienteJSON
 * Ejecutar:
 *   ./clienteJSON <host>
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

#include "cJSON.h"

 /* ─── Constantes ─────────────────────────────────────────────── */
#define TCP_PORT   5000
#define UDP_LOCAL  5100      /* puerto LOCAL donde escuchamos notificaciones */
#define BUFSIZE    8192

/* ─── Estado global ─────────────────────────────────────────── */
static int  g_tcp_fd = -1;
static int  g_udp_fd = -1;
static int  g_user_id = -1;
static char g_username[64] = "";

/* ══════════════════════════════════════════════════════════════
   UTILIDADES DE RED
   ══════════════════════════════════════════════════════════════ */

   /*
    * recv_line: lee bytes hasta '\n' o EOF.
    * Retorna bytes leídos, 0 si cierre limpio, <0 si error.
    */
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

/* send_line: envía msg + '\n' */
static void send_line(int fd, const char* msg)
{
    char buf[BUFSIZE];
    snprintf(buf, sizeof(buf), "%s\n", msg);
    send(fd, buf, strlen(buf), 0);
}

/* send_json_obj: serializa y envía un cJSON */
static void send_json_obj(int fd, cJSON* json)
{
    char* s = cJSON_PrintUnformatted(json);
    if (!s) return;
    send_line(fd, s);
    free(s);
}

/* ══════════════════════════════════════════════════════════════
   HILO UDP — notificaciones push del servidor
   ══════════════════════════════════════════════════════════════ */

static void* hilo_udp_listener(void* arg)
{
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

        cJSON* notif = cJSON_Parse(buf);
        if (!notif) {
            printf("\n[UDP] %s\n> ", buf);
            fflush(stdout);
            continue;
        }

        cJSON* jtype = cJSON_GetObjectItem(notif, "type");
        printf("\n");

        if (cJSON_IsString(jtype)) {
            const char* t = jtype->valuestring;

            if (strcmp(t, "NEW_MESSAGE_RESPONSE") == 0) {
                cJSON* msg = cJSON_GetObjectItem(notif, "message");
                cJSON* text = msg ? cJSON_GetObjectItem(msg, "text") : NULL;
                cJSON* uid = msg ? cJSON_GetObjectItem(msg, "userId") : NULL;
                cJSON* room = msg ? cJSON_GetObjectItem(msg, "chatRoomId") : NULL;
                printf("  ╔══ Nuevo mensaje (sala %d) ══\n",
                    room ? room->valueint : 0);
                printf("  ║  usuario %d: %s\n",
                    uid ? uid->valueint : 0,
                    text ? text->valuestring : "");
                printf("  ╚═══════════════════════════\n");
            }
            else if (strcmp(t, "ADD_USER_RESPONSE") == 0) {
                cJSON* cu = cJSON_GetObjectItem(notif, "chatUser");
                cJSON* room = cJSON_GetObjectItem(notif, "chatRoomId");
                cJSON* uname = cu ? cJSON_GetObjectItem(cu, "username") : NULL;
                printf("  >> Usuario '%s' agregado a sala %d\n",
                    uname ? uname->valuestring : "?",
                    room ? room->valueint : 0);
            }
            else if (strcmp(t, "REMOVE_USER_RESPONSE") == 0) {
                cJSON* uid = cJSON_GetObjectItem(notif, "userId");
                cJSON* room = cJSON_GetObjectItem(notif, "chatRoomId");
                printf("  >> Usuario %d eliminado de sala %d\n",
                    uid ? uid->valueint : 0,
                    room ? room->valueint : 0);
            }
            else if (strcmp(t, "DELETE_MESSAGE_RESPONSE") == 0) {
                cJSON* mid = cJSON_GetObjectItem(notif, "messageId");
                printf("  >> Mensaje #%d eliminado\n", mid ? mid->valueint : 0);
            }
            else if (strcmp(t, "DELETE_CHATROOM_RESPONSE") == 0) {
                cJSON* room = cJSON_GetObjectItem(notif, "chatRoomId");
                printf("  >> Sala #%d eliminada\n", room ? room->valueint : 0);
            }
            else if (strcmp(t, "NEW_CHATROOM_RESPONSE") == 0) {
                cJSON* cr = cJSON_GetObjectItem(notif, "chatRoom");
                cJSON* name = cr ? cJSON_GetObjectItem(cr, "name") : NULL;
                printf("  >> Nueva sala: %s\n", name ? name->valuestring : "?");
            }
            else {
                printf("  [UDP] %s\n", buf);
            }
        }
        else {
            printf("  [UDP] %s\n", buf);
        }
        cJSON_Delete(notif);
        printf("> ");
        fflush(stdout);
    }
    return NULL;
}

/* ══════════════════════════════════════════════════════════════
   AUTENTICACIÓN
   El servidor NO envía nada al conectar; el cliente habla primero.
   ══════════════════════════════════════════════════════════════ */

   /*
    * Retorna 1 si autenticado, 0 si el usuario eligió salir.
    */
static int hacer_auth(void)
{
    char buf[BUFSIZE];

    while (1) {
        printf("\n=== CHATROOM — Acceso al sistema ===\n");
        printf("  1) Iniciar sesion\n");
        printf("  2) Registrarse\n");
        printf("  0) Salir\n");
        printf("Opcion: ");
        fflush(stdout);

        char opcion[8];
        if (!fgets(opcion, sizeof(opcion), stdin)) return 0;
        opcion[strcspn(opcion, "\n")] = '\0';
        if (strcmp(opcion, "0") == 0) return 0;
        if (strcmp(opcion, "1") != 0 && strcmp(opcion, "2") != 0) {
            printf("Opcion invalida.\n");
            continue;
        }

        char user[64], pass[64];
        printf("Usuario: "); fflush(stdout);
        if (!fgets(user, sizeof(user), stdin)) return 0;
        user[strcspn(user, "\n")] = '\0';

        printf("Contrasena: "); fflush(stdout);
        if (!fgets(pass, sizeof(pass), stdin)) return 0;
        pass[strcspn(pass, "\n")] = '\0';

        if (!strlen(user) || !strlen(pass)) {
            printf("Error: campos vacios.\n");
            continue;
        }

        /* ── REGISTRAR ──────────────────────────────── */
        if (strcmp(opcion, "2") == 0) {
            cJSON* req = cJSON_CreateObject();
            cJSON_AddStringToObject(req, "type", "CREATE_ACCOUNT");
            cJSON_AddStringToObject(req, "username", user);
            cJSON_AddStringToObject(req, "password", pass);
            send_json_obj(g_tcp_fd, req);
            cJSON_Delete(req);

            /* Leer CREATE_ACCOUNT_RESPONSE */
            if (recv_line(g_tcp_fd, buf, sizeof(buf)) <= 0) {
                printf("Error: servidor cerro la conexion.\n");
                return 0;
            }
            cJSON* resp = cJSON_Parse(buf);
            if (!resp) {
                printf("Error: respuesta no es JSON (%s)\n", buf);
                continue;
            }
            cJSON* jtype = cJSON_GetObjectItem(resp, "type");
            if (cJSON_IsString(jtype) &&
                strcmp(jtype->valuestring, "CREATE_ACCOUNT_RESPONSE") == 0) {
                cJSON* success = cJSON_GetObjectItem(resp, "success");
                if (cJSON_IsTrue(success) || (cJSON_IsNumber(success) && success->valueint)) {
                    cJSON* jid = cJSON_GetObjectItem(resp, "id");
                    cJSON* juname = cJSON_GetObjectItem(resp, "username");
                    printf("  Registro exitoso. ID: %d, usuario: %s\n",
                        jid ? jid->valueint : -1,
                        juname ? juname->valuestring : "?");
                    printf("  Ahora inicia sesion.\n");
                }
                else {
                    printf("  Registro fallido.\n");
                }
            }
            else {
                printf("  Respuesta inesperada: %s\n", buf);
            }
            cJSON_Delete(resp);
            continue;   /* volver al menú para hacer login */
        }

        /* ── INICIAR SESIÓN ─────────────────────────── */
        cJSON* req = cJSON_CreateObject();
        cJSON_AddStringToObject(req, "type", "AUTH");
        cJSON_AddStringToObject(req, "username", user);
        cJSON_AddStringToObject(req, "password", pass);
        send_json_obj(g_tcp_fd, req);
        cJSON_Delete(req);

        /* Leer AUTH_RESPONSE */
        if (recv_line(g_tcp_fd, buf, sizeof(buf)) <= 0) {
            printf("Error: servidor cerro la conexion.\n");
            return 0;
        }
        cJSON* resp = cJSON_Parse(buf);
        if (!resp) {
            printf("Error: respuesta no es JSON (%s)\n", buf);
            continue;
        }
        cJSON* jtype = cJSON_GetObjectItem(resp, "type");
        if (!cJSON_IsString(jtype) ||
            strcmp(jtype->valuestring, "AUTH_RESPONSE") != 0) {
            printf("Respuesta inesperada: %s\n", buf);
            cJSON_Delete(resp);
            continue;
        }
        cJSON* success = cJSON_GetObjectItem(resp, "success");
        if (cJSON_IsTrue(success) || (cJSON_IsNumber(success) && success->valueint)) {
            cJSON* juid = cJSON_GetObjectItem(resp, "userId");
            cJSON* juname = cJSON_GetObjectItem(resp, "username");
            g_user_id = juid ? juid->valueint : -1;
            strncpy(g_username,
                juname ? juname->valuestring : "?",
                sizeof(g_username) - 1);
            printf("\n  Bienvenido, %s (ID: %d)\n", g_username, g_user_id);
            cJSON_Delete(resp);
            return 1;
        }
        else {
            printf("  Acceso denegado: credenciales invalidas.\n");
            cJSON_Delete(resp);
            continue;
        }
    }
}

/* ══════════════════════════════════════════════════════════════
   SYNC — recibir salas, usuarios y mensajes tras el login
   ══════════════════════════════════════════════════════════════ */

static void recibir_sync(void)
{
    char buf[BUFSIZE];
    printf("\n[SYNC] Recibiendo datos iniciales...\n");

    while (recv_line(g_tcp_fd, buf, sizeof(buf)) > 0) {
        cJSON* json = cJSON_Parse(buf);
        if (!json) { printf("  [SYNC] no-JSON: %s\n", buf); continue; }

        cJSON* jtype = cJSON_GetObjectItem(json, "type");
        if (!cJSON_IsString(jtype)) { cJSON_Delete(json); continue; }
        const char* t = jtype->valuestring;

        if (strcmp(t, "SYNC_START") == 0) {
            printf("  Sincronizacion iniciada.\n");
        }
        else if (strcmp(t, "CHATROOM") == 0) {
            cJSON* jid = cJSON_GetObjectItem(json, "id");
            cJSON* jname = cJSON_GetObjectItem(json, "name");
            printf("\n  Sala #%d: %s\n",
                jid ? jid->valueint : -1,
                jname ? jname->valuestring : "?");
        }
        else if (strcmp(t, "CHAT_USER") == 0) {
            cJSON* jid = cJSON_GetObjectItem(json, "id");
            cJSON* jname = cJSON_GetObjectItem(json, "name");
            printf("    └─ usuario %d: %s\n",
                jid ? jid->valueint : -1,
                jname ? jname->valuestring : "?");
        }
        else if (strcmp(t, "MESSAGE") == 0) {
            cJSON* jid = cJSON_GetObjectItem(json, "id");
            cJSON* juid = cJSON_GetObjectItem(json, "userId");
            cJSON* jtext = cJSON_GetObjectItem(json, "text");
            printf("    └─ msg #%d (uid %d): %s\n",
                jid ? jid->valueint : -1,
                juid ? juid->valueint : -1,
                jtext ? jtext->valuestring : "");
        }
        else if (strcmp(t, "SYNC_END") == 0) {
            printf("  Sincronizacion completada.\n");
            cJSON_Delete(json);
            break;
        }
        cJSON_Delete(json);
    }
    printf("  (Fin del sync)\n");
}

/* ══════════════════════════════════════════════════════════════
   MENÚ PRINCIPAL DE SESIÓN
   Maneja todos los request types del handbook.
   ══════════════════════════════════════════════════════════════ */

   /* Lee un entero del usuario */
static int leer_int(const char* prompt)
{
    char buf[32];
    printf("%s", prompt); fflush(stdout);
    if (!fgets(buf, sizeof(buf), stdin)) return -1;
    return atoi(buf);
}

/* Lee una cadena del usuario */
static void leer_str(const char* prompt, char* out, int maxlen)
{
    printf("%s", prompt); fflush(stdout);
    if (!fgets(out, maxlen, stdin)) { out[0] = '\0'; return; }
    out[strcspn(out, "\n")] = '\0';
}

/* Imprime la respuesta JSON recibida del servidor */
static void imprimir_respuesta(const char* buf)
{
    cJSON* resp = cJSON_Parse(buf);
    if (!resp) { printf("  Respuesta: %s\n", buf); return; }

    cJSON* jtype = cJSON_GetObjectItem(resp, "type");
    cJSON* jsuc = cJSON_GetObjectItem(resp, "success");
    int    suc = (cJSON_IsTrue(jsuc) || (cJSON_IsNumber(jsuc) && jsuc->valueint));
    const char* t = cJSON_IsString(jtype) ? jtype->valuestring : "?";

    printf("\n  [%s] %s\n", t, suc ? "OK" : "FALLO");

    /* Detalles adicionales según el tipo */
    if (strcmp(t, "NEW_MESSAGE_RESPONSE") == 0 && suc) {
        cJSON* msg = cJSON_GetObjectItem(resp, "message");
        cJSON* text = msg ? cJSON_GetObjectItem(msg, "text") : NULL;
        cJSON* mid = msg ? cJSON_GetObjectItem(msg, "id") : NULL;
        printf("  Mensaje #%d guardado: %s\n",
            mid ? mid->valueint : -1,
            text ? text->valuestring : "");
    }
    else if (strcmp(t, "NEW_CHATROOM_RESPONSE") == 0 && suc) {
        cJSON* cr = cJSON_GetObjectItem(resp, "chatRoom");
        cJSON* crid = cr ? cJSON_GetObjectItem(cr, "id") : NULL;
        cJSON* crn = cr ? cJSON_GetObjectItem(cr, "name") : NULL;
        printf("  Sala #%d '%s' creada.\n",
            crid ? crid->valueint : -1,
            crn ? crn->valuestring : "?");
    }
    else if (strcmp(t, "ADD_USER_RESPONSE") == 0 && suc) {
        cJSON* cu = cJSON_GetObjectItem(resp, "chatUser");
        cJSON* uname = cu ? cJSON_GetObjectItem(cu, "username") : NULL;
        printf("  Usuario '%s' agregado.\n",
            uname ? uname->valuestring : "?");
    }
    else if (strcmp(t, "DELETE_MESSAGE_RESPONSE") == 0 && suc) {
        cJSON* mid = cJSON_GetObjectItem(resp, "messageId");
        printf("  Mensaje #%d eliminado.\n", mid ? mid->valueint : -1);
    }
    else if (strcmp(t, "DELETE_CHATROOM_RESPONSE") == 0 && suc) {
        cJSON* room = cJSON_GetObjectItem(resp, "chatRoomId");
        printf("  Sala #%d eliminada.\n", room ? room->valueint : -1);
    }
    else if (strcmp(t, "REMOVE_USER_RESPONSE") == 0 && suc) {
        cJSON* uid = cJSON_GetObjectItem(resp, "userId");
        cJSON* room = cJSON_GetObjectItem(resp, "chatRoomId");
        printf("  Usuario %d eliminado de sala %d.\n",
            uid ? uid->valueint : -1,
            room ? room->valueint : -1);
    }
    cJSON_Delete(resp);
}

static void menu_sesion(void)
{
    char buf[BUFSIZE];

    while (1) {
        printf("\n========== MENU (uid=%d / %s) ==========\n",
            g_user_id, g_username);
        printf("  1) Enviar mensaje\n");
        printf("  2) Crear sala\n");
        printf("  3) Agregar usuario a sala\n");
        printf("  4) Eliminar usuario de sala\n");
        printf("  5) Eliminar mensaje\n");
        printf("  6) Eliminar sala\n");
        printf("  0) Salir\n");
        printf("> "); fflush(stdout);

        char opcion[8];
        if (!fgets(opcion, sizeof(opcion), stdin)) break;
        opcion[strcspn(opcion, "\n")] = '\0';

        cJSON* req = NULL;

        if (strcmp(opcion, "0") == 0) break;

        /* ── 1) NEW_MESSAGE ─────────────────────────── */
        else if (strcmp(opcion, "1") == 0) {
            char text[512];
            int  room = leer_int("  ID de sala: ");
            leer_str("  Mensaje: ", text, sizeof(text));
            req = cJSON_CreateObject();
            cJSON_AddStringToObject(req, "type", "NEW_MESSAGE");
            cJSON_AddStringToObject(req, "text", text);
            cJSON_AddNumberToObject(req, "userId", g_user_id);
            cJSON_AddNumberToObject(req, "chatRoomId", room);
        }

        /* ── 2) NEW_CHATROOM ────────────────────────── */
        else if (strcmp(opcion, "2") == 0) {
            char name[128];
            leer_str("  Nombre de sala: ", name, sizeof(name));
            req = cJSON_CreateObject();
            cJSON_AddStringToObject(req, "type", "NEW_CHATROOM");
            cJSON_AddStringToObject(req, "name", name);
            cJSON_AddNumberToObject(req, "coordinatorId", g_user_id);
        }

        /* ── 3) ADD_USER ────────────────────────────── */
        else if (strcmp(opcion, "3") == 0) {
            int room = leer_int("  ID de sala: ");
            int uid = leer_int("  ID de usuario a agregar: ");
            req = cJSON_CreateObject();
            cJSON_AddStringToObject(req, "type", "ADD_USER");
            cJSON_AddNumberToObject(req, "chatRoomId", room);
            cJSON_AddNumberToObject(req, "userId", uid);
        }

        /* ── 4) REMOVE_USER ─────────────────────────── */
        else if (strcmp(opcion, "4") == 0) {
            int room = leer_int("  ID de sala: ");
            int uid = leer_int("  ID de usuario a eliminar: ");
            req = cJSON_CreateObject();
            cJSON_AddStringToObject(req, "type", "REMOVE_USER");
            cJSON_AddNumberToObject(req, "chatRoomId", room);
            cJSON_AddNumberToObject(req, "userId", uid);
        }

        /* ── 5) DELETE_MESSAGE ──────────────────────── */
        else if (strcmp(opcion, "5") == 0) {
            int mid = leer_int("  ID del mensaje: ");
            req = cJSON_CreateObject();
            cJSON_AddStringToObject(req, "type", "DELETE_MESSAGE");
            cJSON_AddNumberToObject(req, "messageId", mid);
        }

        /* ── 6) DELETE_CHATROOM ─────────────────────── */
        else if (strcmp(opcion, "6") == 0) {
            int room = leer_int("  ID de sala: ");
            req = cJSON_CreateObject();
            cJSON_AddStringToObject(req, "type", "DELETE_CHATROOM");
            cJSON_AddNumberToObject(req, "chatRoomId", room);
        }

        else {
            printf("  Opcion invalida.\n");
            continue;
        }

        if (!req) continue;

        /* Enviar request y esperar respuesta */
        send_json_obj(g_tcp_fd, req);
        cJSON_Delete(req);

        if (recv_line(g_tcp_fd, buf, sizeof(buf)) <= 0) {
            printf("  Error: servidor desconectado.\n");
            break;
        }
        imprimir_respuesta(buf);
    }
}

/* ══════════════════════════════════════════════════════════════
   MAIN
   ══════════════════════════════════════════════════════════════ */

int main(int argc, char* argv[])
{
    if (argc != 2) {
        fprintf(stderr, "Uso: %s <host>\n", argv[0]);
        exit(1);
    }
    const char* host = argv[1];

    /* Socket UDP local para notificaciones push */
    g_udp_fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (g_udp_fd == -1) { perror("udp socket"); exit(1); }
    struct sockaddr_in udp_local;
    memset(&udp_local, 0, sizeof(udp_local));
    udp_local.sin_family = AF_INET;
    udp_local.sin_addr.s_addr = INADDR_ANY;
    udp_local.sin_port = htons(UDP_LOCAL);
    if (bind(g_udp_fd, (struct sockaddr*)&udp_local, sizeof(udp_local)) == -1) {
        perror("udp bind");
        fprintf(stderr, "Puerto %d en uso — cambia UDP_LOCAL en el fuente\n", UDP_LOCAL);
        exit(1);
    }
    pthread_t tid;
    pthread_create(&tid, NULL, hilo_udp_listener, NULL);
    pthread_detach(tid);

    /* Conexión TCP */
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
    printf("Notificaciones UDP en puerto local %d\n\n", UDP_LOCAL);

    /*
     * El servidor NO envía nada al conectar.
     * El cliente inicia la conversación con AUTH o CREATE_ACCOUNT.
     */

     /* Autenticación */
    if (!hacer_auth()) {
        printf("Saliendo.\n");
        close(g_tcp_fd);
        close(g_udp_fd);
        return 0;
    }

    /* Sync inicial */
    recibir_sync();

    /* Sesión interactiva */
    menu_sesion();

    close(g_tcp_fd);
    close(g_udp_fd);
    printf("Adios.\n");
    return 0;
}